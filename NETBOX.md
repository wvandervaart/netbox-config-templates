# How NetBox data drives these templates

These templates are registered in NetBox as Config Templates and rendered via `render_config()`. The context NetBox hands to Jinja2 is `{"device": device, **device.get_config_context()}`, plus each role's `main.j2` prefetching `netbox_bgp` querysets (`bgp_sessions`, `bgp_peer_groups`) and `device.interfaces.all()` as `device_interfaces` (see `CLAUDE.md` for the prefetch pattern and repo/template structure).

Templates pull from three NetBox data channels: **custom fields**, **tags**, and **config context**. This doc catalogs what's actually read today. `scaffold/provision_netbox_schema.py` provisions the custom fields and tags below on a NetBox instance (idempotent, safe to rerun) — see that file's docstring for usage.

## Custom fields

Accessed as `object.cf.FIELD` (raises if the custom field isn't defined on that object type's schema) or `object.cf.get('FIELD')` (safe, returns `None`/falsy if unset) — templates mix both depending on whether the field is guaranteed present.

### Device

| Field | Purpose |
|---|---|
| `VSTP_ENABLED` | Enables VSTP (per-VLAN spanning tree) globally |
| `VSTP_BRIDGEID` | VSTP system-identifier |
| `VSTP_BRIDGEPRIO` | VSTP bridge-priority |
| `VSTP_ALL_INT_ENABLED` | Enables VSTP on all interfaces by default |
| `GNMI_MONITORED` | Enables gRPC/gNMI telemetry config |
| `DEFAULT_AS_PREPEND` | Default AS-path prepend count in BGP export policy |

### Interface

| Field | Purpose |
|---|---|
| `RSTP_OFF` | Disables RSTP on the interface |
| `QFX_PORTGROUP` | Maps interface to a chassis FPC/PIC port-group for speed config |
| `SFLOW` | Enables sFlow monitoring on the interface |
| `LLDP_OFF` | Disables LLDP on the interface |
| `VSTP_OFF` | Disables VSTP on the interface (overrides device default) |
| `IXPORT` | Marks an IX/peering port — affects ARP policer and filter selection |
| `INPUT_FILTER` / `OUTPUT_FILTER` | Firewall filter name applied inbound/outbound (special value `"re-protect"` triggers the RE-protection filter) |
| `INPUT_FILTER_V6` | IPv6 inbound firewall filter (special value `"re-protect_V6"`) |
| `FABRIC` | Marks the interface as underlay/fabric-facing — affects VRF/routing-instance logic. **Not the same as the device `fabric` tag below** — same-ish name, different mechanism |
| `FEC` | List of forward-error-correction modes to configure on the port |
| `IGMPIFACEDISABLE` | Disables IGMP on the interface |
| `IGMPIFACEVERSION` | IGMP protocol version for the interface |
| `PIMIFACEMODE` / `PIMIFACEPRIO` / `PIMIFACEHELLO` | PIM interface mode / DR priority / hello-interval |
| `OSPF_AREA` | OSPF area for the interface — also gates whether OSPF is enabled at all |
| `OSPF_VERSION` | `"2"`, `"3"`, or `"23"` — which OSPF version(s) to configure |
| `OSPF_PASSIVE` | Marks the OSPF interface passive |
| `OSPF_BFD` | Enables BFD for OSPF on the interface |
| `OSPF_NETWORK_TYPE` | OSPF interface network type |

### VRF

| Field | Purpose |
|---|---|
| `VNI` | Object reference to a VLAN/VNI object, linking the VRF to its EVPN-VXLAN VNI |
| `OSPF_EXPORT` | Name of the OSPF export policy for the VRF |

### VNI/VLAN (reached via `vrf.cf.VNI`)

| Field | Purpose |
|---|---|
| `EXPORT_POLICY` | EVPN export policy name for `protocols evpn ip-prefix-routes export` |

### Loopback0 (VTEP)

| Field | Purpose |
|---|---|
| `VTEP` | Marks loopback0 as the VXLAN tunnel endpoint — gates whether access/Q-in-Q ports bind into the L2 VXLAN routing-instance |

### Static route

| Field | Purpose |
|---|---|
| `BFD` | Enables BFD for the static route |

### IP address

| Field | Purpose |
|---|---|
| `PRIMARY` | Marks which IP on the interface is primary vs. secondary/VRRP |
| `VRRP_GROUP` | VRRP group ID for the virtual-gateway IP (defaults to 1 if unset) |

### BGP session (netbox-bgp)

| Field | Purpose |
|---|---|
| `PREFIX_LIMIT` | Per-neighbor max-prefix override (with teardown) |
| `AUTH_KEY` | Per-neighbor BGP auth key |
| `LLGR_OFF` | Disables long-lived graceful-restart for this neighbor |

### BGP peer group (netbox-bgp)

| Field | Purpose |
|---|---|
| `AUTH_KEY` | Peer-group-level BGP auth key |
| `BFD` / `BFD_INTERVAL` | Enables BFD / sets minimum-interval (defaults to 300) |
| `PREFIX_LIMIT` | Peer-group-level max-prefix override (with teardown) |
| `FILTER_PRIVATE_ASN` | Enables `remove-private all` on outbound AS-path |
| `BGP_NEXTHOP` | Sets `next-hop-{self\|third-party\|...}` behavior (EOS only) |

