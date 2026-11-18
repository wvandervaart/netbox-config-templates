"""Targeted tests for the NETCONF XML router/ocnos/main.j2 renders.

No OcNOS device exists in NetBox yet, so these render against the hand-built
build_ocnos_router_context() mock (see fixtures.py) - swap to a real
fetch_netbox_snapshot.py snapshot + load_context() once one does. Element paths
are read through tests/ocnos_xml.py (namespaces mirror common/ocnos/ns.j2).
"""
from collections import Counter

import pytest

from fixtures import build_ocnos_router_context
from ocnos_xml import (
    af_config,
    bgp_instance,
    bgp_vrf,
    bridge,
    comments,
    config_children,
    dot1q,
    find,
    findall,
    interface_names,
    interfaces,
    ipv4,
    ipv6,
    lag_member,
    local,
    network_instances,
    peer_groups,
    peers,
    prefix_lists,
    route_maps,
    settings,
    static_routes,
    switchport,
    text,
    texts,
    vrf_summary,
)

TEMPLATE = "router/ocnos/main.j2"


@pytest.fixture
def xml(render_xml):
    return render_xml(TEMPLATE, build_ocnos_router_context())


@pytest.fixture
def root(xml):
    return xml[0]


@pytest.fixture
def intfs(root):
    return interfaces(root)


def test_single_netconf_config_document(root):
    assert root.tag == "{urn:ietf:params:xml:ns:netconf:base:1.0}config"


def test_every_container_and_interface_rendered_once(root):
    # edit-config rejects a container or list key twice - every partial must merge
    # into one top-level container and one entry per interface
    assert [t for t, c in Counter(local(c.tag) for c in root if isinstance(c.tag, str)).items() if c > 1] == []
    names = interface_names(root)
    assert names and [n for n, c in Counter(names).items() if c > 1] == []


def test_system(root):
    assert text(root, "sys:system-info/sys:config/sys:hostname") == "r1-ocnos-nl1"
    assert text(root, "sys:system-info/sys:clock/sys:config/sys:timezone-name") == "Amsterdam"
    users = {text(u, "user:username"): u for u in findall(root, "user:user-management/user:users/user:user")}
    assert text(users["jdoe"], "user:config/user:role") == "network-admin"
    assert text(users["jdoe"], "user:config/user:password-hashed") == "0xFAKEHASH"
    # users without an 'ocnos' system entry are skipped
    assert "junosonly" not in users
    ntp = find(root, "ntp:ntp/ntp:vrfs/ntp:vrf")
    assert text(ntp, "ntp:vrf-name") == "management"
    assert find(ntp, "ntp:config/ntp:feature-enable") is not None
    assert "192.0.2.123" in texts(ntp, "ntp:servers/ntp:server/ntp:server-address")
    dns = find(root, "dns:dns/dns:vrfs/dns:vrf")
    assert text(dns, "dns:vrf-name") == "management"
    assert "192.0.2.53" in texts(dns, "dns:servers/dns:server/dns:address")


def test_syslog_port_only_when_in_ocnos_range(root):
    servers = {
        text(s, "log:address"): (text(s, "log:config/log:port"), text(s, "log:config/log:severity"))
        for s in findall(root, "log:logging/log:remote-logging/log:remote-servers/log:remote-server/log:servers/log:server")
    }
    assert servers["192.0.2.80"] == ("1514", "7")
    assert servers["192.0.2.81"] == (None, "7")


def test_mgmt_services_in_management_vrf(root):
    assert text(root, "ssh:ssh-server/ssh:vrfs/ssh:vrf/ssh:vrf-name") == "management"
    assert find(root, "ms:netconf-server/ms:vrfs/ms:vrf/ms:netconf-ssh-config/ms:config/ms:feature-netconf-ssh") is not None


def test_snmp_from_config_context(root):
    server = find(root, "snmp:snmp/ss:servers/ss:server")
    assert text(server, "ss:vrf-name") == "management"
    assert find(server, "ss:config/ss:enabled") is not None
    assert text(server, "sx:snmp-views/sx:snmp-view/sx:oid-trees/sx:oid-tree/sx:config/sx:filter-type") == "included"
    community = find(server, "sx:communities/sx:community")
    assert text(community, "sx:community-name") == "public-ro"
    assert [text(community, f"sx:config/sx:{leaf}") for leaf in ("community-view-name", "version", "access")] == [
        "all", "v2c", "ro",
    ]


def test_vrf_definition(root):
    vrfs = network_instances(root, "vrf")
    assert "internet" in vrfs
    assert vrf_summary(vrfs["internet"])[0] == "10.255.0.20:100"
    assert "management" not in vrfs


