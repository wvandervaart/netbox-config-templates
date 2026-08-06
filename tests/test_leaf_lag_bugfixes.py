"""Coverage for two bugs fixed in leaf/junos/interfaces/lag.j2: a missing
400gbase-x-qsfpdd speed-mapping entry (would KeyError on a 400G LAG member)
and a missing cable-label description suffix (present in every other role's
lag.j2 but previously absent here). Neither committed leaf snapshot has a
400G LAG member or a cable-labeled interface, so this uses a small
hand-built context, same technique as tests/test_bgp_policy_rendering.py.
"""
from netbox_mocks import FakeEsi, FakeInterface, fake_endpoint, fake_link_peer

TEMPLATE = "leaf/junos/interfaces/lag.j2"


def _context(member, ae):
    return {
        "device_interfaces": [member, ae],
        "esi_by_interface": {ae.id: FakeEsi(esi_id="00:00:00:00:00:01:00:00:00:01", interfaces=[ae, member])},
    }


def test_400g_lag_member_gets_correct_link_speed(render, rendered_lines):
    ae = FakeInterface(name="ae0", type="lag", mtu=9192, id="ae0")
    member = FakeInterface(
        name="et-0/0/0",
        type="400gbase-x-qsfpdd",
        lag=ae,
        connected_endpoints=[fake_endpoint("et-0/0/1", device_name="leaf02")],
    )
    lines = rendered_lines(render(TEMPLATE, _context(member, ae)))
    assert "set interfaces ae0 aggregated-ether-options link-speed 400g" in lines


def test_lag_member_description_includes_cable_label(render, rendered_lines):
    ae = FakeInterface(name="ae0", type="lag", mtu=9192, id="ae0")
    member = FakeInterface(
        name="et-0/0/0",
        type="100gbase-x-qsfp28",
        lag=ae,
        connected_endpoints=[fake_endpoint("et-0/0/1", device_name="leaf02")],
        link_peers=[fake_link_peer(cable_label="patch-123")],
    )
    lines = rendered_lines(render(TEMPLATE, _context(member, ae)))
    assert 'set interfaces et-0/0/0 description "ae0 :: leaf02-et-0/0/1 :: patch-123"' in lines
