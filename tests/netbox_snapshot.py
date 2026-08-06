"""Loads a tests/snapshots/<device>.json file (captured by
fetch_netbox_snapshot.py from real NetBox data) into the same Fake* mock
graph used by tests/fixtures.py, plus the full render_config() context dict.

NetBox's actual render_config() context is `{"device": device, **device.get_config_context()}`
- config-context keys are spread at the top level, not nested - so
`load_context()` does the same. Config-context values are left as the raw
dicts/lists from JSON: Jinja2's attribute access on a dict falls back to item
access automatically (`x.y` tries `getattr(x, 'y')` then `x['y']`), so plain
dicts already behave the way these templates expect without extra wrapping.
"""
import json
import sys
import types
from pathlib import Path

from netbox_mocks import (
    FakeBGPSession,
    FakeCF,
    FakeDevice,
    FakeEsi,
    FakeInterface,
    FakeIPAddress,
    FakePeerGroup,
    FakePolicy,
    FakeQuerySet,
    FakeTags,
    FakeVlan,
    FakeVRF,
    fake_endpoint,
    fake_ipam,
    fake_link_peer,
    fake_netbox_bgp,
    fake_netbox_custom_objects,
)

SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"


def _resolve_vni(vni):
    # fetch_netbox_snapshot.py's resolve_vni() already flattened VRF.cf.VNI
    # (an "object" custom field pointing at a vpn.L2VPN) to
    # {"identifier": int, "export_policy": name-or-None}.
    if not vni:
        return None
    export_policy = FakePolicy(vni["export_policy"]) if vni["export_policy"] else None
    return types.SimpleNamespace(
        identifier=vni["identifier"], cf=FakeCF(EXPORT_POLICY=export_policy)
    )


def _load_vrfs(data):
    vrfs = {}
    for name, v in data["vrfs"].items():
        cf = dict(v["custom_fields"])
        cf["VNI"] = _resolve_vni(cf.get("VNI"))
        if cf.get("OSPF_EXPORT"):
            cf["OSPF_EXPORT"] = FakePolicy(cf["OSPF_EXPORT"])
        vrfs[name] = FakeVRF(
            name=v["name"],
            rd=v["rd"],
            cf=cf,
            import_targets=[types.SimpleNamespace(name=t) for t in v["import_targets"]],
            export_targets=[types.SimpleNamespace(name=t) for t in v["export_targets"]],
        )
    return vrfs


def _vlan_ref(ref, vlans):
    if not ref:
        return None
    full = vlans.get(ref["name"])
    vlan = types.SimpleNamespace(
        id=ref["id"],
        name=ref["name"],
        vid=ref["vid"],
        description=(full or {}).get("description", ""),
        tags=FakeTags((full or {}).get("tags", [])),
    )
    identifier = (full or {}).get("l2vpn_identifier")
    vlan.l2vpn_termination = (
        types.SimpleNamespace(l2vpn=types.SimpleNamespace(identifier=identifier))
        if identifier
        else None
    )
    return vlan


def _build_interfaces(data, vrfs):
    vlans = data["vlans"]
    by_name = {}
    for i in data["interfaces"]:
        iface = FakeInterface(
            name=i["name"],
            enabled=i["enabled"],
            mtu=i["mtu"],
            type=i["type"],
            tags=i["tags"],
            mode=i["mode"],
            untagged_vlan=_vlan_ref(i["untagged_vlan"], vlans),
            tagged_vlans=[_vlan_ref(v, vlans) for v in i["tagged_vlans"]],
            qinq_svlan=_vlan_ref(i.get("qinq_svlan"), vlans),
            vrf=vrfs.get(i["vrf"]) if i["vrf"] else None,
            cf=i["custom_fields"],
            connected_endpoints=(
                [fake_endpoint(i["connected_endpoint"]["name"], i["connected_endpoint"]["device_name"])]
                if i["connected_endpoint"]
                else []
            ),
            link_peers=[fake_link_peer(i["cable_label"])] if i["cable_label"] else [],
            description=i["description"],
            mac_address=i["mac_address"],
            id=i["id"],
        )
        iface.ip_addresses = FakeQuerySet(
            FakeIPAddress(
                ip["address"],
                family=ip["family"],
                status=ip["status"],
                tags=ip["tags"],
                assigned_object=iface,
                cf=ip.get("custom_fields", {}),
            )
            for ip in i["ip_addresses"]
        )
        by_name[i["name"]] = (iface, i["lag"], i["parent"])

    # Second pass: resolve .lag / .parent references now that every
    # interface exists (mirrors real NetBox interface ordering, where a LAG
    # member interface sorts before its ae/Port-Channel bundle).
    for iface, lag_name, parent_name in by_name.values():
        if lag_name:
            iface.lag = by_name[lag_name][0]
        if parent_name:
            iface.parent = by_name[parent_name][0]

    return [iface for iface, _, _ in by_name.values()]