def test_vrf_router_id_and_route_targets(root):
    rd, router_id, rts = vrf_summary(network_instances(root, "vrf")["internet"])
    # the VRF's own loopback, skipping its anycast address
    assert router_id == "203.0.113.1"
    assert dict(rts) == {"65100:100": "import export", "65100:200": "import", "65100:300": "export"}


def test_mgmt_interface(intfs):
    eth0 = intfs["eth0"]
    assert ipv4(eth0) == ["192.0.2.20/24"]
    assert "vrf-name" not in config_children(eth0)


def test_lag_members(intfs):
    xe1 = intfs["xe1"]
    assert lag_member(xe1) == ("1", "active")
    assert text(xe1, "agg:member-aggregation/agg:config/agg:agg-type") == "lacp"
    assert text(xe1, "eth:ethernet/ext:extended-ethernet/ext:config/ext:forward-err-correction") == "off"
    assert text(xe1, "eth:ethernet/eth:config/eth:port-speed") == "25g"
    descriptions = [text(i, "if:config/if:description") for i in intfs.values()]
    assert "po1 :: core01-et-0/0/2 :: CBL-0042" in descriptions
    assert find(intfs["xe2"], "eth:ethernet/ext:extended-ethernet") is None


def test_lag_mtu_on_members_not_bundle(intfs):
    # OcNOS rejects an MTU on a poN - the bundle inherits it from its members
    assert text(intfs["xe1"], "if:config/if:mtu") == "9216"
    assert text(intfs["xe2"], "if:config/if:mtu") == "9216"
    assert text(intfs["po1"], "if:config/if:mtu") is None


def test_subinterface_vrf_and_addresses(intfs):
    sub = intfs["xe3.100"]
    assert dot1q(sub) == "100"
    assert text(sub, "if:config/if:vrf-name") == "internet"
    assert ipv4(sub) == ["198.51.100.2/29", "198.51.100.9/29"]
    assert ipv6(sub) == ["2001:db8:100::2/64"]
    # the VRRP virtual address is not configured as an interface address
    assert not any(a.startswith("198.51.100.1/") for a in ipv4(sub))


def test_vrrp(root):
    instances = findall(root, "vrrp:vrrp/vrrp:ipv4-instances/vrrp:ipv4-instance")
    assert [text(i, "vrrp:virtual-router-id") for i in instances] == ["10"]
    intf = find(instances[0], "vrrp:interfaces/vrrp:interface")
    assert text(intf, "vrrp:interface-name") == "xe3.100"
    assert text(intf, "vrrp:config/vrrp:priority") == "250"
    assert text(intf, "vrrp:virtual-ip/vrrp:config/vrrp:virtual-ip-address") == "198.51.100.1"
    assert find(intf, "vrrp:protocol-enable/vrrp:config/vrrp:enable") is not None


def test_disabled_interface_shutdown(intfs):
    assert "shutdown" in config_children(intfs["xe4"])
    assert "shutdown" not in config_children(intfs["xe3.100"])


def test_loopbacks(intfs):
    lo = intfs["loopback1"]
    assert ipv4(lo) == ["10.255.0.20/32"]
    assert "vrf-name" not in config_children(lo)
    lo_vrf = intfs["loopback2"]
    assert text(lo_vrf, "if:config/if:vrf-name") == "internet"
    # first IPv4 is primary, only further ones are secondary
    assert ipv4(lo_vrf) == ["203.0.113.254/32", "203.0.113.1/32"]


def test_vlan_database(root):
    br = bridge(root)
    assert text(br, "br:config/br:protocol") == "rstp-vlan-bridge"
    # every VLAN on an enabled switchport or SVI, once each, sorted by vid;
    # VLAN99 only sits on a disabled port
    vlans = [
        (text(v, "vlan:vlan-id"), text(v, "vlan:customer-vlan/vlan:config/vlan:name"),
         text(v, "vlan:customer-vlan/vlan:config/vlan:state"))
        for v in findall(br, "vlan:vlans/vlan:vlan")
    ]
    assert vlans == [("10", "VLAN10", "enable"), ("20", "VLAN20", "enable"), ("30", "VLAN30", "enable")]
    # bridge ports: every switchport, bundles instead of their members
    assert texts(br, "br:bridge-ports/br:interface/br:name") == ["xe5", "xe6", "po2"]


def test_access_switchport(intfs):
    xe5 = intfs["xe5"]
    assert text(xe5, "if:config/if:description") == "server01-eno1"
    assert "enable-switchport" in config_children(xe5)
    assert switchport(xe5) == {"mode": "access", "vlan": "10", "native": None, "allowed": None}


def test_trunk_switchport(intfs):
    # the native VLAN must also be allowed on an OcNOS trunk
    assert switchport(intfs["xe6"]) == {"mode": "trunk", "vlan": None, "native": "30", "allowed": "10,20,30"}


