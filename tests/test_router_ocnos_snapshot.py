"""Tests for the NETCONF XML router/ocnos/main.j2 renders against
tests/snapshots/r1-ocnos-610-12-nl1.json.

That snapshot is SYNTHETIC: the real Junos r1-610-12-nl1 snapshot with its interfaces
renamed to OcNOS conventions (et-0/0/N -> ceN/cdN, aeN -> poN, irb.N -> vlan1.N,
lo0.0 -> loopback1, lo0.N -> loopback2+ (one per VRF), re0:mgmt-0 -> eth0) and OcNOS users added. It gives
real-world scale and data shape (VRF-scoped transit/IX/PNI sessions, v4+v6, LAG
sub-interfaces) until a real OcNOS router exists in NetBox to snapshot.
"""
import json
from collections import Counter

import pytest

from netbox_snapshot import SNAPSHOT_DIR, load_context
from ocnos_xml import (
    af_config,
    aspath_lists,
    bgp_instance,
    bgp_vrf,
    bridge,
    comments,
    config_children,
    dot1q,
    find,
    interface_names,
    interfaces,
    ipv4,
    ipv6,
    lag_member,
    network_instances,
    peer_groups,
    peers,
    prefix_lists,
    route_maps,
    settings,
    switchport,
    text,
    texts,
    vrf_summary,
)

TEMPLATE = "router/ocnos/main.j2"
DEVICE = "r1-ocnos-610-12-nl1"


@pytest.fixture(scope="module")
def xml():
    import jinja2

    from conftest import OCNOS_ENV_PARAMS, REPO_ROOT
    from ocnos_xml import parse

    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(REPO_ROOT)), **OCNOS_ENV_PARAMS)
    output = env.get_template(TEMPLATE).render(**load_context(DEVICE))
    return parse(output), output


@pytest.fixture(scope="module")
def root(xml):
    return xml[0]


@pytest.fixture(scope="module")
def intfs(root):
    return interfaces(root)


def test_renders_well_formed(root):
    assert len(root)


def test_every_interface_rendered_once(root):
    assert [n for n, c in Counter(interface_names(root)).items() if c > 1] == []


def test_mgmt_on_eth0_without_vrf(intfs):
    assert ipv4(intfs["eth0"]) == ["172.18.101.238/23"]
    assert "vrf-name" not in config_children(intfs["eth0"])


def test_no_junos_leftovers(root, xml):
    assert "mgmt_junos" not in network_instances(root, "vrf")
    assert not any(line.startswith(("set ", "delete ")) for line in xml[1].splitlines())


def test_lag_member_and_subinterface(intfs):
    assert lag_member(intfs["ce20"]) == ("3", "active")
    sub = intfs["po1.3528"]
    assert dot1q(sub) == "3528"
    assert text(sub, "if:config/if:vrf-name") == "internet"
    assert "198.18.0.42/31" in ipv4(sub)


def test_lag_mtu_on_members_not_bundle(intfs):
    assert text(intfs["ce28"], "if:config/if:mtu") == "9216"  # po1 member
    assert text(intfs["ce23"], "if:config/if:mtu") == "1536"  # po5 member
    for po in ("po1", "po2", "po3", "po5"):
        if po in intfs:
            assert text(intfs[po], "if:config/if:mtu") is None


def test_vlan_database(root):
    vids = texts(bridge(root), "vlan:vlans/vlan:vlan/vlan:vlan-id")
    # 692 has only an SVI, no member port - it still needs to exist in the bridge
    assert vids == ["690", "692", "801", "804", "1802"]


def test_server_trunks(root, intfs):
    for port in ("ce0", "ce1", "ce2", "ce3", "ce4", "ce5"):
        intf = intfs[port]
        assert "enable-switchport" in config_children(intf)
        assert port in texts(bridge(root), "br:bridge-ports/br:interface/br:name")
        assert switchport(intf) == {"mode": "trunk", "vlan": None, "native": None, "allowed": "690,801,804,1802"}


def test_svi_is_not_a_subinterface(intfs):
    svi = intfs["vlan1.690"]
    assert dot1q(svi) is None
    assert text(svi, "if:config/if:vrf-name") == "internet"
    assert ipv4(svi) == ["10.4.254.1/25"]
    assert "vlan1.1802" in intfs
    assert not any(name.startswith("irb") for name in intfs)


def test_vrf_router_id_and_route_targets(root):
    vrfs = network_instances(root, "vrf")
    assert vrf_summary(vrfs["internet"]) == ("10.0.254.250:2", "198.18.0.233", [("65000:2", "import export")])
    assert vrf_summary(vrfs["SGBC"]) == ("10.0.254.250:4", "172.18.255.17", [("65000:4", "import export")])


def test_vrf_loopbacks(intfs):
    lo2 = intfs["loopback2"]
    assert text(lo2, "if:config/if:vrf-name") == "internet"
    assert "198.18.0.233/32" in ipv4(lo2)
    assert "2001:db8:3101::3/128" in ipv6(lo2)
    lo3 = intfs["loopback3"]
    assert text(lo3, "if:config/if:vrf-name") == "SGBC"
    assert ipv4(lo3) == ["172.18.255.17/32"]