def _find_primary_ip(data, interfaces):
    addr = data["device"]["primary_ip"]
    if not addr:
        return None
    for iface in interfaces:
        for ip in iface.ip_addresses:
            if str(ip.address) == addr:
                return types.SimpleNamespace(address=ip.address, assigned_object=iface)
    print(f"warning: primary_ip {addr} not found on any interface", file=sys.stderr)
    return types.SimpleNamespace(
        address=types.SimpleNamespace(ip=addr.split("/")[0]),
        assigned_object=types.SimpleNamespace(vrf=None),
    )


def _build_bgp(data, device, vrfs):
    peer_groups = {
        pg["name"]: FakePeerGroup(
            id=pg["id"],
            name=pg["name"],
            cf=pg["custom_fields"],
            export_policies=[FakePolicy(n) for n in pg["export_policies"]],
            import_policies=[FakePolicy(n) for n in pg["import_policies"]],
        )
        for pg in data["bgp_peer_groups"]
    }
    sessions = []
    for s in data["bgp_sessions"]:
        local_vrf = None  # local_address VRF isn't captured separately; sessions
        # here are keyed off the device's routed/global address in every
        # snapshot fetched so far. Extend fetch_netbox_snapshot.py's
        # serialize_bgp() if a VRF-scoped session needs testing.
        sessions.append(
            FakeBGPSession(
                device=device,
                local_address=types.SimpleNamespace(
                    address=types.SimpleNamespace(ip=s["local_address"].split("/")[0]),
                    vrf=local_vrf,
                    family=s["local_address_family"],
                ),
                remote_address=types.SimpleNamespace(
                    address=types.SimpleNamespace(ip=s["remote_address"].split("/")[0])
                ),
                local_as=s["local_as"],
                remote_as=s["remote_as"],
                peer_group=peer_groups[s["peer_group"]],
                description=s["description"],
                cf=s["custom_fields"],
                status=s["status"],
                tags=s["tags"],
                export_policies=[FakePolicy(n) for n in s["export_policies"]],
                import_policies=[FakePolicy(n) for n in s["import_policies"]],
            )
        )
    return fake_netbox_bgp(sessions=sessions, peer_groups=list(peer_groups.values()))


def _build_esi_objects(data, interfaces_by_name):
    return [
        FakeEsi(
            esi_id=esi["esi_id"],
            interfaces=[interfaces_by_name[name] for name in esi["interfaces"] if name in interfaces_by_name],
        )
        for esi in data.get("esi_objects", [])
    ]


def _build_static_routes(data, vrfs):
    routes = []
    for r in data["static_routes"]:
        routes.append(
            types.SimpleNamespace(
                prefix=r["prefix"],
                next_hop=r["next_hop"],
                vrf=vrfs.get(r["vrf"]) if r["vrf"] else None,
                cf=FakeCF(**r["custom_fields"]),
            )
        )
    return routes


def load_context(device_name):
    """Loads tests/snapshots/<device_name>.json and returns a render_config()-shaped context."""
    path = SNAPSHOT_DIR / f"{device_name}.json"
    data = json.loads(path.read_text())

    vrfs = _load_vrfs(data)
    interfaces = _build_interfaces(data, vrfs)

    dd = data["device"]
    device = FakeDevice(
        name=dd["name"],
        role_name=dd["role"],
        interfaces=interfaces,
        tags=dd["tags"],
        cf=dd["custom_fields"],
        region_slug=dd["region_slug"],
        site_slug=dd["site_slug"],
        location_slug=dd["location_slug"],
        rack_name=dd["rack_name"],
        static_routes=_build_static_routes(data, vrfs),
        device_type_model=dd["device_type_model"],
    )
    device.primary_ip = _find_primary_ip(data, interfaces)

    interfaces_by_name = {iface.name: iface for iface in interfaces}

    context = dict(data["config_context"])
    context["device"] = device
    context["netbox_bgp"] = _build_bgp(data, device, vrfs)
    context["netbox_custom_objects"] = fake_netbox_custom_objects(
        esi_objects=_build_esi_objects(data, interfaces_by_name)
    )
    # site-scoped VLAN(s) tagged "maintenance" - replaces the old hardcoded
    # "VLAN900" literal. Absent from older snapshots (key added after that
    # migration), so this defaults to an empty list, same as a site with no
    # maintenance VLAN configured yet.
    context["ipam"] = fake_ipam(
        vlans=[
            FakeVlan(
                v["name"],
                vid=v.get("vid"),
                site=device.site,
                tags=["maintenance"],
                description=v.get("description", ""),
            )
            for v in data.get("maintenance_vlans", [])
        ]
        # q-in-q customer VLANs - see serialize_qinq_customer_vlans() in
        # fetch_netbox_snapshot.py. Absent from snapshots taken before this
        # was added, so this defaults to an empty list.
        + [
            FakeVlan(v["name"], vid=v.get("vid"), qinq_svlan=v["svlan_id"])
            for v in data.get("qinq_customer_vlans", [])
        ]
    )
    return context


def available_snapshots():
    return sorted(p.stem for p in SNAPSHOT_DIR.glob("*.json"))