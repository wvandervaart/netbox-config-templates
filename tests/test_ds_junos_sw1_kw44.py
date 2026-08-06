"""Targeted line-level tests for ds/junos/main.j2's Q-in-Q handling
(common/junos/interfaces/qinq.j2) against a real device snapshot
(tests/snapshots/sw1-kw44-nl2.json) - a distribution switch with a q-in-q
CarrierD uplink on xe-0/0/3, which the other ds/junos snapshots don't have.
"""
from netbox_snapshot import load_context

TEMPLATE = "ds/junos/main.j2"
DEVICE = "sw1-kw44-nl2"


def test_renders_without_error(render):
    output = render(TEMPLATE, load_context(DEVICE))
    assert output.strip() != ""


def test_qinq_uplink_interface(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert 'set interfaces xe-0/0/3 description "CarrierD-uplink :: VLAN1001"' in lines
    assert "set interfaces xe-0/0/3 vlan-tagging" in lines
    assert "set interfaces xe-0/0/3 encapsulation extended-vlan-bridge" in lines
    assert "set interfaces xe-0/0/3 mtu 1514" in lines
    assert "set interfaces xe-0/0/3 unit 0 vlan-id-list [4 6]" in lines
    assert "set interfaces xe-0/0/3 unit 0 input-vlan-map push" in lines
    assert "set interfaces xe-0/0/3 unit 0 input-vlan-map vlan-id 1001" in lines
    assert "set interfaces xe-0/0/3 unit 0 output-vlan-map pop" in lines
    assert "set vlans Q-in-Q interface xe-0/0/3.0" in lines
