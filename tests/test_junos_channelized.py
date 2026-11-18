"""Junos Evo breakout (channelized) ports - common/junos/interfaces/channelized.j2
plus the parent-skipping in access.j2/lag.j2.

NetBox models a breakout as a parent port (et-0/0/90) plus channel interfaces
et-0/0/90:0..:3 whose `parent` points at it and whose `type` is the channel
speed. No snapshot has a channelized port yet, so the channels are injected into
real snapshots: r1-610-12-nl1 (ACX7100, Junos Evo) for router/junos and
leaf1-610-12-nl1 for the leaf/junos wiring.
"""
from netbox_mocks import FakeInterface, FakeIPAddress, FakeQuerySet
from netbox_snapshot import load_context

PARENT = "et-0/0/90"


def _add_breakout(context, parent_enabled=True, channel_type="25gbase-x-sfp28", indexes=range(4)):
    device = context["device"]
    vlan = next(
        (v for i in device.interfaces for v in [i.untagged_vlan] if v is not None and getattr(v, "name", None)),
        None,
    )
    parent = FakeInterface(PARENT, enabled=parent_enabled, type="100gbase-x-qsfp28", mtu=9216)
    channels = []
    for n in indexes:
        ch = FakeInterface(f"{PARENT}:{n}", type=channel_type, parent=parent, mtu=9216)
        channels.append(ch)
    # :0 as an access port, :1 with a routed sub-interface
    if vlan is not None:
        channels[0].mode = "access"
        channels[0].untagged_vlan = vlan
    sub = FakeInterface(f"{PARENT}:1.100", parent=channels[1], type="virtual", mtu=1500)
    sub.ip_addresses = FakeQuerySet([FakeIPAddress("192.0.2.1/31", assigned_object=sub)])
    device.interfaces = FakeQuerySet(list(device.interfaces) + [parent, *channels, sub])
    return vlan


def _lines_for(rendered_lines, output, name):
    return {line for line in rendered_lines(output) if line.startswith(f"set interfaces {name} ")}


def test_breakout_statement_router(render, rendered_lines):
    context = load_context("r1-610-12-nl1")
    _add_breakout(context)
    lines = rendered_lines(render("router/junos/main.j2", context))
    assert f"set interfaces {PARENT} number-of-sub-ports 4 speed 25g" in lines


def test_parent_gets_only_breakout_line(render, rendered_lines):
    context = load_context("r1-610-12-nl1")
    _add_breakout(context)
    output = render("router/junos/main.j2", context)
    assert _lines_for(rendered_lines, output, PARENT) == {
        f"set interfaces {PARENT} number-of-sub-ports 4 speed 25g"
    }


def test_disabled_parent_does_not_disable_channels(render, rendered_lines):
    context = load_context("r1-610-12-nl1")
    _add_breakout(context, parent_enabled=False)
    output = render("router/junos/main.j2", context)
    assert f"set interfaces {PARENT} disable" not in rendered_lines(output)
    assert _lines_for(rendered_lines, output, PARENT) == {
        f"set interfaces {PARENT} number-of-sub-ports 4 speed 25g"
    }


def test_channels_render_as_normal_interfaces(render, rendered_lines):
    context = load_context("r1-610-12-nl1")
    vlan = _add_breakout(context)
    lines = rendered_lines(render("router/junos/main.j2", context))
    # routed sub-interface of a channel
    assert f"set interfaces {PARENT}:1 unit 100 vlan-id 100 family inet address 192.0.2.1/31" in lines
    # :1 has a sub-interface, so it gets flexible-vlan-tagging itself
    assert f"set interfaces {PARENT}:1 flexible-vlan-tagging" in lines
    if vlan is not None:
        assert (
            f"set interfaces {PARENT}:0 unit 0 family ethernet-switching interface-mode access vlan members {vlan.name}"
            in lines
        )


def test_sub_port_count_from_highest_index(render, rendered_lines):
    context = load_context("r1-610-12-nl1")
    _add_breakout(context, channel_type="10gbase-x-sfpp", indexes=[0, 1, 3])
    lines = rendered_lines(render("router/junos/main.j2", context))
    assert f"set interfaces {PARENT} number-of-sub-ports 4 speed 10g" in lines


def test_unmapped_channel_type_skipped(render, rendered_lines):
    context = load_context("r1-610-12-nl1")
    _add_breakout(context, channel_type="other")
    lines = rendered_lines(render("router/junos/main.j2", context))
    assert not any("number-of-sub-ports" in line for line in lines)


def test_no_breakout_without_channels(render):
    output = render("router/junos/main.j2", load_context("r1-610-12-nl1"))
    assert "number-of-sub-ports" not in output


def test_breakout_statement_leaf(render, rendered_lines):
    context = load_context("leaf1-610-12-nl1")
    _add_breakout(context)
    output = render("leaf/junos/main.j2", context)
    assert _lines_for(rendered_lines, output, PARENT) == {
        f"set interfaces {PARENT} number-of-sub-ports 4 speed 25g"
    }
