"""Targeted line-level tests for router/eos/main.j2 against a real device
snapshot (tests/snapshots/r1-3-mx08-nl1.json) captured from NetBox - see
tests/fetch_netbox_snapshot.py and tests/netbox_snapshot.py.

r1-3-mx08-nl1 is a real internet-peering edge router (CarrierC + a private
TLQ_INTERNAL peer group), which is useful real-world coverage the hand-built
spine/junos fixture doesn't exercise: route-maps, external peer-as/description,
and a VRF-scoped loopback.
"""
from netbox_snapshot import load_context

TEMPLATE = "router/eos/main.j2"
DEVICE = "r1-3-mx08-nl1"


def test_renders_without_error(render):
    output = render(TEMPLATE, load_context(DEVICE))
    assert output.strip() != ""


def test_hostname(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "hostname r1-3-mx08-nl1" in lines


def test_lag_member_bundled(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "channel-group 1 mode active" in lines
    assert "description Po1 :: sw01-vmware-mx08-ams1-et-0/0/43" in lines


def test_lag_member_fec_disabled(render, rendered_lines):
    # Ethernet25/26 have custom field FEC=["none"], which disables FEC.
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "no error-correction encoding" in lines


def test_loopback_vrf_addressing(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert 'description "Loopback :: vrf:internet"' in lines
    assert "vrf internet" in lines
    assert "ip address 198.18.0.234/32" in lines


def test_bgp_router_id(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "router bgp 65206" in lines
    assert "router-id 172.16.249.247" in lines


def test_bgp_external_peer_with_description(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "neighbor 198.18.0.122 remote-as 60781" in lines
    assert "neighbor 198.18.0.122 description LW_1" in lines


def test_bgp_peer_group_route_map(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "neighbor TLQ_CarrierC_NL_MX08 route-map POL_LW_EXPORT_MX08 out" in lines
