"""Targeted line-level tests for ds/junos/main.j2's RSTP_OFF handling against
a second real device snapshot (tests/snapshots/res1-607-32-nl1.json) - this
device (a Peering Switch, same ds/junos/main.j2 template as
tests/test_ds_junos.py's mds1-610-11-nl1) has real RSTP_OFF-tagged interfaces,
which mds1-610-11-nl1 doesn't have any of.
"""
from netbox_snapshot import load_context

TEMPLATE = "ds/junos/main.j2"
DEVICE = "res1-607-32-nl1"


def test_renders_without_error(render):
    output = render(TEMPLATE, load_context(DEVICE))
    assert output.strip() != ""


def test_rstp_disabled_on_tagged_interface(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "set protocols rstp interface xe-0/0/0 disable" in lines
    assert "set protocols layer2-control bpdu-block interface xe-0/0/0 drop" in lines
