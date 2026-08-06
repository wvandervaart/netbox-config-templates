"""Targeted line-level tests for spine/junos/*.

These render the templates against lightweight mock NetBox/netbox-bgp objects
(see netbox_mocks.py / fixtures.py) - there's no real NetBox instance involved,
so this only proves the Jinja2 logic does what we intend given known inputs,
not that NetBox's actual data model matches these fixtures exactly.
"""
from fixtures import build_spine_context

MAIN_TEMPLATE = "spine/junos/main.j2"


def test_main_renders_without_error(render):
    output = render(MAIN_TEMPLATE, build_spine_context())
    assert output.strip() != ""


def test_hostname_and_asn(render, rendered_lines):
    lines = rendered_lines(render(MAIN_TEMPLATE, build_spine_context()))
    assert "set system host-name spine01" in lines
    assert "set routing-options autonomous-system 65000" in lines


def test_underlay_ospf_p2p_fabric_link(render, rendered_lines):
    lines = rendered_lines(render(MAIN_TEMPLATE, build_spine_context()))
    assert "set protocols ospf area 0.0.0.0 interface et-0/0/0.0 interface-type p2p" in lines
    assert (
        "set protocols ospf area 0.0.0.0 interface et-0/0/0.0 bfd-liveness-detection minimum-interval 300"
        in lines
    )
    assert "set protocols ospf reference-bandwidth 1000g" in lines


def test_underlay_ospf_passive_loopback(render, rendered_lines):
    lines = rendered_lines(render(MAIN_TEMPLATE, build_spine_context()))
    assert "set protocols ospf area 0.0.0.0 interface lo0.0 passive" in lines


def test_underlay_ospf_p2p_over_lag_bundle(render, rendered_lines):
    lines = rendered_lines(render(MAIN_TEMPLATE, build_spine_context()))
    assert "set protocols ospf area 0.0.0.0 interface ae0.0 interface-type p2p" in lines


def test_fabric_interface_gets_address(render, rendered_lines):
    lines = rendered_lines(render(MAIN_TEMPLATE, build_spine_context()))
    assert (
        'set interfaces et-0/0/0 mtu 9192 unit 0 description "to-leaf01-et-0/0/1"' in lines
    )
    assert "set interfaces et-0/0/0 unit 0 family inet address 10.0.1.0/31" in lines


def test_lag_member_bundled_into_ae0(render, rendered_lines):
    lines = rendered_lines(render(MAIN_TEMPLATE, build_spine_context()))
    assert "set interfaces et-0/0/2 ether-options 802.3ad ae0" in lines
    assert "set interfaces ae0 aggregated-ether-options link-speed 100g" in lines


def test_loopback_gets_primary_address(render, rendered_lines):
    lines = rendered_lines(render(MAIN_TEMPLATE, build_spine_context()))
    assert 'set interfaces lo0 unit 0 description "Loopback :: vrf:global"' in lines
    assert "set interfaces lo0 unit 0 family inet address 10.255.0.1/32 primary" in lines


def test_mgmt_interface_configured(render, rendered_lines):
    lines = rendered_lines(render(MAIN_TEMPLATE, build_spine_context()))
    assert 'set interfaces em0 description "em0"' in lines
    assert "set interfaces em0 unit 0 family inet address 192.0.2.10/24" in lines


def test_disabled_interface_is_shut_down(render, rendered_lines):
    lines = rendered_lines(render(MAIN_TEMPLATE, build_spine_context()))
    assert 'set interfaces et-0/0/5 description "leaf03-et-0/0/9 :: DISABLED"' in lines
    assert "set interfaces et-0/0/5 disable" in lines


def test_bgp_group_and_neighbor(render, rendered_lines):
    lines = rendered_lines(render(MAIN_TEMPLATE, build_spine_context()))
    assert "set protocols bgp group LEAF local-address 10.255.0.1" in lines
    assert "set protocols bgp group LEAF neighbor 10.255.1.1" in lines
    assert 'set protocols bgp group LEAF neighbor 10.255.1.1 description "LEAF01"' in lines
    assert "set protocols bgp group LEAF type internal" in lines
    assert "set protocols bgp group LEAF family evpn signaling" in lines
    assert "set protocols bgp group LEAF family inet unicast" in lines
    assert "set protocols bgp group LEAF multipath" in lines
    assert "set protocols bgp precision-timers" in lines
    assert "set protocols bgp bgp-error-tolerance" in lines


def test_bgp_peer_group_bfd_and_prefix_limit(render, rendered_lines):
    lines = rendered_lines(render(MAIN_TEMPLATE, build_spine_context()))
    assert (
        "set protocols bgp group LEAF bfd-liveness-detection minimum-interval 300" in lines
    )
    assert "set protocols bgp group LEAF family inet unicast prefix-limit maximum 100" in lines


def test_llgr_off_via_custom_field(render, rendered_lines):
    normal = rendered_lines(render(MAIN_TEMPLATE, build_spine_context()))
    llgr_off = rendered_lines(render(MAIN_TEMPLATE, build_spine_context(llgr_off=True)))

    assert "set protocols bgp group LEAF neighbor 10.255.1.1 graceful-restart long-lived receiver disable" not in normal
    assert "set protocols bgp group LEAF neighbor 10.255.1.1 graceful-restart long-lived receiver disable" in llgr_off


def test_maintenance_tag_rejects_bgp_export(render, rendered_lines):
    normal = rendered_lines(render(MAIN_TEMPLATE, build_spine_context(maintenance=False)))
    maintenance = rendered_lines(render(MAIN_TEMPLATE, build_spine_context(maintenance=True)))

    assert "set protocols bgp group LEAF export POL_REJECT" not in normal
    assert "set protocols bgp group LEAF export POL_REJECT" in maintenance


def test_snmp_location_and_contact(render, rendered_lines):
    lines = rendered_lines(render(MAIN_TEMPLATE, build_spine_context()))
    assert 'set snmp contact "noc@example.com"' in lines
    assert (
        'set snmp location "region: region1 dc: site1 room: loc1 rack: rack1"' in lines
    )


def test_grpc_service_bound_to_primary_ip(render, rendered_lines):
    lines = rendered_lines(render(MAIN_TEMPLATE, build_spine_context()))
    assert (
        "set system services extension-service request-response grpc clear-text address 10.255.0.1"
        in lines
    )


def test_sflow_collector_configured(render, rendered_lines):
    lines = rendered_lines(render(MAIN_TEMPLATE, build_spine_context()))
    assert "set protocols sflow collector 10.0.0.99 udp-port 6343" in lines
    assert "set protocols sflow agent-id 10.255.0.1" in lines