def test_lag_trunk_switchport_on_bundle_not_member(intfs):
    assert switchport(intfs["po2"])["allowed"] == "20"
    member = intfs["xe7"]
    assert lag_member(member) == ("2", "active")
    assert switchport(member) is None
    assert "enable-switchport" not in config_children(member)


def test_disabled_switchport_not_rendered(intfs):
    assert "xe8" not in intfs


def test_svi_is_routed_not_switched(intfs):
    svi = intfs["vlan1.10"]
    assert switchport(svi) is None
    assert dot1q(svi) is None
    assert text(svi, "if:config/if:vrf-name") == "internet"
    assert ipv4(svi) == ["10.10.0.1/24"]


def test_static_routes(root):
    vrfs = network_instances(root, "vrf")
    assert static_routes(vrfs["default"]) == [("10.99.0.0/16", "Null")]  # the spelling OcNOS stores
    assert static_routes(vrfs["internet"]) == [("0.0.0.0/0", "198.51.100.6")]


def test_ospf_uses_network_statements(root):
    proc = find(root, "ospf:ospfv2/ospf:processes/ospf:process")
    assert text(proc, "ospf:config/ospf:router-id") == "10.255.0.20"
    assert text(proc, "ospf:config/ospf:vrf-name") == "default"
    area = find(proc, "ospf:areas/ospf:area")
    assert text(area, "ospf:area-id") == "0.0.0.0"
    networks = texts(area, "ospf:networks/ospf:network/ospf:prefix")
    assert "10.255.0.20/32" in networks
    # fabric link's connected subnet, not its host address
    assert "10.0.2.0/31" in networks
    passive = find(proc, "ospf:passive-interfaces/ospf:passive-interface")
    assert (text(passive, "ospf:name"), text(passive, "ospf:config/ospf:passive-mode")) == ("loopback1", "enable")
    assert text(proc, "ospf:lsdb/ospf:overflow/ospf:normal-lsa/ospf:config/ospf:max-limit") == "12000"


def test_fabric_interface(root, intfs):
    assert ipv4(intfs["ce0"]) == ["10.0.2.1/31"]
    ospf_if = {text(i, "ospf:name"): i for i in findall(root, "ospf:ospfv2/ospf:interfaces/ospf:interface")}
    assert text(ospf_if["ce0"], "ospf:config/ospf:network-type") == "point-to-point"
    assert text(ospf_if["ce0"], "ospf:config/ospf:enable-bfd") == "enable"


def test_prefix_list_drops_bounds_implied_by_the_length(root):
    # NetBox has ge 24 on a /24 - OcNOS requires len < ge <= le, so ge is left out
    assert prefix_lists(root)[("ipv4", "PL_OWN_V4")] == ["seq 1 permit 198.18.1.139/24 le 32"]


def test_route_maps(root):
    # rule index i -> seq (i+1)*100 (room for `from policy` expansion)
    maps = route_maps(root)
    action, matches, sets = maps[("POL_TRANSIT_EXPORT", 100)]
    assert action == "permit"
    assert matches == ["ipv4-prefix-list PL_OWN_V4"]
    assert sets == ["as-path-prepend 65100 65100"]
    assert maps[("POL_TRANSIT_EXPORT", 200)] == ("deny", [], [])
    action, matches, sets = maps[("POL_TRANSIT_IMPORT", 100)]
    assert matches == ["ipv4-prefix-list POL_TRANSIT_IMPORT_100"]
    assert sets == ["local-preference 200"]
    assert prefix_lists(root)[("ipv4", "POL_TRANSIT_IMPORT_100")] == ["seq 1 permit 0.0.0.0/0"]


def test_redistribute_route_map_exists(root):
    # the model needs a route-map on `redistribute`: a match-less permit keeps CLI semantics
    assert route_maps(root)[("RM_REDIST_ALL", 10)] == ("permit", [], [])
    assert "redistribute connected route-map RM_REDIST_ALL" in settings(bgp_vrf(root, "internet", "ipv4"))


def test_bgp_peer_group_and_members(root):
    bgp = bgp_instance(root)
    assert text(bgp, "bgp:config/bgp:router-id") == "10.255.0.20"
    # peer-groups precede their members
    order = [local(c.tag) for c in bgp]
    assert order.index("peer-groups") < order.index("peers")
    pg = peer_groups(bgp)["IBGP"]
    assert text(pg, "bgp:config/bgp:peer-group-range") == "static"
    # OcNOS wants the peer-group's remote AS before its address-family settings
    assert text(pg, "bgp:config/bgp:peer-as") == "65100"
    assert text(pg, "bgp:bgp-passwords/bgp:bgp-password/bgp:password") == "ibgp-secret"
    assert text(pg, "bgp:bgp-passwords/bgp:bgp-password/bgp:config/bgp:auth-key-encrypt") == "0"
    peer = peers(bgp)["10.255.0.21"]
    assert text(peer, "bgp:config/bgp:peer-as") == "65100"
    assert text(peer, "bgp:config/bgp:mapped-peer-group-tag") == "IBGP"


