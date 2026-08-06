"""Targeted line-level tests for mgmt/main.j2 against a real device snapshot
(tests/snapshots/sw01-610-18-ams1.json) captured from NetBox - see
tests/fetch_netbox_snapshot.py and tests/netbox_snapshot.py.
"""
from netbox_snapshot import load_context

TEMPLATE = "mgmt/main.j2"
DEVICE = "sw01-610-18-ams1"


def test_renders_without_error(render):
    output = render(TEMPLATE, load_context(DEVICE))
    assert output.strip() != ""


def test_hostname(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "set system host-name sw01-610-18-ams1" in lines


def test_l3_vlan_interface_addressing(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert 'set interfaces vlan.1900 description "L3: :: vrf:global"' in lines
    assert "set interfaces vlan.1900 family inet address 172.18.100.3/23" in lines


def test_snmp_contact_and_location(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert 'set snmp contact "support@example.org"' in lines
    assert 'set snmp location "region: nl dc: nl1 room: 610 rack: 18"' in lines
    assert "set snmp community public-ro-1 clients 10.99.0.14/32" in lines
