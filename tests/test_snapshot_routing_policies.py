"""Loader + OcNOS translation coverage for the snapshot routing_policies/prefix_lists/
communities/aspath_lists keys (fetch_netbox_snapshot.serialize_routing_policies()):
a copy of the synthetic OcNOS snapshot with a small, hand-picked policy set covering
each Junos construct common/ocnos/bgp/policy.j2 has to translate (or fail closed on),
rendered through router/ocnos/main.j2 (NETCONF XML, read via tests/ocnos_xml.py). Real-data coverage of the same template is in
test_router_ocnos_snapshot.py."""
import json

import pytest

import netbox_snapshot
from ocnos_xml import aspath_lists, comments, prefix_lists, route_maps

DEVICE = "r1-ocnos-610-12-nl1"


def _rule(index, action="permit", **kw):
    rule = {
        "index": index,
        "action": action,
        "match_ip_address": [],
        "match_ipv6_address": [],
        "match_community": [],
        "match_aspath_list": [],
        "match_custom": None,
        "set_actions": None,
    }
    rule.update(kw)
    return rule


def _pl(id, name, *prefixes):
    return {"id": id, "name": name, "family": "ipv6" if ":" in prefixes[0] else "ipv4", "tags": [], "rules": [
        {"index": i, "action": "permit", "prefix": None, "prefix_custom": p, "ge": None, "le": None}
        for i, p in enumerate(prefixes)
    ]}


def _rf(prefix, match_type, value=None):
    rf = {"name": "route-filter", "prefix": prefix, "match-type": match_type}
    if value:
        rf["value"] = value
    return rf


@pytest.fixture
def root(render_xml, tmp_path, monkeypatch):
    data = json.loads((netbox_snapshot.SNAPSHOT_DIR / f"{DEVICE}.json").read_text())
    data["prefix_lists"] = [
        _pl(1, "PL_OWN_V4", "198.18.0.232/24"),
        _pl(2, "PL_OWN_V6", "2001:db8::/32"),
        _pl(3, "BOGONS", "10.0.0.0/8", "192.168.0.0/16"),
        _pl(4, "PL_UNUSED", "198.18.1.101/24"),
    ]
    data["communities"] = [{"id": 7, "value": "1299:5529", "description": "CarrierA_NO_NTT"}]
    data["aspath_lists"] = [
        {"id": 20, "name": "ASNLIST_CarrierA_NL", "rules": [
            {"index": 0, "pattern": ".*8075", "description": "ASN8075"},
            {"index": 1, "pattern": "6939.*", "description": "ASN6939"},
            {"index": 2, "pattern": "(1|2)+", "description": "untranslatable"},
        ]},
        {"id": 21, "name": "ASNLIST_WEIRD", "rules": [{"index": 0, "pattern": "[0-9]{5}", "description": "x"}]},
    ]
    data["routing_policies"] = [
        # CarrierA import: exact default, `from policy`, as-path list, catch-all
        {"id": 10, "name": "POL_CarrierA_NL_IMPORT", "tags": [], "rules": [
            _rule(10, match_custom=[_rf("0.0.0.0/0", "exact")],
                  set_actions=[{"name": "local-preference", "action": "110"}]),
            _rule(20, action="deny", match_custom=[{"name": "policy", "value": "BGP_PROTECTION"}]),
            _rule(30, match_aspath_list=[20], set_actions=[{"name": "local-preference", "action": "110"}]),
            _rule(31, match_aspath_list=[21]),
            _rule(40, set_actions=[{"name": "local-preference", "action": "90"}]),
            _rule(50, match_custom=[{"name": "protocol", "value": "bgp"}],
                  set_actions=[{"name": "local-preference", "action": "80"}]),
            _rule(999, action="deny"),
        ]},
        # only reachable through the "policy" link above - expanded inline, not its own route-map
        {"id": 11, "name": "BGP_PROTECTION", "tags": [], "rules": [
            _rule(0, match_ip_address=[3], match_custom=[{"pl_match_type": "orlonger"}]),
            _rule(1, match_custom=[_rf("0.0.0.0/0", "prefix-length-range", "/25-/32")]),
            _rule(2, match_custom=[_rf("::0/0", "prefix-length-range", "/49-/128")]),
            _rule(999, action="deny"),
        ]},
        # CarrierA export: several route-filters in one rule, community add, protocol match
        {"id": 12, "name": "POL_CarrierA_NL_EXPORT", "tags": [], "rules": [
            _rule(0, match_custom=[
                _rf("198.18.1.12/24", "orlonger"),
                _rf("198.18.0.232/24", "longer"),
                _rf("198.18.1.17/32", "address-mask", "198.18.1.164"),
                _rf("198.18.1.19/24", "upto", "/26"),
            ], set_actions=[{"name": "community add", "action": "CarrierA_NO_NTT"},
                            {"name": "as-path prepend", "action": "65000 65000"}]),
            _rule(1, match_custom=[{"name": "protocol", "value": "direct"}]),
            _rule(2, match_ip_address=[1], set_actions=[{"name": "community add", "action": "NO_EXPORT NO_HE"}]),
            _rule(3, match_custom=[{"name": "protocol", "value": "bgp"}]),
            _rule(999, action="deny"),
        ]},
        {"id": 13, "name": "POL_CarrierA_NL_EXPORT_V6", "tags": [], "rules": [
            _rule(0, match_custom=[_rf("2001:db8::/32", "orlonger"), {"name": "family", "value": "inet6"}]),
        ]},
        {"id": 14, "name": "POL_UNREFERENCED", "tags": [], "rules": [_rule(0)]},
    ]
    (tmp_path / f"{DEVICE}.json").write_text(json.dumps(data))
    monkeypatch.setattr(netbox_snapshot, "SNAPSHOT_DIR", tmp_path)
    self_ctx = netbox_snapshot.load_context(DEVICE)
    return render_xml("router/ocnos/main.j2", self_ctx)[0]


