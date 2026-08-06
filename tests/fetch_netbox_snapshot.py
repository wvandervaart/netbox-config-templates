#!/usr/bin/env python3
"""Fetches a real device's data from NetBox (+ the netbox-bgp and routing
plugins) and writes it to tests/snapshots/<device>.json for use by
tests/netbox_snapshot.py.

This is a one-time/occasional data-capture script, NOT something the test
suite runs automatically - tests load the committed JSON snapshots so they
stay fast, offline, and reproducible without needing live NetBox access or a
token.

Usage:
    export NETBOX_URL=https://netbox.example.net
    export NETBOX_TOKEN=...          # never pass this as a CLI arg or hardcode it
    python3 tests/fetch_netbox_snapshot.py <device-name-or-id> [<device-name-or-id> ...]

Secret-like and personally-identifying fields (encrypted passwords, BGP/OSPF
auth keys, SNMPv3 keys, SSH public keys, contact emails, and NetBox API
`url` fields embedded in object-reference custom field values) are redacted
before anything is written to disk - see REDACT_KEYS below. This preserves
field *presence* (so `is defined` / truthiness checks in templates still
exercise the same branches) without persisting recoverable production
credentials, real employee SSH keys, or internal hostnames into git history.

The script also prints a warning (not a hard failure) if the device's own AS
number (config_context.bgp.asn or a session's local_as) falls outside the
private ASN ranges - a real, WHOIS-attributable ASN slipping into a snapshot
is exactly the kind of thing this redaction can't catch structurally.
"""
import json
import os
import sys
from pathlib import Path

import pynetbox

SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"

REDACT_KEYS = {
    "passwd",
    "arista_pw",
    "root_auth",
    "key",
    "auth_key",
    "priv_key",
    "AUTH_KEY",
    "contact",
    "pubkey",
    "url",
}
REDACTED = "REDACTED-see-fetch_netbox_snapshot.py"

# NetBox's own AS number (the org's identity, not a peer's) - anything
# outside these ranges is a real, WHOIS-attributable ASN and shouldn't ride
# into a committed snapshot. Peer/transit remote_as values are deliberately
# NOT checked here: real transit ASNs (Arelion, Cogent, etc.) are legitimate,
# expected test data for router/junos coverage.
PRIVATE_ASN_RANGES = [(64512, 65534), (4200000000, 4294967294)]


def redact(value, key=None):
    if isinstance(value, dict):
        out = {k: redact(v, key=k) for k, v in value.items()}
        return out
    if isinstance(value, list):
        return [redact(v, key=key) for v in value]
    # 'pubkey'/'url' are redacted unconditionally (see REDACT_KEYS) - pubkey
    # because it's real, personally-attributable SSH key material regardless
    # of whether pubkeytype says "ssh-ed25519"/"ssh-rsa" or
    # "encrypted-password"; url because NetBox embeds a live API URL (real
    # internal hostname) on every nested object-reference custom field value.
    if key in REDACT_KEYS and value not in (None, "", False):
        return REDACTED
    return value


def warn_if_public_asn(label, asn):
    if asn is None:
        return
    if not any(lo <= asn <= hi for lo, hi in PRIVATE_ASN_RANGES):
        print(
            f"WARNING: {label} = {asn} is outside the private ASN ranges "
            f"(64512-65534, 4200000000-4294967294) - this looks like a real, "
            f"WHOIS-attributable ASN. Double-check before committing this "
            f"snapshot.",
            file=sys.stderr,
        )


def tag_names(tags):
    return [t.name for t in tags] if tags else []


def vlan_ref(vlan):
    if not vlan:
        return None
    return {"name": vlan.name, "vid": vlan.vid, "id": vlan.id}


def connect():
    url = os.environ.get("NETBOX_URL")
    token = os.environ.get("NETBOX_TOKEN")
    if not url or not token:
        sys.exit("Set NETBOX_URL and NETBOX_TOKEN environment variables first.")
    return pynetbox.api(url, token=token)


def serialize_device(nb, device):
    primary_ip = None
    primary_ip_assigned_to = None
    if device.primary_ip:
        primary_ip = str(device.primary_ip.address)

    region = None
    if device.site and device.site.region:
        region = device.site.region.slug

    return {
        "id": device.id,
        "name": device.name,
        "role": device.role.name if device.role else None,
        "platform": device.platform.slug if device.platform else None,
        "tags": tag_names(device.tags),
        "custom_fields": redact(device.custom_fields),
        "site_slug": device.site.slug if device.site else None,
        "region_slug": region,
        "location_slug": device.location.slug if device.location else None,
        "rack_name": device.rack.name if device.rack else None,
        "device_type_model": device.device_type.model if device.device_type else None,
        "primary_ip": primary_ip,
    }