def test_ospf_networks_not_duplicated(root):
    proc = find(root, "ospf:ospfv2/ospf:processes/ospf:process")
    assert text(proc, "ospf:config/ospf:router-id") == "10.0.254.250"
    networks = texts(proc, "ospf:areas/ospf:area/ospf:networks/ospf:network/ospf:prefix")
    assert networks.count("10.0.254.250/32") == 1
    assert "10.0.2.40/31" in networks
    assert len(networks) == len(set(networks))


def test_global_bgp_only_has_underlay_peers(root):
    bgp = bgp_instance(root)
    assert text(peers(bgp)["10.0.254.0"], "bgp:config/bgp:mapped-peer-group-tag") == "SPINE"
    assert "CarrierA_NL" not in peer_groups(bgp)


def test_vrf_bgp_sessions(root):
    v4 = peers(bgp_vrf(root, "internet", "ipv4"))
    CarrierA = settings(v4["198.18.1.153"])
    assert "peer-as 1299" in CarrierA
    assert "route-map-out POL_CarrierA_NL_EXPORT" in CarrierA
    assert "maximum-prefix 12000" in settings(v4["198.18.0.253"])
    v6 = peers(bgp_vrf(root, "internet", "ipv6"))
    assert "route-map-out POL_RS_NL_V6_EXPORT" in settings(v6["2001:db8:ffff::3"])


def _snapshot_rules():
    """An OcNOS route-map entry with no match clause matches every route, so a
    NetBox rule with match conditions must never render without one - either
    translated, or failed closed via PL_MATCH_NONE (common/ocnos/bgp/policy.j2)."""
    data = json.loads((SNAPSHOT_DIR / f"{DEVICE}.json").read_text())
    rules = {p["name"]: p["rules"] for p in data["routing_policies"]}
    return data, rules


def test_route_map_entries_keep_their_match_conditions(root):
    data, rules = _snapshot_rules()
    # `protocol bgp` is always true in an import-only policy - not a condition there
    used = {"import": set(), "export": set()}
    for s in data["bgp_sessions"] + data["bgp_peer_groups"]:
        used["import"] |= set(s["import_policies"])
        used["export"] |= set(s["export_policies"])
    import_only = used["import"] - used["export"]
    checked = 0
    for (name, seq), (_, matches, _) in route_maps(root).items():
        if name == "RM_REDIST_ALL":
            continue
        rule = next(r for r in rules[name] if (r["index"] + 1) * 100 <= seq < (r["index"] + 2) * 100)
        custom = [
            m for m in rule["match_custom"] or []
            if m.get("name") and not (name in import_only and m == {"name": "protocol", "value": "bgp"})
        ]
        conditions = (
            rule["match_ip_address"] or rule["match_ipv6_address"] or rule["match_community"]
            or rule["match_aspath_list"] or custom
        )
        if conditions:
            checked += 1
            assert matches, f"{name} {seq} lost its match conditions"
    assert checked > 50


def test_policy_references_all_defined(root):
    pls = prefix_lists(root)
    maps = route_maps(root)
    aspaths = aspath_lists(root)
    for key, entries in pls.items():
        assert entries, f"prefix-list {key} is empty"
    names = {"ipv4-prefix-list": {n for afi, n in pls if afi == "ipv4"},
             "ipv6-prefix-list": {n for afi, n in pls if afi == "ipv6"},
             "as-path": set(aspaths)}
    for (name, seq), (_, matches, _) in maps.items():
        for match in matches:
            kind, _, ref = match.partition(" ")
            if kind in names:
                assert ref in names[kind], f"{name} {seq}: {match}"
    route_map_names = {name for name, _ in maps}
    for ref in texts(root, ".//bgp:route-map-filter/bgp:config/bgp:route-map-name") + texts(
            root, ".//bgp:redist-route-map-name"):
        assert ref in route_map_names, ref


def test_bgp_protection_expanded_into_transit_import(root):
    maps = route_maps(root)
    denies = [k for k, v in maps.items() if k[0] == "POL_CarrierA_NL_IMPORT" and 2100 <= k[1] < 2200 and v[0] == "deny"]
    assert len(denies) == 7  # one per BGP_PROTECTION permit rule
    assert maps[("POL_CarrierA_NL_IMPORT", 2104)] == ("deny", ["ipv4-prefix-list BOGONS_ORLONGER"], [])
    assert not any(name == "BGP_PROTECTION" for name, _ in maps)


def test_transit_export_community_and_nhs(root):
    sets = route_maps(root)[("POL_CarrierA_NL_EXPORT", 1100)][2]
    assert "community 1299:5529 additive" in sets
    assert "next-hop-self" in af_config(peer_groups(bgp_instance(root))["SPINE"], "ipv4")


def test_protocol_bgp_is_true_on_import_only(root):
    maps = route_maps(root)
    # import-only: `from protocol bgp` dropped as a condition, the entry stays live
    assert maps[("POL_RS_NL_IMPORT", 1100)] == ("permit", [], ["local-preference 500"])
    assert "POL_RS_NL_IMPORT 1100: protocol bgp has no OcNOS route-map equivalent" not in comments(root)
    # export: still fails closed
    assert "ipv4-prefix-list PL_MATCH_NONE" in maps[("POL_INT_EXPORT", 100)][1]
