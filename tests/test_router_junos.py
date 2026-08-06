"""Targeted line-level tests for router/junos/main.j2 against a real device
snapshot (tests/snapshots/r1-610-12-nl1.json) captured from NetBox - see
tests/fetch_netbox_snapshot.py and tests/netbox_snapshot.py.

r1-610-12-nl1 carries real internet transit sessions (CarrierA AS1299, CarrierB
AS174) plus VRF/EVPN route-target config, which the hand-built spine/junos
fixture doesn't cover.
"""
from netbox_mocks import FakeCF
from netbox_snapshot import load_context

TEMPLATE = "router/junos/main.j2"
DEVICE = "r1-610-12-nl1"


def test_renders_without_error(render):
    output = render(TEMPLATE, load_context(DEVICE))
    assert output.strip() != ""


def test_hostname_and_asn(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "set system host-name r1-610-12-nl1" in lines
    assert "set routing-options autonomous-system 65000" in lines


def test_loopback_vrf_dual_stack_addressing(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert 'set interfaces lo0 unit 1 description "Loopback :: vrf:internet"' in lines
    assert "set interfaces lo0 unit 1 family inet address 198.18.0.34/32" in lines
    assert "set interfaces lo0 unit 1 family inet6 address 2001:db8:3101::3/128" in lines


def test_vrf_evpn_route_target(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "set routing-instances internet instance-type vrf" in lines
    assert "set routing-instances internet protocols evpn ip-prefix-routes vni 20001" in lines
    assert (
        "set routing-instances internet protocols evpn ip-prefix-routes export POL_INTERNET_EVPN_EXPORT"
        in lines
    )


def test_ospf_underlay_p2p_with_bfd(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "set protocols ospf area 0.0.0.0 interface et-0/0/24.0 interface-type p2p" in lines
    assert (
        "set protocols ospf area 0.0.0.0 interface et-0/0/24.0 bfd-liveness-detection minimum-interval 300"
        in lines
    )


def test_bgp_transit_peers(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "set protocols bgp group CarrierA_NL neighbor 198.18.0.73 peer-as 1299" in lines
    assert 'set protocols bgp group CarrierA_NL neighbor 198.18.0.73 description "CarrierA"' in lines
    assert 'set protocols bgp group CarrierB_NL neighbor 198.18.0.23 description "CarrierB_A"' in lines


def test_access_port_fec_and_vtep_layer2_binding(render, rendered_lines):
    # et-0/0/28 (FEC=fec91) and et-0/0/29 (FEC=none) are real FEC-tagged ports;
    # lo0.0 carries the "vtep" tag, so every access/tagged port also gets a
    # routing-instances LAYER2 binding line ahead of its interface config.
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "set interfaces et-0/0/28 ether-options fec fec91" in lines
    assert "set interfaces et-0/0/29 ether-options fec none" in lines
    assert "set routing-instances LAYER2 interface et-0/0/0.0" in lines
    assert 'set interfaces et-0/0/0 description "nl-bks400-prod12-live-ens1f0np0"' in lines
    assert "set interfaces et-0/0/0 mtu 9216" in lines
    assert (
        "set interfaces et-0/0/0 unit 0 family ethernet-switching interface-mode trunk "
        "vlan members [VLAN690 VLAN801 VLAN804 VLAN1802]"
        in lines
    )


def test_disabled_interface_gets_disabled_marker(render, rendered_lines):
    # router/junos used to omit the "DISABLED" description marker that every
    # other role's disabled ports get from common/junos/interfaces/access.j2 -
    # a disabled port with no description rendered `description ""` instead of
    # `description "DISABLED"`, and one with a description didn't get the
    # " :: DISABLED" suffix. Fixed as part of merging router into the shared
    # common/junos/interfaces/access.j2 partial.
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert 'set interfaces et-0/0/6 description "DISABLED"' in lines
    assert 'set interfaces et-0/0/22 description "RESERVED FOR TRANSIT :: DISABLED"' in lines


def test_re_protect_v4_v6_and_arp_policer(render, rendered_lines):
    # lo0.1 has both INPUT_FILTER=re-protect and INPUT_FILTER_V6=re-protect_V6,
    # and et-0/0/29.7 has the IXPORT custom field set - real coverage for all
    # three feature flags in common/junos/re-protect.j2 at once, plus the two
    # other IXPORT consumers (common/junos/system/arp-ix.j2's aging-timer and
    # common/junos/interfaces/routed.j2's per-unit policer application), which
    # previously rendered but had no assertion coverage.
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "delete firewall" in lines
    assert "set firewall family inet filter re-protect interface-specific" in lines
    assert "set firewall family inet6 filter re-protect_V6 interface-specific" in lines
    assert "set firewall family inet6 filter re-protect_V6 term allow_p2p then accept" in lines
    assert "set firewall policer ARP-POLICER if-exceeding bandwidth-limit 2m" in lines
    assert "set firewall policer small-bw-policer if-exceeding bandwidth-limit 1m" in lines
    assert "set firewall policer tcp-policer if-exceeding bandwidth-limit 500k" in lines
    assert "set system arp interfaces et-0/0/29.7 aging-timer 240" in lines
    assert "set interfaces et-0/0/29 unit 7 family inet policer arp ARP-POLICER" in lines


def test_ddos_protection_aggregate_limits(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "set system ddos-protection protocols arp aggregate bandwidth 40000" in lines
    assert "set system ddos-protection protocols arp aggregate burst 20000" in lines
    assert "set system ddos-protection protocols ndpv6 aggregate bandwidth 40000" in lines
    assert "set system ddos-protection protocols ndpv6 aggregate burst 20000" in lines


def test_grpc_rendered_when_gnmi_monitored(render, rendered_lines):
    # r1-610-12-nl1 has the GNMI_MONITORED custom field set (migrated from
    # the gnmi-monitored tag) - router/junos/main.j2 didn't include grpc.j2
    # at all before this migration wired it in.
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "set system services extension-service request-response grpc clear-text address 10.0.254.250" in lines
    assert "set system services extension-service request-response grpc clear-text port 32767" in lines


def test_overlay_switch_options_and_policy(render, rendered_lines):
    # lo0.0 carries the "vtep" tag, so router-id/route-distinguisher use its
    # address rather than the device's primary IP (they happen to be equal
    # here since lo0.0's address IS the primary IP).
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "set switch-options vrf-target target:65000:1" in lines
    assert "set switch-options route-distinguisher 10.0.254.250:1" in lines
    assert "set routing-options router-id 10.0.254.250" in lines
    assert "set forwarding-options storm-control-profiles default all" in lines
    assert "set policy-options policy-statement lbpp then load-balance per-flow" in lines
    assert "set routing-options forwarding-table export lbpp" in lines


def test_fabric_vrf_without_vni_does_not_crash(render):
    # Regression test: common/junos/routing-instance.j2 used to gate VNI-only
    # rendering on an undefined `fabric` variable (should have been `is_fabric`),
    # so the guard was always a no-op and a fabric-tagged edge router with a VRF
    # that has no VNI custom field set would crash the whole render on
    # `vni.cf.EXPORT_POLICY` with `vni` being None.
    context = load_context(DEVICE)
    for iface in context["device"].interfaces:
        if iface.vrf is not None and iface.vrf.name == "internet":
            iface.vrf.cf = FakeCF()
    render(TEMPLATE, context)