No `.cf` access exists directly under `leaf/`, `ds/`, or `mgmt/` — those roles render through the shared `common/` (and `router/`) templates listed above.

## Tags

| Tag | Checked on | Effect |
|---|---|---|
| `maintenance` | Device | Forces `POL_REJECT` (reject-all) BGP export on every peer-group/session and the VRF's EVPN export — pulls the device out of production traffic without dropping BGP sessions. **Junos roles only**; not implemented for `spine/eos` or `router/eos`. |
| `maintenance` | Interface | *Separate mechanism, same tag name*: appends `" :: MAINT"` to the interface description and swaps its VLAN(s) to the site's maintenance VLAN (looked up via `ipam.VLAN.objects.filter(site=device.site, tags__name='maintenance')`, falling back to `"VLAN900"`). |
| `fabric` | Device | Gates whether a VRF is treated as fabric/EVPN-attached in `common/junos/routing-instance.j2` — controls whether EVPN `ip-prefix-routes` gets rendered. **Naming collision**: the unrelated interface custom field `FABRIC` above produces a same-named `is_fabric` local variable elsewhere in the templates; the two are independent mechanisms on different object types. |
| `IGMP-SNOOPING` | VLAN | Emits `set protocols igmp-snooping vlan <name>` |
| `IGMP-SNOOPING-PROXY` | VLAN | Same as above, plus `... proxy` |
| `ALWAYS_ADD` | netbox-bgp `RoutingPolicy` / `PrefixList` | Forces the policy/prefix-list to render even if no BGP session or peer-group on the device currently imports/exports it |

`mgmt/main.j2` computes a `maintenance_vlan` lookup but the `mgmt` role never checks `is_maintenance` — the variable is currently unused there.

## Config context

NetBox spreads `device.get_config_context()` keys directly into the top-level template namespace — so these are plain variables, not nested under a `config_context` key. See `scaffold/example_config_context.json` for a worked example covering every key below with placeholder values — paste its contents into a NetBox Config Context's "Data" field as a starting point, then replace the placeholders (ASN, IPs, users, keys) with real values.

| Key | Shape | Purpose |
|---|---|---|
| `users` | `.junos[]` (`root_auth`), `.exampleorg[]` (`_name`, `pubkey`/`pubkeytype`, `passwd`, `uid`, `arista_pw`, `systems[]` → `{_name, class}`) | Provisions local operator accounts (SSH key, password, login class) per vendor |
| `utility` | `.timezone` (str), `.ntp[]`, `.dns[]`, `.syslog[]` (`{_name, port}`) | Timezone, NTP/DNS servers, syslog hosts |
| `ddos_protection` | `.protocols[]` → `{name, aggregate: {bandwidth, burst}}` | Per-protocol DDoS storm-control policer thresholds |
| `bgp` | `.asn`, `.clusterid`, `.key` | Only `.asn` is currently used (AS number); `.clusterid`/`.key` exist in real data but aren't referenced by any template |
| `ospf` | `.area`, `.key` | Only `.area` is used, for underlay OSPF interface config |
| `snmp` | `.contact`, `.auth_key`, `.community[]` → `{name, clients[]: {address, vrf?}}` | SNMP contact string and community/client ACLs |
| `switch_options` | `.target`, `.t5` (route-target strings) | EVPN/VXLAN `vrf-target` statements |
| `sflow` | `.collector`, `.port`, `.interfaces[]` (optional) | sFlow agent/collector config; interfaces to enable are usually driven separately by interface `SFLOW` custom field |
| `communities` | `[{name, community}]` | BGP community-list definitions (`policy-options community ...`) |
| `hash_key` / `enhanced_hash_key` | `.family.inet[]`, `.family.inet6[]` | Forwarding hash-key modes, gated by device-type substring match (`ACX7100` / `QFX`) |
| `manual_config` / `group_config` | list of raw config-line strings | Escape hatch for one-off device- or group-scoped lines not worth a dedicated template; included near the bottom of every role's `main.j2`, rendered verbatim |

Secret-shaped fields (`users[].root_auth`/`arista_pw`, `bgp.key`, `ospf.key`, `snmp.auth_key`) are redacted in the committed test snapshots — see `tests/fetch_netbox_snapshot.py`'s `REDACT_KEYS`. Real values only ever exist in NetBox itself.

## BGP/interface prefetching

Each role's `main.j2` (or `bgp/main.j2` sub-entry-point) pre-fetches `bgp_sessions`, `bgp_peer_groups`, and `device_interfaces` once, with `select_related`/`prefetch_related` covering what the included partials read. Partials must consume these shared variables rather than querying `netbox_bgp`/`device.interfaces` directly — see `CLAUDE.md` for why (Jinja2 `{% set %}` doesn't propagate out of `{% include %}`) and where to extend the prefetch when a partial needs a new relation.
