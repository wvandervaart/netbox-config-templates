"""Builds representative device contexts for template tests: a spine device + BGP
fabric (spine/junos), and an OcNOS edge router (router/ocnos)."""
import types

from netbox_mocks import (
    FakeBGPAddress,
    FakeBGPSession,
    FakeCF,
    FakeDevice,
    FakeInterface,
    FakeIPAddress,
    FakePeerGroup,
    FakePolicy,
    FakePrefixList,
    FakePrefixListRule,
    FakeQuerySet,
    FakeRoutingPolicyRule,
    FakeVlan,
    FakeVRF,
    fake_endpoint,
    fake_link_peer,
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

OCNOS_ASN = 65100


def build_ocnos_router_context():
    """An OcNOS SP edge router - hand-built until a real OcNOS device exists in
    NetBox to snapshot (then switch tests/test_router_ocnos.py to load_context())."""
    rt = types.SimpleNamespace
    vrf_internet = FakeVRF(
        name="internet",
        rd=100,
        import_targets=[rt(name="65100:100"), rt(name="65100:200")],
        export_targets=[rt(name="65100:100"), rt(name="65100:300")],
    )

    # -- Interfaces -----------------------------------------------------
    mgmt = FakeInterface(
        name="eth0",
        ip_addresses=[FakeIPAddress("192.0.2.20/24")],
        connected_endpoints=[fake_endpoint("ge-0/0/10", device_name="mgmt-sw01")],
    )
    lo = FakeInterface(name="loopback1", ip_addresses=[FakeIPAddress("10.255.0.20/32")])
    lo_internet = FakeInterface(
        name="loopback2",
        vrf=vrf_internet,
        ip_addresses=[FakeIPAddress("203.0.113.254/32", role="anycast"), FakeIPAddress("203.0.113.1/32")],
    )
    fabric = FakeInterface(
        name="ce0",
        mtu=9216,
        cf={"FABRIC": True},
        connected_endpoints=[fake_endpoint("Ethernet1/1", device_name="spine01")],
    )
    fabric.ip_addresses = FakeQuerySet([FakeIPAddress("10.0.2.1/31", assigned_object=fabric)])

    # physical LAG members sort before their bundle, like real NetBox ordering
    po1 = FakeInterface(name="po1", type="lag", mtu=9216, description="core")
    po1.ip_addresses = FakeQuerySet([FakeIPAddress("10.0.3.0/31", assigned_object=po1)])
    member1 = FakeInterface(
        name="xe1",
        type="25gbase-x-sfp28",
        lag=po1,
        cf={"FEC": ["none"]},
        connected_endpoints=[fake_endpoint("et-0/0/1", device_name="core01")],
    )
    member2 = FakeInterface(
        name="xe2",
        type="25gbase-x-sfp28",
        lag=po1,
        connected_endpoints=[fake_endpoint("et-0/0/2", device_name="core01")],
        link_peers=[fake_link_peer("CBL-0042")],
    )

    # transit sub-interface in vrf internet, with a VRRP gateway
    transit = FakeInterface(
        name="xe3.100",
        vrf=vrf_internet,
        description="transit",
        connected_endpoints=[fake_endpoint("xe-0/0/3", device_name="transit-rtr")],
    )
    transit.ip_addresses = FakeQuerySet(
        [
            FakeIPAddress("198.51.100.2/29", assigned_object=transit),
            FakeIPAddress("198.51.100.9/29", assigned_object=transit),
            FakeIPAddress("2001:db8:100::2/64", family=6, assigned_object=transit),
            FakeIPAddress(
                "198.51.100.1/29",
                role="vrrp",
                assigned_object=transit,
                cf={"PRIMARY": True, "VRRP_GROUP": 10},
            ),
        ]
    )
    disabled = FakeInterface(name="xe4", enabled=False, ip_addresses=[FakeIPAddress("10.9.9.1/30")])

    # -- L2: bridge 1 switchports + a vlan1.N SVI ------------------------------
    vlan10 = FakeVlan("VLAN10", vid=10)
    vlan20 = FakeVlan("VLAN20", vid=20)
    vlan30 = FakeVlan("VLAN30", vid=30)
    vlan99 = FakeVlan("VLAN99", vid=99)
    access = FakeInterface(
        name="xe5",
        mode="access",
        untagged_vlan=vlan10,
        connected_endpoints=[fake_endpoint("eno1", device_name="server01")],
    )
    trunk = FakeInterface(name="xe6", mode="tagged", tagged_vlans=[vlan20, vlan10], untagged_vlan=vlan30)
    po2 = FakeInterface(name="po2", type="lag", mode="tagged", tagged_vlans=[vlan20], description="to-sw01")
    po2_member = FakeInterface(name="xe7", type="25gbase-x-sfp28", lag=po2)
    disabled_trunk = FakeInterface(name="xe8", enabled=False, mode="tagged", tagged_vlans=[vlan99])
    svi = FakeInterface(name="vlan1.10", mode="access", untagged_vlan=vlan10, vrf=vrf_internet)
    svi.ip_addresses = FakeQuerySet([FakeIPAddress("10.10.0.1/24", assigned_object=svi)])

    interfaces = [
        mgmt, lo, lo_internet, fabric, member1, member2, po1, transit, disabled,
        access, trunk, po2_member, po2, disabled_trunk, svi,
    ]

    static_routes = [
        types.SimpleNamespace(prefix="0.0.0.0/0", next_hop="198.51.100.6", vrf=vrf_internet, cf=FakeCF()),
        types.SimpleNamespace(prefix="10.99.0.0/16", next_hop="255.255.255.255", vrf=None, cf=FakeCF()),
    ]

    primary_ip = types.SimpleNamespace(address=lo.ip_addresses[0].address, assigned_object=lo)
    device = FakeDevice(
        name="r1-ocnos-nl1",
        role_name="router",
        primary_ip=primary_ip,
        interfaces=interfaces,
        static_routes=static_routes,
        device_type_model="UfiSpace S9600-32X",
        config_template_name="ocnos-router-config",
    )

    # -- Routing policy ---------------------------------------------------
    pl_own = FakePrefixList(id=1, name="PL_OWN_V4")
    pl_own_rules = [FakePrefixListRule(pl_own, 0, "198.18.1.139/24", le=32, ge=24)]
    pol_export = FakePolicy("POL_TRANSIT_EXPORT")
    pol_export.rules = FakeQuerySet(
        [
            FakeRoutingPolicyRule(
                pol_export,
                0,
                action="permit",
                match_ip_address=[pl_own],
                set_actions=[{"name": "as-path-prepend", "action": "default"}],
            ),
            FakeRoutingPolicyRule(pol_export, 1, action="deny"),
        ]
    )
    pol_import = FakePolicy("POL_TRANSIT_IMPORT")
    pol_import.rules = FakeQuerySet(
        [
            FakeRoutingPolicyRule(
                pol_import,
                0,
                action="permit",
                match_custom=[{"name": "route-filter", "prefix": "0.0.0.0/0", "match-type": "exact"}],
                set_actions={"name": "local-preference", "action": "200"},
            ),
        ]
    )
    device.cf._fields["DEFAULT_AS_PREPEND"] = 2

    # -- BGP ----------------------------------------------------------------
    pg_ibgp = FakePeerGroup(id=10, name="IBGP", cf={"BGP_NEXTHOP": "self", "AUTH_KEY": "ibgp-secret"})
    pg_transit = FakePeerGroup(
        id=11,
        name="TRANSIT",
        cf={"PREFIX_LIMIT": 1500000},
        export_policies=[pol_export],
        import_policies=[pol_import],
    )
    sessions = [
        FakeBGPSession(
            device=device,
            local_address=FakeBGPAddress("10.255.0.20/32"),
            remote_address=FakeBGPAddress("10.255.0.21/32"),
            local_as=OCNOS_ASN,
            remote_as=OCNOS_ASN,
            peer_group=pg_ibgp,
            description="r2-ocnos-nl1",
        ),
        FakeBGPSession(
            device=device,
            local_address=FakeBGPAddress("198.51.100.2/29", vrf=vrf_internet),
            remote_address=FakeBGPAddress("198.51.100.6/29", vrf=vrf_internet),
            local_as=OCNOS_ASN,
            remote_as=64500,
            peer_group=pg_transit,
            description="TRANSIT_A",
        ),
        FakeBGPSession(
            device=device,
            local_address=FakeBGPAddress("2001:db8:100::2/64", vrf=vrf_internet, family=6),
            remote_address=FakeBGPAddress("2001:db8:100::6/64", vrf=vrf_internet, family=6),
            local_as=OCNOS_ASN,
            remote_as=64500,
            peer_group=pg_transit,
            description="TRANSIT_A_V6",
        ),
    ]
    netbox_bgp = fake_netbox_bgp(
        sessions=sessions,
        peer_groups=[pg_ibgp, pg_transit],
        routing_policies=[pol_export, pol_import],
        prefix_lists=[pl_own],
        prefix_list_rules=pl_own_rules,
    )

    # -- Config context ------------------------------------------------------
    users = types.SimpleNamespace(
        exampleorg=[
            types.SimpleNamespace(
                _name="jdoe",
                ocnos_pw="0xFAKEHASH",
                systems=[types.SimpleNamespace(**{"_name": "ocnos", "class": "network-admin"})],
            ),
            # no ocnos system entry -> must not be rendered
            types.SimpleNamespace(
                _name="junosonly",
                systems=[types.SimpleNamespace(**{"_name": "junos", "class": "super-user"})],
            ),
        ],
    )
    utility = types.SimpleNamespace(
        timezone="Europe/Amsterdam",
        ntp=["192.0.2.123"],
        dns=["192.0.2.53"],
        syslog=[
            types.SimpleNamespace(_name="192.0.2.80", port="1514"),
            types.SimpleNamespace(_name="192.0.2.81", port="514"),
        ],
    )
    return {
        "device": device,
        "users": users,
        "utility": utility,
        "bgp": types.SimpleNamespace(asn=OCNOS_ASN),
        "ospf": {"area": "0.0.0.0"},
        "snmp": {"community": [{"name": "public-ro", "clients": [{"address": "198.18.1.101/24"}]}]},
        "sflow": {"collector": "192.0.2.99", "port": "6343", "interfaces": ["xe3"]},
        "manual_config": ["ip domain-name example.net"],
        "netbox_bgp": netbox_bgp,
        "ipam": fake_ipam(),
    }