@pytest.fixture
def maps(root):
    return route_maps(root)


@pytest.fixture
def pls(root):
    return prefix_lists(root)


def test_sequence_numbers_leave_room_for_expansion(maps):
    assert [(seq, action) for (name, seq), (action, _, _) in maps.items() if name == "POL_CarrierA_NL_IMPORT"] == [
        (1100, "permit"),
        (2101, "deny"),
        (2102, "deny"),
        (2103, "deny"),
        (3100, "permit"),
        (3200, "permit"),
        (4100, "permit"),
        (5100, "permit"),
        (100000, "deny"),
    ]


def test_from_policy_expanded_into_one_deny_per_permit_rule(maps, pls):
    # BGP_PROTECTION's three permit rules become three deny entries; its own deny drops out
    assert maps[("POL_CarrierA_NL_IMPORT", 2101)][1] == ["ipv4-prefix-list BOGONS_ORLONGER"]
    assert maps[("POL_CarrierA_NL_IMPORT", 2102)][1] == [
        "ipv4-prefix-list POL_CarrierA_NL_IMPORT_2102_BGP_PROTECTION",
    ]
    assert maps[("POL_CarrierA_NL_IMPORT", 2103)][1] == [
        "ipv6-prefix-list POL_CarrierA_NL_IMPORT_2103_BGP_PROTECTION_V6",
    ]
    assert pls[("ipv4", "POL_CarrierA_NL_IMPORT_2102_BGP_PROTECTION")] == ["seq 1 permit 0.0.0.0/0 ge 25 le 32"]
    assert pls[("ipv6", "POL_CarrierA_NL_IMPORT_2103_BGP_PROTECTION_V6")] == ["seq 1 permit ::0/0 ge 49 le 128"]
    assert not any(name == "BGP_PROTECTION" for name, _ in maps)


def test_prefix_list_orlonger_becomes_derived_list(pls):
    assert pls[("ipv4", "BOGONS_ORLONGER")] == [
        "seq 1 permit 10.0.0.0/8 le 32",
        "seq 2 permit 192.168.0.0/16 le 32",
    ]