def test_bgp_global_address_family(root):
    bgp = bgp_instance(root)
    assert "ebgp-max-path 8" in af_config(bgp, "ipv4")
    pg_af = af_config(peer_groups(bgp)["IBGP"], "ipv4")
    assert "activate" in pg_af
    assert "next-hop-self" in pg_af
    # no v6 global peers -> no global ipv6 address-family
    assert af_config(bgp, "ipv6") is None


def test_bgp_vrf_neighbors_get_peer_group_policy_directly(root):
    for nbr, afi in [("198.51.100.6", "ipv4"), ("2001:db8:100::6", "ipv6")]:
        vrf_af = bgp_vrf(root, "internet", afi)
        assert "redistribute connected route-map RM_REDIST_ALL" in settings(vrf_af)
        assert "ebgp-max-path 64" in settings(vrf_af)
        peer = settings(peers(vrf_af)[nbr])
        assert "peer-as 64500" in peer
        assert "activate" in peer
        assert "maximum-prefix 1500000" in peer
        assert "route-map-out POL_TRANSIT_EXPORT" in peer
        assert "route-map-in POL_TRANSIT_IMPORT" in peer
        # router-mode only on OcNOS - VRF neighbors must not join a peer-group
        assert not any("peer-group" in s for s in peer)


def test_manual_cli_line_is_commented_not_applied(root):
    assert "skipped CLI line (not XML): ip domain-name example.net" in comments(root)


def test_manual_xml_snippet_passed_through(render_xml):
    ctx = build_ocnos_router_context()
    ctx["manual_config"] = ['<banner xmlns="urn:example:banner"><motd>hi</motd></banner>']
    root, _ = render_xml(TEMPLATE, ctx)
    assert text(root, "{urn:example:banner}banner/{urn:example:banner}motd") == "hi"


def test_free_text_is_escaped(render_xml):
    ctx = build_ocnos_router_context()
    xe5 = next(i for i in ctx["device"].interfaces.all() if i.name == "xe5")
    xe5.description = "A&B <lab>"
    root, raw = render_xml(TEMPLATE, ctx)
    assert "A&amp;B &lt;lab&gt;" in raw
    assert text(interfaces(root)["xe5"], "if:config/if:description").startswith("A&B <lab> :: ")


SECTIONS = ['system', 'management', 'snmp', 'network-instances', 'interfaces', 'ospf', 'sflow', 'bgp', 'manual']


def test_payload_is_minified_by_default(xml):
    _, raw = xml
    assert len(raw.strip().splitlines()) == 1
    assert "\n" not in raw.strip() and ">  <" not in raw


def test_pretty_mode(render_xml):
    ctx = build_ocnos_router_context()
    ctx["netconf_pretty"] = True
    root, raw = render_xml(TEMPLATE, ctx)
    assert len(raw.strip().splitlines()) > 100
    assert interface_names(root)


def test_sections_render_only_their_containers(render_xml, root):
    full = [local(c.tag) for c in root if isinstance(c.tag, str)]
    seen = []
    for section in SECTIONS:
        ctx = build_ocnos_router_context()
        ctx["netconf_sections"] = [section]
        part, _ = render_xml(TEMPLATE, ctx)
        seen += [local(c.tag) for c in part if isinstance(c.tag, str)]
    # every section on its own is a valid payload, and together they cover the full one
    # (split, the interfaces section adds a network-instances block with the bridge-ports)
    assert [t for t in seen if t != "network-instances"] == [t for t in full if t != "network-instances"]
    ctx = build_ocnos_router_context()
    ctx["netconf_sections"] = ["interfaces"]
    part, _ = render_xml(TEMPLATE, ctx)
    assert [local(c.tag) for c in part] == ["interfaces", "vrrp", "network-instances"]
    br = find(part, "ni:network-instances/ni:network-instance/br:bridge")
    assert texts(br, "br:bridge-ports/br:interface/br:name") == ["xe5", "xe6", "po2"]
    assert find(br, "br:config") is None and find(br, "vlan:vlans") is None
    ctx["netconf_sections"] = ["network-instances"]
    part, _ = render_xml(TEMPLATE, ctx)
    assert find(part, "ni:network-instances/ni:network-instance/br:bridge/br:bridge-ports") is None
