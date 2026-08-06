"""Coverage for common/{junos,eos}/bgp/{prefix-list,policy,aspath-list}.j2.

These partials were previously untested (see netbox_mocks.py's FakePolicy
docstring - `.rules` was always empty in every existing fixture, so the
policy-rule-walking logic in these five files never actually ran under test).
Exercises: dedup of a prefix-list referenced from multiple rules/policies,
the match_custom "policy" side-effect that pulls in a linked RoutingPolicy,
the junos-only ALWAYS_ADD prefix-list and routing-policy scans, and AS-path
list rendering.
"""
import types

from netbox_mocks import (
    FakeASPathList,
    FakeASPathListRule,
    FakeBGPAddress,
    FakeBGPSession,
    FakeDevice,
    FakePeerGroup,
    FakePolicy,
    FakePrefixList,
    FakePrefixListRule,
    FakeRoutingPolicyRule,
    fake_netbox_bgp,
)


def _build_policy_fixture():
    """A CUSTOMER-V4 prefix-list and AS-CUSTOMER as-path-list, each referenced
    from two different rules (one of them via a match_custom-linked policy),
    plus a junos-only ALWAYS_ADD-tagged BOGONS prefix-list."""
    customer_v4 = FakePrefixList(id=1, name="CUSTOMER-V4")
    customer_v4_rules = [
        FakePrefixListRule(customer_v4, index=1, prefix_custom="10.0.0.0/8"),
        FakePrefixListRule(customer_v4, index=2, prefix_custom="172.16.0.0/12"),
    ]
    bogons = FakePrefixList(id=2, name="BOGONS", tags=["ALWAYS_ADD"])
    bogons_rules = [FakePrefixListRule(bogons, index=1, prefix_custom="0.0.0.0/8")]

    as_customer = FakeASPathList(id=1, name="AS-CUSTOMER")
    as_customer_rules = [
        FakeASPathListRule(as_customer, description="cust1", pattern="^65001"),
        FakeASPathListRule(as_customer, description="cust2", pattern="^65002"),
    ]

    linked_policy = FakePolicy("LINKED-POLICY")
    linked_policy.rules = type(linked_policy.rules)(
        [
            FakeRoutingPolicyRule(
                routing_policy=linked_policy,
                index=10,
                action="permit",
                match_ip_address=[customer_v4],
                match_aspath_list=[as_customer],
            )
        ]
    )

    always_add_policy = FakePolicy("ALWAYS-ADD-POLICY", tags=["ALWAYS_ADD"])
    always_add_policy.rules = type(always_add_policy.rules)(
        [
            FakeRoutingPolicyRule(
                routing_policy=always_add_policy,
                index=10,
                action="permit",
                match_ip_address=[customer_v4],
            )
        ]
    )

    export_policy = FakePolicy("EXPORT-TO-LEAF")
    export_policy.rules = type(export_policy.rules)(
        [
            FakeRoutingPolicyRule(
                routing_policy=export_policy,
                index=10,
                action="permit",
                match_ip_address=[customer_v4],
                match_custom=[{"name": "policy", "value": "LINKED-POLICY"}],
            ),
            FakeRoutingPolicyRule(
                routing_policy=export_policy,
                index=20,
                action="deny",
                match_ip_address=[customer_v4],
            ),
        ]
    )

    device = FakeDevice(name="test-device", role_name="spine")
    peer_group = FakePeerGroup(id=1, name="PG")
    session = FakeBGPSession(
        device=device,
        local_address=FakeBGPAddress("10.255.0.1/32"),
        remote_address=FakeBGPAddress("10.255.0.2/32"),
        local_as=65000,
        remote_as=65000,
        peer_group=peer_group,
        export_policies=[export_policy],
    )

    netbox_bgp = fake_netbox_bgp(
        sessions=[session],
        peer_groups=[peer_group],
        routing_policies=[export_policy, linked_policy, always_add_policy],
        prefix_lists=[customer_v4, bogons],
        prefix_list_rules=customer_v4_rules + bogons_rules,
        aspath_list_rules=as_customer_rules,
    )

    return device, session, netbox_bgp


