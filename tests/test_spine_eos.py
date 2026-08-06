"""Targeted line-level tests for spine/eos/main.j2 against a real device
snapshot (tests/snapshots/spine01-610-12-nl1.json) captured from NetBox -
see tests/fetch_netbox_snapshot.py and tests/netbox_snapshot.py.
"""
from netbox_snapshot import load_context

TEMPLATE = "spine/eos/main.j2"
DEVICE = "spine01-610-12-nl1"


def test_renders_without_error(render):
    output = render(TEMPLATE, load_context(DEVICE))
    assert output.strip() != ""


def test_hostname(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "hostname spine01-610-12-nl1" in lines


def test_fabric_p2p_interface(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "description to-r1-610-12-nl1-et-0/0/26" in lines
    assert "ip address 10.0.1.0/31" in lines
    assert "ip ospf area 0.0.0.0" in lines


def test_disabled_interface_is_shut_down(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "description disabled" in lines
    assert "shutdown" in lines


def test_ospf_router_id_and_passive_loopback(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "router ospf 1" in lines
    assert "router-id 10.0.254.0" in lines
    assert "passive-interface Loopback0" in lines


def test_bgp_router_and_route_reflector_client(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "router bgp 65000" in lines
    assert "neighbor LEAF remote-as 65000" in lines
    assert "neighbor LEAF route-reflector-client" in lines
    assert "neighbor LEAF activate" in lines


def test_snmp_community(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "snmp-server community public-ro-1 ro" in lines
