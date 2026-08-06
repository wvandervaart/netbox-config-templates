"""Targeted line-level tests for ds/junos/main.j2 against a real device
snapshot (tests/snapshots/mds1-610-11-nl1.json) captured from NetBox - see
tests/fetch_netbox_snapshot.py and tests/netbox_snapshot.py.
"""
from netbox_snapshot import load_context

TEMPLATE = "ds/junos/main.j2"
DEVICE = "mds1-610-11-nl1"


def test_renders_without_error(render):
    output = render(TEMPLATE, load_context(DEVICE))
    assert output.strip() != ""


def test_hostname(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "set system host-name mds1-610-11-nl1" in lines


def test_access_port_vlan_membership(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert (
        "set interfaces ge-0/0/0 unit 0 family ethernet-switching interface-mode access vlan members VLAN1201"
        in lines
    )


def test_trunk_port_vlan_membership(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert (
        "set interfaces ge-0/0/24 unit 0 family ethernet-switching interface-mode trunk vlan members [VLAN399]"
        in lines
    )


def test_vlan_definition_and_irb_binding(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert 'set vlans VLAN1201 description "point to point e4c dataminer" vlan-id 1201' in lines
    assert "set vlans VLAN320 l3-interface irb.320" in lines


def test_multicast_vrf_route_distinguisher(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "set routing-instances multicast-external instance-type vrf" in lines
    assert "set routing-instances multicast-external route-distinguisher 10.254.255.1:1000" in lines


def test_disabled_lldp_on_tagged_interface(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "set protocols lldp interface ge-0/0/1 disable" in lines


def test_dns_name_servers(render, rendered_lines):
    # ds/junos/main.j2 used to skip common/junos/system/dns.j2 entirely -
    # every other junos role configures DNS one way or another. Primary IP
    # sits on em0 in vrf mgmt_junos.
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "set system name-server 172.16.252.211 routing-instance mgmt_junos" in lines
    assert "set system name-server 172.16.252.211 source-address 172.18.254.11" in lines
    assert "set system name-server 172.16.252.212 routing-instance mgmt_junos" in lines
    assert "set system name-server 172.16.252.212 source-address 172.18.254.11" in lines


def test_pim_interface_mode_priority_and_hello(render, rendered_lines):
    # xe-0/0/39.398 (vrf multicast-internal) sets all three PIM custom fields
    # at once; ge-0/0/1/xe-0/0/6 (vrf multicast-external) set mode only.
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "set routing-instances multicast-external protocols pim interface ge-0/0/1 mode sparse" in lines
    assert "set routing-instances multicast-internal protocols pim interface xe-0/0/39.398 mode sparse" in lines
    assert "set routing-instances multicast-internal protocols pim interface xe-0/0/39.398 priority 5" in lines
    assert (
        "set routing-instances multicast-internal protocols pim interface xe-0/0/39.398 hello-interval 3"
        in lines
    )


def test_igmp_interface_disable_and_version(render, rendered_lines):
    # ge-0/0/1/xe-0/0/6 have IGMPIFACEDISABLE=True; xe-0/0/39.398 sets version 3.
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "set protocols igmp interface ge-0/0/1 disable" in lines
    assert "set protocols igmp interface xe-0/0/6 disable" in lines
    assert "set protocols igmp interface xe-0/0/39.398 version 3" in lines


def test_igmp_snooping_vlans(render, rendered_lines):
    # VLAN320/VLAN350/VLAN399/VLAN3399 all carry the IGMP-SNOOPING tag.
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "set protocols igmp-snooping vlan VLAN320" in lines
    assert "set protocols igmp-snooping vlan VLAN399" in lines


def test_ddos_protection_aggregate_limits(render, rendered_lines):
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "set system ddos-protection protocols arp aggregate bandwidth 2000" in lines
    assert "set system ddos-protection protocols arp aggregate burst 1000" in lines


def test_vstp_disabled_port_without_interface_all(render, rendered_lines):
    # ge-0/0/0 has the VSTP_OFF custom field set; VSTP_BRIDGEID is None and
    # VSTP_ALL_INT_ENABLED is False on this device, so no system-identifier
    # group line and no "interface all" line are expected.
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert "set groups APPLY-GROUP-VSTP protocols vstp vlan <*> bridge-priority 4k" in lines
    assert "set protocols vstp apply-groups APPLY-GROUP-VSTP" in lines
    assert "set protocols vstp interface all" not in lines
    assert "set protocols vstp interface ge-0/0/0 disable" in lines


def test_grpc_not_rendered_without_gnmi_monitored(render, rendered_lines):
    # mds1-610-11-nl1 doesn't have the GNMI_MONITORED custom field set
    # (migrated from the gnmi-monitored tag, which this device never carried).
    lines = rendered_lines(render(TEMPLATE, load_context(DEVICE)))
    assert not any("extension-service request-response grpc" in line for line in lines)