def serialize_interfaces(nb, device_id):
    ifaces = list(nb.dcim.interfaces.filter(device_id=device_id))
    ips = list(nb.ipam.ip_addresses.filter(device_id=device_id))

    vrf_ids = set()
    vlan_ids = set()

    out = []
    for i in ifaces:
        if i.vrf:
            vrf_ids.add(i.vrf.id)
        if i.untagged_vlan:
            vlan_ids.add(i.untagged_vlan.id)
        for v in i.tagged_vlans or []:
            vlan_ids.add(v.id)
        if i.qinq_svlan:
            vlan_ids.add(i.qinq_svlan.id)

        ep = None
        if i.connected_endpoints:
            first = i.connected_endpoints[0]
            ep = {
                "name": first.name,
                "device_name": first.device.name if getattr(first, "device", None) else None,
            }
        cable_label = None
        if i.link_peers and i.link_peers[0].cable is not None:
            cable_label = i.link_peers[0].cable.label or None

        my_ips = []
        for ip in ips:
            if ip.assigned_object_id == i.id and ip.assigned_object_type == "dcim.interface":
                my_ips.append(
                    {
                        "address": str(ip.address),
                        "family": ip.family.value,
                        "status": ip.status.value,
                        "tags": tag_names(ip.tags),
                        "custom_fields": redact(ip.custom_fields),
                    }
                )
                if ip.vrf:
                    vrf_ids.add(ip.vrf.id)

        out.append(
            {
                "id": i.id,
                "name": i.name,
                "enabled": i.enabled,
                "mtu": i.mtu,
                "type": i.type.value if i.type else None,
                "tags": tag_names(i.tags),
                "lag": i.lag.name if i.lag else None,
                "mode": i.mode.value if i.mode else None,
                "untagged_vlan": vlan_ref(i.untagged_vlan),
                "tagged_vlans": [vlan_ref(v) for v in (i.tagged_vlans or [])],
                "qinq_svlan": vlan_ref(i.qinq_svlan),
                "vrf": i.vrf.name if i.vrf else None,
                "custom_fields": redact(i.custom_fields),
                "connected_endpoint": ep,
                "cable_label": cable_label,
                "description": i.description,
                "parent": i.parent.name if i.parent else None,
                "mac_address": str(i.mac_address) if i.mac_address else None,
                "ip_addresses": my_ips,
            }
        )
    return out, vrf_ids, vlan_ids


def resolve_vrf_cf(nb, cf):
    """Resolves VRF custom fields that are NetBox "object" references so the
    loader doesn't need live NetBox access:

    - VNI points at a vpn.L2VPN record; templates read `vni.identifier` and
      `vni.cf.EXPORT_POLICY` (itself an object ref, to a routing-policy).
    - OSPF_EXPORT points directly at a routing-policy.
    """
    cf = dict(cf)

    vni_ref = cf.get("VNI")
    if vni_ref:
        l2vpn = nb.vpn.l2vpns.get(vni_ref["id"])
        export_policy = None
        if l2vpn and l2vpn.custom_fields.get("EXPORT_POLICY"):
            export_policy = l2vpn.custom_fields["EXPORT_POLICY"]["name"]
        cf["VNI"] = {
            "identifier": l2vpn.identifier if l2vpn else vni_ref.get("identifier"),
            "export_policy": export_policy,
        }

    ospf_export_ref = cf.get("OSPF_EXPORT")
    if ospf_export_ref:
        cf["OSPF_EXPORT"] = ospf_export_ref["name"]

    return cf


def serialize_vrfs(nb, vrf_ids):
    out = {}
    for vid in vrf_ids:
        v = nb.ipam.vrfs.get(vid)
        if not v:
            continue
        out[v.name] = {
            "name": v.name,
            "rd": v.rd,
            "custom_fields": redact(resolve_vrf_cf(nb, v.custom_fields)),
            "import_targets": [t.name for t in (v.import_targets or [])],
            "export_targets": [t.name for t in (v.export_targets or [])],
        }
    return out


def serialize_vlans(nb, vlan_ids):
    out = {}
    for vid in vlan_ids:
        v = nb.ipam.vlans.get(vid)
        if not v:
            continue
        identifier = None
        term = getattr(v, "l2vpn_termination", None)
        if term is not None:
            full_term = nb.vpn.l2vpn_terminations.get(term.id)
            if full_term and full_term.l2vpn:
                identifier = full_term.l2vpn.identifier
        out[v.name] = {
            "name": v.name,
            "vid": v.vid,
            "description": v.description or "",
            "l2vpn_identifier": identifier,
            "tags": tag_names(v.tags),
        }
    return out


def serialize_maintenance_vlans(nb, site_id):
    # Replaces the old hardcoded "VLAN900" literal: a site-scoped VLAN
    # tagged "maintenance" that access/trunk ports fall back to while a
    # device/interface is in maintenance mode.
    out = []
    for v in nb.ipam.vlans.filter(site_id=site_id, tag="maintenance"):
        out.append(
            {
                "name": v.name,
                "vid": v.vid,
                "description": v.description or "",
            }
        )
    return out


