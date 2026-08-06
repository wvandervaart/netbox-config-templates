"""Coverage for the maintenance-VLAN substitution in common/junos/interfaces/
{access,lag}.j2 and leaf/junos/interfaces/lag.j2 - previously an untested,
hardcoded "VLAN900" literal, now a site-scoped ipam.VLAN tagged "maintenance"
(falling back to the "VLAN900" literal if no such VLAN exists for the site).
"""
import types

from netbox_mocks import FakeInterface, FakeVlan

ACCESS_TEMPLATE = "common/junos/interfaces/access.j2"
LAG_TEMPLATE = "common/junos/interfaces/lag.j2"

DEVICE = types.SimpleNamespace(role=types.SimpleNamespace(name="leaf"))
UNTAGGED_VLAN = types.SimpleNamespace(id=1, name="VLAN100", vid=100)


def _access_interface():
    return FakeInterface(
        name="ge-0/0/10",
        mtu=1500,
        tags=["maintenance"],
        mode="access",
        untagged_vlan=UNTAGGED_VLAN,
        id="ge-0/0/10",
    )


def test_access_mode_falls_back_to_literal_without_maintenance_vlan(render, rendered_lines):
    lines = rendered_lines(
        render(
            ACCESS_TEMPLATE,
            {"device": DEVICE, "device_interfaces": [_access_interface()], "maintenance_vlan": None},
        )
    )
    assert (
        "set interfaces ge-0/0/10 unit 0 family ethernet-switching interface-mode access vlan members VLAN900"
        in lines
    )


def test_access_mode_uses_site_scoped_maintenance_vlan(render, rendered_lines):
    lines = rendered_lines(
        render(
            ACCESS_TEMPLATE,
            {
                "device": DEVICE,
                "device_interfaces": [_access_interface()],
                "maintenance_vlan": FakeVlan("MAINT-SITE1", vid=999),
            },
        )
    )
    assert (
        "set interfaces ge-0/0/10 unit 0 family ethernet-switching interface-mode access vlan members MAINT-SITE1"
        in lines
    )
    assert "VLAN900" not in "\n".join(lines)


def _lag_interface():
    ae0 = FakeInterface(name="ae0", mtu=9192, type="lag", tags=["maintenance"], id="ae0")
    ae0.mode = "access"
    ae0.untagged_vlan = UNTAGGED_VLAN
    return ae0


def test_lag_access_mode_uses_site_scoped_maintenance_vlan(render, rendered_lines):
    lines = rendered_lines(
        render(
            LAG_TEMPLATE,
            {"device_interfaces": [_lag_interface()], "maintenance_vlan": FakeVlan("MAINT-SITE1", vid=999)},
        )
    )
    assert (
        "set interfaces ae0 unit 0 family ethernet-switching vlan members MAINT-SITE1" in lines
    )
