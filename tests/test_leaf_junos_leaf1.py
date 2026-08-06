"""Targeted line-level tests for leaf/junos/main.j2's VSTP handling against a
second real device snapshot (tests/snapshots/leaf1-610-12-nl1.json) - this
device has real VSTP_BRIDGEID/VSTP_BRIDGEPRIO custom fields and a VSTP_OFF
disabled port, none of which tests/test_leaf_junos.py's leaf1-607-13-nl1
fixture has.
"""
from netbox_snapshot import load_context

TEMPLATE = "leaf/junos/main.j2"
DEVICE = "leaf1-610-12-nl1"


def test_renders_without_error(render):
    output = render(TEMPLATE, load_context(DEVICE))
    assert output.strip() != ""


def test_esi_lacp_config_on_multihomed_lag(render, rendered_lines):
    # ae16 is linked (via the netbox_custom_objects "esi" custom object type)
    # to ESI 00:00:00:00:00:00:00:00:03:16.
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "set interfaces ae16 esi 00:00:00:00:00:00:00:00:03:16" in lines
    assert "set interfaces ae16 esi all-active" in lines
    assert "set interfaces ae16 aggregated-ether-options lacp system-id 00:00:00:00:03:16" in lines
    assert "set interfaces ae16 aggregated-ether-options lacp admin-key 16" in lines


def test_vstp_groups_and_disabled_port(render, rendered_lines):
    # et-0/0/55 has the VSTP_OFF custom field set (migrated from the vstp
    # config_context's "disabled" list).
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "set groups APPLY-GROUP-VSTP protocols vstp vlan <*> system-identifier 00:00:00:00:00:01" in lines
    assert "set groups APPLY-GROUP-VSTP protocols vstp vlan <*> bridge-priority 0" in lines
    assert "set protocols vstp apply-groups APPLY-GROUP-VSTP" in lines
    assert "set protocols vstp interface all" in lines
    assert "set protocols vstp interface et-0/0/55 disable" in lines