def serialize_qinq_customer_vlans(nb, interfaces):
    # Customer VLANs for a q-in-q interface aren't the interface's own
    # tagged_vlans (q-in-q mode leaves that empty) - they're separate VLAN
    # objects elsewhere in NetBox whose own qinq_svlan field points back at
    # this interface's S-VLAN (VLAN.qinq_role Service vs Customer).
    svlan_ids = {i["qinq_svlan"]["id"] for i in interfaces if i.get("qinq_svlan")}
    out = []
    for sv_id in svlan_ids:
        for v in nb.ipam.vlans.filter(qinq_svlan_id=sv_id):
            out.append({"svlan_id": sv_id, "name": v.name, "vid": v.vid})
    return out


def serialize_static_routes(nb, device_name):
    # The routing plugin's staticroute endpoint doesn't support server-side
    # filtering by device in this NetBox version, so filter client-side.
    out = []
    for r in nb.plugins.routing.staticroute.all():
        if not any(d.name == device_name for d in (r.devices or [])):
            continue
        out.append(
            {
                "prefix": r.prefix,
                "next_hop": r.next_hop,
                "vrf": r.vrf.name if r.vrf else None,
                "custom_fields": redact(r.custom_fields),
            }
        )
    return out


def serialize_esi_objects(nb, device_id, interface_names):
    # netbox_custom_objects generates per-type REST endpoints dynamically;
    # this assumes the plugin's URL namespace is "custom_objects" and the
    # ESI custom object type's slug is "esi" (as configured per the plan in
    # netbox-config-templates' CLAUDE.md-adjacent planning doc) - verify
    # against /api/plugins/custom-objects/ on the live instance and adjust
    # if the actual namespace/slug differs.
    out = []
    for esi in nb.plugins.custom_objects.esi.all():
        linked = [
            iface["name"] if isinstance(iface, dict) else str(iface)
            for iface in (esi.interfaces or [])
        ]
        names_on_device = [n for n in linked if n in interface_names]
        if not names_on_device:
            continue
        out.append({"esi_id": esi.esi_id, "interfaces": sorted(names_on_device)})
    return out


def serialize_bgp(nb, device_id):
    sessions = list(nb.plugins.bgp.bgpsession.filter(device_id=device_id))
    pg_ids = set()
    out_sessions = []
    for s in sessions:
        pg_ids.add(s.peer_group.id)
        out_sessions.append(
            {
                "name": s.name,
                "local_address": str(s.local_address.address),
                "local_address_family": s.local_address.family.value,
                "remote_address": str(s.remote_address.address),
                "local_as": s.local_as.asn if s.local_as else None,
                "remote_as": s.remote_as.asn if s.remote_as else None,
                "peer_group": s.peer_group.name,
                "description": s.description or "",
                "status": s.status.value,
                "tags": tag_names(s.tags),
                "custom_fields": redact(s.custom_fields),
                "export_policies": [p.name for p in (s.export_policies or [])],
                "import_policies": [p.name for p in (s.import_policies or [])],
            }
        )

    out_pgs = []
    for pgid in pg_ids:
        pg = nb.plugins.bgp.bgppeergroup.get(pgid)
        out_pgs.append(
            {
                "id": pg.id,
                "name": pg.name,
                "custom_fields": redact(pg.custom_fields),
                "export_policies": [p.name for p in (pg.export_policies or [])],
                "import_policies": [p.name for p in (pg.import_policies or [])],
            }
        )
    return out_sessions, out_pgs


def fetch_snapshot(nb, device_ref):
    try:
        device_id = int(device_ref)
        device = nb.dcim.devices.get(device_id)
    except ValueError:
        device = nb.dcim.devices.get(name=device_ref)
    if device is None:
        sys.exit(f"device not found: {device_ref}")

    interfaces, vrf_ids, vlan_ids = serialize_interfaces(nb, device.id)
    sessions, peer_groups = serialize_bgp(nb, device.id)
    interface_names = {i["name"] for i in interfaces}

    snapshot = {
        "device": serialize_device(nb, device),
        "interfaces": interfaces,
        "vrfs": serialize_vrfs(nb, vrf_ids),
        "vlans": serialize_vlans(nb, vlan_ids),
        "static_routes": serialize_static_routes(nb, device.name),
        "bgp_sessions": sessions,
        "bgp_peer_groups": peer_groups,
        "esi_objects": serialize_esi_objects(nb, device.id, interface_names),
        "maintenance_vlans": serialize_maintenance_vlans(nb, device.site.id),
        "qinq_customer_vlans": serialize_qinq_customer_vlans(nb, interfaces),
        "config_context": redact(dict(device.config_context or {})),
    }

    warn_if_public_asn("config_context.bgp.asn", snapshot["config_context"].get("bgp", {}).get("asn"))
    for s in sessions:
        warn_if_public_asn(f"bgp_sessions[{s['name']!r}].local_as", s.get("local_as"))

    return device.name, snapshot


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    nb = connect()
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    for device_ref in sys.argv[1:]:
        name, snapshot = fetch_snapshot(nb, device_ref)
        out_path = SNAPSHOT_DIR / f"{name}.json"
        out_path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
        print(f"wrote {out_path}")


if __name__ == "__main__":
    main()