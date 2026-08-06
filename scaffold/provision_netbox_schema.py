#!/usr/bin/env python3
"""Provisions the NetBox custom fields and tags these Jinja2 templates read.

This is a one-time/occasional setup script for a fresh (or drifted) NetBox
instance - it is NOT run by the test suite, which loads committed JSON
snapshots instead (see tests/fetch_netbox_snapshot.py / tests/snapshots/).

The field/tag list below is derived from NETBOX.md, which catalogs every
`.cf.FIELD` and tag actually read by the templates in this repo - see that
file for what each field/tag does and why. Fields that exist in real NetBox
data but aren't read by any template today (OLDNAME, MGMT_GW, snmp.v3.*,
static-route BFD_INTERVAL, etc.) are deliberately left out; add them by hand
if you want them for other reasons.

Usage:
    export NETBOX_URL=https://netbox.example.net
    export NETBOX_TOKEN=...          # never pass this as a CLI arg or hardcode it
    python3 scaffold/provision_netbox_schema.py [--dry-run]

Idempotent and additive: a tag/custom field that already exists is left
untouched and merely logged as "already exists" - this script never deletes
or overwrites live schema. Re-running it after adding a new field/tag to the
lists below only creates what's missing.

Needs pynetbox (see tests/requirements.txt: `pip install -r tests/requirements.txt`).
"""
import argparse
import os
import sys

import pynetbox
from pynetbox.core.query import RequestError

# -- Tags --------------------------------------------------------------
# NetBox tags aren't restricted to specific content-types by this script
# (kept assignable anywhere, matching how tags already behave in the live
# instance) - the "applies to" note is documentation only, see NETBOX.md.
TAGS = [
    {
        "name": "maintenance",
        "description": "Pulls a device/interface/VLAN out of production traffic "
        "without dropping BGP sessions (device, interface, ipam.vlan).",
    },
    {
        "name": "fabric",
        "description": "Marks a device as fabric/EVPN-attached, gating VRF "
        "routing-instance rendering (device).",
    },
    {
        "name": "IGMP-SNOOPING",
        "description": "Enables IGMP snooping on a VLAN (ipam.vlan).",
    },
    {
        "name": "IGMP-SNOOPING-PROXY",
        "description": "Enables IGMP snooping proxy on a VLAN (ipam.vlan).",
    },
    {
        "name": "ALWAYS_ADD",
        "description": "Forces a routing-policy/prefix-list to always render, "
        "even if unreferenced by any BGP session/peer-group/VRF today "
        "(netbox_bgp.routingpolicy, netbox_bgp.prefixlist).",
    },
]