def _junos_context():
    device, session, netbox_bgp = _build_policy_fixture()
    return {
        "device": device,
        "device_interfaces": [],
        "bgp_sessions": [session],
        "netbox_bgp": netbox_bgp,
    }


def _eos_context():
    device, session, netbox_bgp = _build_policy_fixture()
    return {
        "device": device,
        "bgp_sessions": [session],
        "netbox_bgp": netbox_bgp,
    }


def test_junos_prefix_list_dedup_and_always_add(render):
    output = render("common/junos/bgp/prefix-list.j2", _junos_context())
    assert output.count("set policy-options prefix-list CUSTOMER-V4 10.0.0.0/8") == 1
    assert output.count("set policy-options prefix-list CUSTOMER-V4 172.16.0.0/12") == 1
    assert "set policy-options prefix-list BOGONS 0.0.0.0/8" in output


def test_junos_policy_statements_and_linked_policy(render, rendered_lines):
    lines = rendered_lines(render("common/junos/bgp/policy.j2", _junos_context()))
    assert "set policy-options policy-statement EXPORT-TO-LEAF term 10 from prefix-list CUSTOMER-V4" in lines
    assert "set policy-options policy-statement EXPORT-TO-LEAF term 10 from policy LINKED-POLICY" in lines
    assert "set policy-options policy-statement EXPORT-TO-LEAF term 10 then accept" in lines
    assert "set policy-options policy-statement EXPORT-TO-LEAF term 20 then reject" in lines
    # LINKED-POLICY is only reachable via the match_custom side-effect above -
    # this is the RoutingPolicy.objects.get(name=...) N+1 lookup being exercised.
    assert "set policy-options policy-statement LINKED-POLICY term 10 from prefix-list CUSTOMER-V4" in lines
    assert "set policy-options policy-statement LINKED-POLICY term 10 from as-path-group AS-CUSTOMER" in lines
    assert "set policy-options policy-statement LINKED-POLICY term 10 then accept" in lines


def test_junos_policy_always_add_tag_included(render, rendered_lines):
    # ALWAYS-ADD-POLICY isn't referenced by any session or peer-group - only
    # its ALWAYS_ADD tag pulls it in (policy.j2's RoutingPolicy scan).
    lines = rendered_lines(render("common/junos/bgp/policy.j2", _junos_context()))
    assert "set policy-options policy-statement ALWAYS-ADD-POLICY term 10 from prefix-list CUSTOMER-V4" in lines
    assert "set policy-options policy-statement ALWAYS-ADD-POLICY term 10 then accept" in lines


def test_junos_aspath_list_rendering(render):
    output = render("common/junos/bgp/aspath-list.j2", _junos_context())
    assert "set policy-options as-path-group AS-CUSTOMER as-path cust1 ^65001" in output
    assert "set policy-options as-path-group AS-CUSTOMER as-path cust2 ^65002" in output


def test_eos_prefix_list_dedup(render):
    output = render("common/eos/bgp/prefix-list.j2", _eos_context())
    assert "ip prefix-list CUSTOMER-V4" in output
    assert output.count("seq 2 permit 10.0.0.0/8") == 1
    assert output.count("seq 3 permit 172.16.0.0/12") == 1


def test_eos_policy_route_maps_and_linked_policy(render, rendered_lines):
    lines = rendered_lines(render("common/eos/bgp/policy.j2", _eos_context()))
    assert "route-map EXPORT-TO-LEAF permit 11" in lines
    assert "match ip address prefix-list CUSTOMER-V4" in lines
    assert "route-map EXPORT-TO-LEAF deny 21" in lines
    # LINKED-POLICY only reachable via the match_custom "policy" side-effect.
    assert "route-map LINKED-POLICY permit 11" in lines
