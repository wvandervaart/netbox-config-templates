"""Targeted line-level tests for leaf/junos/main.j2 against a real device
snapshot (tests/snapshots/leaf1-607-13-nl1.json) captured from NetBox - see
tests/fetch_netbox_snapshot.py and tests/netbox_snapshot.py.
"""
from netbox_snapshot import load_context

TEMPLATE = "leaf/junos/main.j2"
DEVICE = "leaf1-607-13-nl1"


def test_renders_without_error(render):
    output = render(TEMPLATE, load_context(DEVICE))
    assert output.strip() != ""


def test_hostname_and_asn(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "set system host-name leaf1-607-13-nl1" in lines
    assert "set routing-options autonomous-system 65000" in lines


def test_disabled_interface_is_shut_down(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "set interfaces xe-0/0/4 disable" in lines


def test_loopback_global_and_vrf_addressing(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert 'set interfaces lo0 unit 0 description "Loopback :: vrf:global"' in lines
    assert "set interfaces lo0 unit 0 family inet address 10.0.254.15/32" in lines
    assert 'set interfaces lo0 unit 4 description "Loopback :: vrf:SGBC"' in lines


def test_ospf_underlay_p2p(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "set protocols ospf area 0.0.0.0 interface et-0/0/48.0 interface-type p2p" in lines


def test_bgp_spine_route_reflector_group(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "set protocols bgp group SPINE type internal" in lines
    assert "set protocols bgp group SPINE family evpn signaling" in lines
    assert "set protocols bgp group SPINE multipath" in lines


def test_bgp_external_peer_with_description(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "set protocols bgp group INTSERVICE neighbor 172.18.7.23 peer-as 65005" in lines
    assert 'set protocols bgp group INTSERVICE neighbor 172.18.7.23 description "sol-es03"' in lines


def test_re_protect_v4_only(render, rendered_lines):
    # lo0.0 has INPUT_FILTER=re-protect and no interface has the IXPORT custom
    # field set, so only the v4 filter should render - no v6 filter, no ARP-POLICER.
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "delete firewall" in lines
    assert "set firewall family inet filter re-protect interface-specific" in lines
    assert "set firewall family inet filter re-protect term allow-bgp-source then accept" in lines
    assert not any("family inet6 filter re-protect_V6" in line for line in lines)
    assert not any("ARP-POLICER" in line for line in lines)
    assert "set firewall policer small-bw-policer if-exceeding bandwidth-limit 1m" in lines
    assert 'set policy-options prefix-list bgp-peers apply-path "protocols bgp group <*> neighbor <*>"' in lines


def test_overlay_switch_options_and_policy(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "set switch-options vtep-source-interface lo0.0" in lines
    assert "set switch-options vrf-target target:65000:1" in lines
    assert "set switch-options route-distinguisher 10.0.254.15:1" in lines
    assert "set forwarding-options vxlan-routing overlay-ecmp" in lines
    assert "set policy-options policy-statement LBPP then load-balance per-packet" in lines


def test_esi_lacp_config_on_multihomed_lag(render, rendered_lines):
    # ae3 is linked (via the netbox_custom_objects "esi" custom object type)
    # to ESI 00:00:00:00:00:00:00:00:11:03; the 6th octet is "00" so an
    # explicit lacp admin-key is also expected (see leaf/junos/interfaces/lag.j2).
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "set interfaces ae3 esi 00:00:00:00:00:00:00:00:11:03" in lines
    assert "set interfaces ae3 esi all-active" in lines
    assert "set interfaces ae3 aggregated-ether-options lacp system-id 00:00:00:00:11:03" in lines
    assert "set interfaces ae3 aggregated-ether-options lacp admin-key 3" in lines


def test_grpc_rendered_when_gnmi_monitored(render, rendered_lines):
    # DEVICE has the GNMI_MONITORED custom field set (migrated from the
    # gnmi-monitored tag).
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "set system services extension-service request-response grpc clear-text address 10.0.254.15" in lines
    assert "set system services extension-service request-response grpc clear-text port 32767" in lines