# -- Custom fields -------------------------------------------------------
# object_types: list of NetBox content-type labels ("app_label.model") the
# field is attached to.
# object_type: for type="object"/"multiobject" fields, the content-type the
# field's value points AT (resolved dynamically for the plugin-sourced ones,
# see resolve_content_type()).
CUSTOM_FIELDS = [
    # -- Device --
    {"name": "GNMI_MONITORED", "type": "boolean", "object_types": ["dcim.device"],
     "group_name": "Telemetry", "description": "Enables gRPC/gNMI telemetry config."},
    {"name": "VSTP_ENABLED", "type": "boolean", "object_types": ["dcim.device"],
     "group_name": "VSTP", "description": "Enables VSTP (per-VLAN spanning tree) globally."},
    {"name": "VSTP_ALL_INT_ENABLED", "type": "boolean", "object_types": ["dcim.device"],
     "group_name": "VSTP", "description": "Enables VSTP on all interfaces by default."},
    {"name": "DEFAULT_AS_PREPEND", "type": "integer", "object_types": ["dcim.device"],
     "group_name": "BGP", "description": "Default AS-path prepend count in BGP export policy."},
    {"name": "VSTP_BRIDGEID", "type": "text", "object_types": ["dcim.device"],
     "group_name": "VSTP", "description": "VSTP system-identifier."},
    {"name": "VSTP_BRIDGEPRIO", "type": "text", "object_types": ["dcim.device"],
     "group_name": "VSTP", "description": "VSTP bridge-priority."},

    # -- Interface: booleans --
    {"name": "FABRIC", "type": "boolean", "object_types": ["dcim.interface"],
     "group_name": "Underlay", "description": "Marks the interface as underlay/fabric-facing."},
    {"name": "IXPORT", "type": "boolean", "object_types": ["dcim.interface"],
     "group_name": "Filters", "description": "Marks an IX/peering port - affects ARP policer and filter selection."},
    {"name": "LLDP_OFF", "type": "boolean", "object_types": ["dcim.interface"],
     "group_name": "Protocols", "description": "Disables LLDP on the interface."},
    {"name": "RSTP_OFF", "type": "boolean", "object_types": ["dcim.interface"],
     "group_name": "Protocols", "description": "Disables RSTP on the interface."},
    {"name": "VSTP_OFF", "type": "boolean", "object_types": ["dcim.interface"],
     "group_name": "VSTP", "description": "Disables VSTP on the interface (overrides device default)."},
    {"name": "SFLOW", "type": "boolean", "object_types": ["dcim.interface"],
     "group_name": "Telemetry", "description": "Enables sFlow monitoring on the interface."},
    {"name": "IGMPIFACEDISABLE", "type": "boolean", "object_types": ["dcim.interface"],
     "group_name": "Multicast", "description": "Disables IGMP on the interface."},
    {"name": "OSPF_PASSIVE", "type": "boolean", "object_types": ["dcim.interface"],
     "group_name": "OSPF", "description": "Marks the OSPF interface passive."},
    {"name": "OSPF_BFD", "type": "boolean", "object_types": ["dcim.interface"],
     "group_name": "OSPF", "description": "Enables BFD for OSPF on the interface."},

    # -- Interface: integers --
    {"name": "QFX_PORTGROUP", "type": "integer", "object_types": ["dcim.interface"],
     "group_name": "Hardware", "description": "Maps interface to a chassis FPC/PIC port-group for speed config."},
    {"name": "IGMPIFACEVERSION", "type": "integer", "object_types": ["dcim.interface"],
     "group_name": "Multicast", "description": "IGMP protocol version for the interface (2 or 3)."},
    {"name": "PIMIFACEHELLO", "type": "integer", "object_types": ["dcim.interface"],
     "group_name": "Multicast", "description": "PIM hello-interval for the interface."},
    {"name": "PIMIFACEPRIO", "type": "integer", "object_types": ["dcim.interface"],
     "group_name": "Multicast", "description": "PIM DR priority for the interface."},

    # -- Interface: text --
    {"name": "INPUT_FILTER", "type": "text", "object_types": ["dcim.interface"],
     "group_name": "Filters", "description": "Firewall filter name applied inbound "
     '(special value "re-protect" triggers the RE-protection filter).'},
    {"name": "OUTPUT_FILTER", "type": "text", "object_types": ["dcim.interface"],
     "group_name": "Filters", "description": "Firewall filter name applied outbound."},
    {"name": "INPUT_FILTER_V6", "type": "text", "object_types": ["dcim.interface"],
     "group_name": "Filters", "description": 'IPv6 inbound firewall filter (special value "re-protect_V6").'},
    {"name": "OSPF_AREA", "type": "text", "object_types": ["dcim.interface"],
     "group_name": "OSPF", "description": "OSPF area for the interface - also gates whether OSPF is enabled at all."},

    # -- Interface: select/multiselect --
    {"name": "FEC", "type": "multiselect", "object_types": ["dcim.interface"],
     "group_name": "Hardware", "description": "Forward-error-correction mode(s) to configure on the port.",
     "choices": ["none", "fec74", "fec91"]},
    {"name": "OSPF_VERSION", "type": "select", "object_types": ["dcim.interface"],
     "group_name": "OSPF", "description": 'Which OSPF version(s) to configure ("2", "3", or "23" for both).',
     "choices": ["2", "3", "23"]},
    {"name": "OSPF_NETWORK_TYPE", "type": "select", "object_types": ["dcim.interface"],
     "group_name": "OSPF", "description": "OSPF interface network type.",
     "choices": ["p2p", "p2mp", "nbma", "broadcast"]},
    {"name": "PIMIFACEMODE", "type": "select", "object_types": ["dcim.interface"],
     "group_name": "Multicast", "description": "PIM interface mode.",
     "choices": ["dense", "sparse", "sparse-dense"]},

    # -- IP address --
    {"name": "PRIMARY", "type": "boolean", "object_types": ["ipam.ipaddress"],
     "group_name": None, "description": "Marks which IP on the interface is primary vs. secondary/VRRP."},
    {"name": "VRRP_GROUP", "type": "integer", "object_types": ["ipam.ipaddress"],
     "group_name": None, "description": "VRRP group ID for the virtual-gateway IP (defaults to 1 if unset)."},

    # -- BGP peer group (netbox-bgp) --
    {"name": "AUTH_KEY", "type": "text", "object_types": ["netbox_bgp.bgppeergroup"],
     "group_name": "BGP", "description": "Peer-group-level BGP auth key."},
    {"name": "BFD", "type": "boolean", "object_types": ["netbox_bgp.bgppeergroup"],
     "group_name": "BGP", "description": "Enables BFD for the peer group."},
    {"name": "BFD_INTERVAL", "type": "integer", "object_types": ["netbox_bgp.bgppeergroup"],
     "group_name": "BGP", "description": "BFD minimum-interval for the peer group (defaults to 300)."},
    {"name": "PREFIX_LIMIT", "type": "integer", "object_types": ["netbox_bgp.bgppeergroup"],
     "group_name": "BGP", "description": "Peer-group-level max-prefix override (with teardown)."},
    {"name": "FILTER_PRIVATE_ASN", "type": "boolean", "object_types": ["netbox_bgp.bgppeergroup"],
     "group_name": "BGP", "description": "Enables `remove-private all` on outbound AS-path."},
    {"name": "BGP_NEXTHOP", "type": "text", "object_types": ["netbox_bgp.bgppeergroup"],
     "group_name": "BGP", "description": 'Sets next-hop-{value} behavior, e.g. "self" (EOS only).'},

    # -- BGP session (netbox-bgp) --
    {"name": "AUTH_KEY", "type": "text", "object_types": ["netbox_bgp.bgpsession"],
     "group_name": "BGP", "description": "Per-neighbor BGP auth key."},
    {"name": "PREFIX_LIMIT", "type": "integer", "object_types": ["netbox_bgp.bgpsession"],
     "group_name": "BGP", "description": "Per-neighbor max-prefix override (with teardown)."},
    {"name": "LLGR_OFF", "type": "boolean", "object_types": ["netbox_bgp.bgpsession"],
     "group_name": "BGP", "description": "Disables long-lived graceful-restart for this neighbor."},

    # -- Static route (routing plugin - content-type resolved at runtime) --
    {"name": "BFD", "type": "boolean", "object_types": ["__static_route__"],
     "group_name": None, "description": "Enables BFD for the static route."},

    # -- VRF --
    {"name": "VNI", "type": "object", "object_types": ["ipam.vrf"], "object_type": "vpn.l2vpn",
     "group_name": "EVPN", "description": "Object reference to a VLAN/VNI (vpn.L2VPN) object, "
     "linking the VRF to its EVPN-VXLAN VNI."},
    {"name": "OSPF_EXPORT", "type": "object", "object_types": ["ipam.vrf"], "object_type": "netbox_bgp.routingpolicy",
     "group_name": "OSPF", "description": "OSPF export policy for the VRF."},

    # -- VPN L2VPN (reached via vrf.cf.VNI) --
    {"name": "EXPORT_POLICY", "type": "object", "object_types": ["vpn.l2vpn"], "object_type": "netbox_bgp.routingpolicy",
     "group_name": "EVPN", "description": "EVPN export policy for `protocols evpn ip-prefix-routes export`."},
]

