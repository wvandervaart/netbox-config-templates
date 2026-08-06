"""Builds a representative spine device + BGP fabric context for template tests."""
import types

from netbox_mocks import (
    FakeBGPAddress,
    FakeBGPSession,
    FakeCF,
    FakeDevice,
    FakeInterface,
    FakeIPAddress,
    FakePeerGroup,
    FakeQuerySet,
    fake_endpoint,
    fake_ipam,
    fake_netbox_bgp,
)

ASN = 65000


def build_spine_context(maintenance=False, llgr_off=False):
    # -- Interfaces -----------------------------------------------------
    # fabric/vtep/PRIMARY are set via both tag and custom field below,
    # matching real post-backfill NetBox state (migrate_tags_to_cf.py is
    # non-destructive - it adds the CF, it doesn't remove the tag). The
    # templates only read the CF now (tag fallback was removed once the
    # backfill was confirmed complete).
    loopback = FakeInterface(
        name="lo0.0",
        tags=["fabric"],
        cf={"FABRIC": True},
        ip_addresses=[
            FakeIPAddress(
                "10.255.0.1/32",
                tags=["PRIMARY"],
                cf={"PRIMARY": True},
            )
        ],
    )

    fabric_p2p = FakeInterface(
        name="et-0/0/0",
        mtu=9192,
        tags=["fabric"],
        cf={"FABRIC": True},
        connected_endpoints=[fake_endpoint("et-0/0/1", device_name="leaf01")],
    )
    fabric_p2p.ip_addresses = FakeQuerySet([FakeIPAddress("10.0.1.0/31", assigned_object=fabric_p2p)])

    ae0 = FakeInterface(
        name="ae0",
        type="lag",
        mtu=9192,
        tags=["fabric"],
        cf={"FABRIC": True},
        connected_endpoints=[fake_endpoint("ae1", device_name="leaf02")],
    )
    ae0.ip_addresses = FakeQuerySet([FakeIPAddress("10.0.1.2/31", assigned_object=ae0)])

    ae0_member = FakeInterface(
        name="et-0/0/2",
        type="100gbase-x-qsfp28",
        lag=ae0,
        connected_endpoints=[fake_endpoint("et-0/0/1", device_name="leaf02")],
    )

    mgmt = FakeInterface(
        name="em0",
        ip_addresses=[FakeIPAddress("192.0.2.10/24")],
    )

    disabled_port = FakeInterface(
        name="et-0/0/5",
        enabled=False,
        connected_endpoints=[fake_endpoint("et-0/0/9", device_name="leaf03")],
    )

    # ae0_member must precede ae0: common/junos/interfaces/lag.j2 builds its
    # lagspeed map in a single forward pass, same as real NetBox interface
    # ordering (physical member ports sort before their LAG bundle).
    interfaces = [loopback, fabric_p2p, ae0_member, ae0, mgmt, disabled_port]

    primary_ip = types.SimpleNamespace(
        address=loopback.ip_addresses[0].address, assigned_object=loopback
    )

    device_tags = ["maintenance"] if maintenance else []
    device = FakeDevice(
        name="spine01",
        role_name="spine",
        primary_ip=primary_ip,
        interfaces=interfaces,
        tags=device_tags,
        cf={"GNMI_MONITORED": True},
    )

    # -- BGP fabric: iBGP route-reflector session to a LEAF peer-group --
    pg_leaf = FakePeerGroup(
        id=1,
        name="LEAF",
        cf={"BFD": True, "PREFIX_LIMIT": 100},
    )
    session = FakeBGPSession(
        device=device,
        local_address=FakeBGPAddress("10.255.0.1/32"),
        remote_address=FakeBGPAddress("10.255.1.1/32"),
        local_as=ASN,
        remote_as=ASN,
        peer_group=pg_leaf,
        description="LEAF01",
        cf={"LLGR_OFF": True} if llgr_off else None,
    )

    netbox_bgp = fake_netbox_bgp(sessions=[session], peer_groups=[pg_leaf])

    # -- Misc context vars ------------------------------------------------
    users = types.SimpleNamespace(
        junos=[types.SimpleNamespace(root_auth="$6$fakehash")],
        exampleorg=[
            types.SimpleNamespace(
                _name="jdoe",
                systems=[types.SimpleNamespace(**{"_name": "junos", "class": "superuser"})],
                pubkey="ssh-ed25519 AAAAFAKE",
                pubkeytype="ssh-ed25519",
            )
        ],
    )
    utility = types.SimpleNamespace(
        timezone="UTC",
        ntp=["10.0.0.53"],
        dns=["10.0.0.53"],
        syslog=[types.SimpleNamespace(_name="10.0.0.60", port=514)],
    )

    context = {
        "device": device,
        "users": users,
        "utility": utility,
        "bgp": types.SimpleNamespace(asn=ASN),
        "ospf": types.SimpleNamespace(area="0.0.0.0"),
        "snmp": types.SimpleNamespace(contact="noc@example.com"),
        "sflow": {"collector": "10.0.0.99", "port": 6343, "interfaces": []},
        "netbox_bgp": netbox_bgp,
        "ipam": fake_ipam(),
    }
    return context