def test_route_filters_share_one_list_with_mapped_match_types(maps, pls):
    assert maps[("POL_CarrierA_NL_EXPORT", 100)] == (
        "permit",
        ["ipv4-prefix-list POL_CarrierA_NL_EXPORT_100"],
        ["as-path-prepend 65000 65000", "community 1299:5529 additive"],
    )
    assert pls[("ipv4", "POL_CarrierA_NL_EXPORT_100")] == [
        "seq 1 permit 198.18.1.12/24 le 32",
        "seq 2 permit 198.18.0.232/24 ge 25 le 32",
        "seq 3 permit 198.18.1.19/24 le 26",
    ]


def test_ipv6_route_filter_and_family(maps, pls):
    # one IPv6 prefix-list per entry: `family inet6` (PL_ANY_V6) is implied by the
    # route-filter's own IPv6 list, so it's dropped rather than failing closed
    assert maps[("POL_CarrierA_NL_EXPORT_V6", 100)][1] == ["ipv6-prefix-list POL_CarrierA_NL_EXPORT_V6_100_V6"]
    assert pls[("ipv6", "PL_ANY_V6")] == ["seq 1 permit ::/0 le 128"]


def test_at_most_one_prefix_list_per_family(root):
    # the OcNOS model holds one IPv4 + one IPv6 prefix-list per route-map entry
    maps = route_maps(root)
    assert all(len([m for m in matches if m.startswith("ipv4-prefix-list")]) <= 1 for _, matches, _ in maps.values())
    assert all(len([m for m in matches if m.startswith("ipv6-prefix-list")]) <= 1 for _, matches, _ in maps.values())


def test_protocol_match_fails_closed(root, maps, pls):
    assert "POL_CarrierA_NL_EXPORT 200: protocol direct has no OcNOS route-map equivalent" in comments(root)
    assert maps[("POL_CarrierA_NL_EXPORT", 200)][1] == [
        "ipv4-prefix-list PL_MATCH_NONE",
        "ipv6-prefix-list PL_MATCH_NONE_V6",
    ]
    assert pls[("ipv4", "PL_MATCH_NONE")] == ["seq 1 deny 0.0.0.0/0 le 32"]
    assert pls[("ipv6", "PL_MATCH_NONE_V6")] == ["seq 1 deny ::/0 le 128"]


def test_protocol_bgp_true_only_in_import_only_policies(maps):
    # POL_CarrierA_NL_IMPORT is import-only: `protocol bgp` is dropped as a condition
    assert maps[("POL_CarrierA_NL_IMPORT", 5100)] == ("permit", [], ["local-preference 80"])
    # POL_CarrierA_NL_EXPORT is export: `protocol bgp` still fails closed
    assert "ipv4-prefix-list PL_MATCH_NONE" in maps[("POL_CarrierA_NL_EXPORT", 400)][1]


def test_communities_resolved_well_known_or_skipped(root, maps):
    assert "POL_CarrierA_NL_EXPORT 300: community NO_HE not found in NetBox - not set" in comments(root)
    assert "community no-export additive" in maps[("POL_CarrierA_NL_EXPORT", 300)][2]


def test_aspath_lists_translated(root, maps):
    assert "as-path ASNLIST_CarrierA_NL" in maps[("POL_CarrierA_NL_IMPORT", 3100)][1]
    lists = aspath_lists(root)
    assert lists["ASNLIST_CarrierA_NL"] == ["_8075$", "^6939_"]
    # a list with no translatable pattern fails closed instead of matching everything
    assert "ipv4-prefix-list PL_MATCH_NONE" in maps[("POL_CarrierA_NL_IMPORT", 3200)][1]
    assert "ASNLIST_WEIRD" not in lists


def test_unreferenced_objects_not_rendered(maps, pls):
    assert not any(name == "POL_UNREFERENCED" for name, _ in maps)
    assert not any(name == "PL_UNUSED" for _, name in pls)