# Multiple fields share the name AUTH_KEY/PREFIX_LIMIT/BFD across different
# object_types above (e.g. AUTH_KEY on both bgppeergroup and bgpsession) -
# NetBox custom fields are keyed by name *and* content-type combination isn't
# how the API works: a CustomField is one object whose object_types list can
# span several content-types. Merge entries with the same name so we create
# ONE custom field per name, attached to the union of its content-types,
# instead of trying (and failing) to create two same-named CustomFields.


def merge_custom_field_specs(specs):
    merged = {}
    for spec in specs:
        key = spec["name"]
        if key in merged:
            existing = merged[key]
            existing["object_types"] = sorted(set(existing["object_types"]) | set(spec["object_types"]))
            assert existing["type"] == spec["type"], f"conflicting type for {key}"
        else:
            merged[key] = dict(spec)
    return list(merged.values())


# -- Content-type resolution ---------------------------------------------

def connect():
    url = os.environ.get("NETBOX_URL")
    token = os.environ.get("NETBOX_TOKEN")
    if not url or not token:
        sys.exit("Set NETBOX_URL and NETBOX_TOKEN environment variables first.")
    return pynetbox.api(url, token=token)


def resolve_content_type(nb, label, candidates=None):
    """Resolves a content-type label to the string NetBox's custom-field
    object_types API expects ("app_label.model"). `label` is used as-is if
    it already looks like "app_label.model"; `candidates` is a list of
    (app_label, model) pairs to try instead when the label is a placeholder
    like "__static_route__" whose real app_label depends on how the routing
    plugin is installed on this instance.
    """
    if candidates is None:
        return label

    all_cts = list(nb.extras.content_types.all())
    for app_label, model in candidates:
        for ct in all_cts:
            if ct.app_label == app_label and ct.model == model:
                return f"{app_label}.{model}"

    found = sorted(f"{ct.app_label}.{ct.model}" for ct in all_cts if ct.model == candidates[0][1])
    sys.exit(
        f"Could not resolve content-type for {label!r}: tried "
        f"{[f'{a}.{m}' for a, m in candidates]}, none exist on this NetBox "
        f"instance. Content-types with model={candidates[0][1]!r} found: "
        f"{found or 'none'}. Adjust the candidate list in resolve_content_type()."
    )


PLACEHOLDER_CANDIDATES = {
    "__static_route__": [("routing", "staticroute"), ("netbox_routing", "staticroute")],
}


def resolve_object_types(nb, object_types):
    resolved = []
    for label in object_types:
        if label in PLACEHOLDER_CANDIDATES:
            resolved.append(resolve_content_type(nb, label, PLACEHOLDER_CANDIDATES[label]))
        else:
            resolved.append(label)
    return resolved


# -- Tag / custom-field / choice-set creation -----------------------------

def slugify(name):
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")


def ensure_tag(nb, spec, dry_run):
    existing = nb.extras.tags.get(name=spec["name"])
    if existing:
        print(f"tag {spec['name']!r}: already exists, skipping")
        return
    if dry_run:
        print(f"tag {spec['name']!r}: would create")
        return
    nb.extras.tags.create(name=spec["name"], slug=slugify(spec["name"]), description=spec["description"])
    print(f"tag {spec['name']!r}: created")


def ensure_choice_set(nb, name, choices, dry_run):
    """Returns the choice-set id to reference from a select/multiselect
    CustomField, or None if this NetBox version doesn't have the separate
    CustomFieldChoiceSet endpoint (pre-3.4) - callers fall back to inline
    `choices` on the CustomField itself in that case.
    """
    try:
        existing = nb.extras.custom_field_choice_sets.get(name=name)
    except RequestError as exc:
        if exc.req.status_code == 404:
            return "no-choice-set-endpoint"
        raise
    if existing:
        return existing.id
    if dry_run:
        print(f"choice set {name!r}: would create with choices {choices}")
        return None
    created = nb.extras.custom_field_choice_sets.create(name=name, extra_choices=[[c, c] for c in choices])
    print(f"choice set {name!r}: created")
    return created.id


def ensure_custom_field(nb, spec, dry_run):
    name = spec["name"]
    existing = nb.extras.custom_fields.get(name=name)
    if existing:
        print(f"custom field {name!r}: already exists, skipping")
        return

    object_types = resolve_object_types(nb, spec["object_types"])
    payload = {
        "name": name,
        "type": spec["type"],
        "object_types": object_types,
        "label": name,
        "description": spec["description"],
        "required": False,
    }
    if spec.get("group_name"):
        payload["group_name"] = spec["group_name"]
    if spec["type"] == "object" or spec["type"] == "multiobject":
        payload["object_type"] = resolve_object_types(nb, [spec["object_type"]])[0]
    if spec["type"] in ("select", "multiselect"):
        choice_set_id = ensure_choice_set(nb, f"{name}_choices", spec["choices"], dry_run)
        if choice_set_id == "no-choice-set-endpoint":
            payload["choices"] = spec["choices"]
        elif choice_set_id is not None:
            payload["choice_set"] = choice_set_id
        elif dry_run:
            pass  # choice set doesn't exist yet in dry-run mode; nothing more to preview

    if dry_run:
        print(f"custom field {name!r} ({spec['type']} on {object_types}): would create")
        return

    nb.extras.custom_fields.create(**payload)
    print(f"custom field {name!r}: created")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print what would be created, make no changes.")
    args = parser.parse_args()

    nb = connect()

    for spec in TAGS:
        ensure_tag(nb, spec, args.dry_run)

    for spec in merge_custom_field_specs(CUSTOM_FIELDS):
        ensure_custom_field(nb, spec, args.dry_run)


if __name__ == "__main__":
    main()
