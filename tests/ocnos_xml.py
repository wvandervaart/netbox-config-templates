"""Read helpers for the NETCONF XML router/ocnos/main.j2 renders.

Namespace URIs mirror common/ocnos/ns.j2 - keep the two in sync. The helpers
flatten the verbose YANG list/config nesting back into short tuples/strings so
test assertions stay as readable as the CLI line assertions they replaced.
"""
import xml.etree.ElementTree as ET

NETCONF = "urn:ietf:params:xml:ns:netconf:base:1.0"
_BASE = "http://www.ipinfusion.com/yang/ocnos/"
NS = {
    "nc": NETCONF,
    "sys": _BASE + "ipi-system",
    "user": _BASE + "ipi-user-management",
    "ntp": _BASE + "ipi-ntp",
    "dns": _BASE + "ipi-dns-client",
    "log": _BASE + "ipi-logging",
    "snmp": _BASE + "ipi-snmp",
    "ss": _BASE + "ipi-snmp-server",
    "sx": _BASE + "ipi-snmp-server-extended",
    "ssh": _BASE + "ipi-ssh",
    "ms": _BASE + "ipi-management-server",
    "ni": _BASE + "ipi-network-instance",
    "vrf": _BASE + "ipi-vrf",
    "bv": _BASE + "ipi-bgp-vrf",
    "if": _BASE + "ipi-interface",
    "ip": _BASE + "ipi-if-ip",
    "ext": _BASE + "ipi-if-extended",
    "eth": _BASE + "ipi-if-ethernet",
    "agg": _BASE + "ipi-if-aggregate",
    "br": _BASE + "ipi-bridge",
    "vlan": _BASE + "ipi-vlan",
    "pv": _BASE + "ipi-port-vlan",
    "vrrp": _BASE + "ipi-vrrp",
    "rib": _BASE + "ipi-rib",
    "ospf": _BASE + "ipi-ospf",
    "sflow": _BASE + "ipi-sflow",
    "sfi": _BASE + "ipi-sflow-interface",
    "bgp": _BASE + "ipi-bgp",
    "rmap": _BASE + "ipi-routemap",
    "pfx": _BASE + "ipi-prefix-list",
}


def parse(output):
    """Parse a rendered payload, keeping comments (fail-closed reasons live in them)."""
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    return ET.fromstring(output, parser=parser)


def local(tag):
    return tag.split("}", 1)[-1] if isinstance(tag, str) else tag


def find(el, path):
    return el.find(path, NS)


def findall(el, path):
    return el.findall(path, NS)


def text(el, path):
    found = el.find(path, NS)
    return found.text if found is not None else None


def texts(el, path):
    return [e.text for e in el.findall(path, NS)]


def comments(root):
    return [c.text.strip() for c in root.iter() if c.tag is ET.Comment]


# -- network-instances ------------------------------------------------------------

def network_instances(root, instance_type):
    return {
        text(n, "ni:instance-name"): n
        for n in findall(root, "ni:network-instances/ni:network-instance")
        if text(n, "ni:instance-type") == instance_type
    }


def vrf_summary(instance):
    """(rd, router-id, [(rt, direction)]) of a type-vrf network-instance."""
    bgp_vrf = find(instance, "vrf:vrf/bv:bgp-vrf")
    rts = [(text(rt, "bv:rt-rd-string"), text(rt, "bv:config/bv:direction"))
           for rt in findall(bgp_vrf, "bv:route-targets/bv:route-target")]
    return text(bgp_vrf, "bv:config/bv:rd-string"), text(instance, "vrf:vrf/vrf:config/vrf:router-id"), rts


def static_routes(instance):
    """[(prefix, gateway-or-interface)] of a network-instance, both families."""
    routes = []
    for r in findall(instance, "rib:static-routing/*/rib:static-route"):
        nh = text(r, "rib:next-hops-gateway/rib:next-hop-gateway/rib:gateway") or text(
            r, "rib:next-hops-interface/rib:next-hop-interface/rib:interface")
        routes.append((text(r, "rib:prefix"), nh))
    return routes


def bridge(root):
    return find(next(iter(network_instances(root, "l2ni").values())), "br:bridge")


# -- interfaces ---------------------------------------------------------------

def interfaces(root):
    return {text(i, "if:name"): i for i in findall(root, "if:interfaces/if:interface")}


def interface_names(root):
    return texts(root, "if:interfaces/if:interface/if:name")


def ipv4(intf):
    """[primary, secondary...] - the order the addresses are applied in."""
    primary = texts(intf, "ip:ipv4/ip:config/ip:primary-ip-addr")
    return primary + texts(intf, "ip:ipv4/ip:secondary-addresses/ip:ip-address")


def ipv6(intf):
    return texts(intf, "ip:ipv6/ip:addresses/ip:ipv6-address")


def config_children(intf):
    """Local names of the interface's <config> children, in document order."""
    return [local(c.tag) for c in find(intf, "if:config")]


def dot1q(intf):
    return text(intf, "ext:extended/ext:subinterface-encapsulation/ext:single-tag-vlan-matches/"
                      "ext:single-tag-vlan-match/ext:config/ext:outer-vlan-id")


def lag_member(intf):
    """(aggregate-id, lacp-mode) or None."""
    cfg = find(intf, "agg:member-aggregation/agg:config")
    return None if cfg is None else (text(cfg, "agg:aggregate-id"), text(cfg, "agg:lacp-mode"))


def switchport(intf):
    """{mode, vlan, native, allowed} of the port-vlan config, or None."""
    sv = find(intf, "pv:port-vlan/pv:switched-vlans/pv:switched-vlan")
    if sv is None:
        return None
    return {
        "mode": text(sv, "pv:config/pv:interface-mode"),
        "vlan": text(sv, "pv:vlans/pv:config/pv:vlan-id"),
        "native": text(sv, "pv:vlans/pv:config/pv:native-vlan-id"),
        "allowed": text(sv, "pv:allowed-vlan/pv:config/pv:allowed-vlan-id"),
    }


# -- prefix-lists / route-maps / as-path ----------------------------------------

def prefix_lists(root):
    """{(afi, name): ["seq N action prefix[ ge X][ le Y]", ...]} - the CLI spelling."""
    result = {}
    for pl in findall(root, "pfx:prefixes/pfx:prefix"):
        afi = "ipv6" if text(pl, "pfx:prefix-list-type") == "ipv6" else "ipv4"
        key = (afi, text(pl, "pfx:prefix-list-name"))
        assert key not in result, f"duplicate prefix-list {key}"
        lines = []
        for e in findall(pl, "pfx:prefix-entries/pfx:prefix-entry"):
            c = find(e, f"pfx:{afi}/pfx:entry/pfx:config")
            prefix = text(c, "pfx:ipv6-prefix-addr" if afi == "ipv6" else "pfx:prefix-addr")
            line = f"seq {text(e, 'pfx:sequence-id')} {text(c, 'pfx:action')} {prefix}"
            for bound, leaf in (("ge", "minimum-prefix-length-match"), ("le", "maximum-prefix-length-match")):
                if text(c, f"pfx:{leaf}") is not None:
                    line += f" {bound} {text(c, f'pfx:{leaf}')}"
            lines.append(line)
        result[key] = lines
    return result


def route_maps(root):
    """{(name, seq): (action, [match...], [set...])} with seq as int. Matches read
    "ipv4-prefix-list X" / "ipv6-prefix-list X" / "as-path X" / "community X"; sets
    "<leaf> <value>", "ipv4-next-hop X", "community <values> [flags] [additive]"."""
    result = {}
    for rm in findall(root, "rmap:routemaps/rmap:routemap"):
        key = (text(rm, "rmap:routemap-name"), int(text(rm, "rmap:sequence-id")))
        assert key not in result, f"duplicate route-map entry {key}"
        mc = find(rm, "rmap:match-condition")
        matches = []
        if mc is not None:
            matches += [f"as-path {v}" for v in texts(mc, "rmap:config/rmap:as-path-name")]
            matches += [f"community {v}" for v in texts(mc, "rmap:communities/rmap:community/rmap:community-identifier")]
            matches += [f"ipv4-prefix-list {v}" for v in texts(mc, "rmap:ipv4/rmap:config/rmap:ip-prefix-list-name")]
            matches += [f"ipv6-prefix-list {v}" for v in texts(mc, "rmap:ipv6/rmap:config/rmap:ipv6-prefix-list-name")]
        sa = find(rm, "rmap:set-action")
        sets = []
        if sa is not None:
            sets += [f"{local(c.tag)} {c.text}" for c in findall(sa, "rmap:config/*")]
            sets += [f"ipv4-next-hop {v}" for v in texts(sa, "rmap:ipv4/rmap:config/rmap:ip-nexthop-address")]
            sets += [f"ipv6-next-hop {v}" for v in texts(sa, "rmap:ipv6/rmap:config/rmap:ipv6-nexthop-address")]
            cc = find(sa, "rmap:communities/rmap:config")
            if cc is not None:
                parts = texts(cc, "rmap:community-number")
                parts += [local(c.tag).replace("enable-", "") for c in cc if local(c.tag).startswith("enable-")]
                parts += ["additive"] if find(cc, "rmap:additive-set") is not None else []
                sets.append("community " + " ".join(parts))
        result[key] = (text(rm, "rmap:config/rmap:action"), matches, sets)
    return result


def aspath_lists(root):
    """{name: [regex, ...]} in document order."""
    result = {}
    for al in findall(root, "bgp:bgp/bgp:global/bgp:as-path-access-lists/bgp:as-path-access-list"):
        result.setdefault(text(al, "bgp:access-list-name"), []).append(text(al, "bgp:access-list-regular-expression"))
    return result


# -- bgp ------------------------------------------------------------------------

def bgp_instance(root):
    return find(root, "bgp:bgp/bgp:bgp-instances/bgp:bgp-instance")


def settings(el):
    """Flattened BGP settings of a peer-group / peer / address-family element:
    its <config> leaves ("leaf value" / "leaf") plus "ebgp-max-path N",
    "maximum-prefix N", "route-map-in|out X" and "redistribute P route-map X"."""
    out = [f"{local(c.tag)} {c.text}".strip() if c.text and c.text.strip() else local(c.tag)
           for c in findall(el, "bgp:config/*")]
    out += [f"{local(c.tag)} {c.text}" for c in findall(el, "bgp:maximum-paths/bgp:config/*")]
    out += [f"maximum-prefix {v}" for v in texts(el, "bgp:maximum-prefixes/bgp:maximum-prefix/bgp:prefix-count")]
    out += [f"route-map-{text(f, 'bgp:route-map-direction')} {text(f, 'bgp:config/bgp:route-map-name')}"
            for f in findall(el, "bgp:route-map-filters/bgp:route-map-filter")]
    out += [f"redistribute {text(r, 'bgp:protocol-type')} route-map {text(r, 'bgp:config/bgp:redist-route-map-name')}"
            for r in findall(el, "bgp:route-redistribute-lists/bgp:route-redistribute-list")]
    return out


def af_config(el, afi):
    """settings() of el's address-family `afi` (ipv4/ipv6 unicast), or None."""
    for af in findall(el, "bgp:address-families/bgp:address-family"):
        if text(af, "bgp:afi") == afi:
            return settings(af)
    return None


def bgp_vrf(root, name, afi):
    """The address-family-vrf element for (afi, unicast, vrf name)."""
    for v in findall(bgp_instance(root), "bgp:address-family-vrfs/bgp:address-family-vrf"):
        if text(v, "bgp:vrf-name") == name and text(v, "bgp:afi") == afi:
            return v
    raise KeyError((name, afi))


def peer_groups(el):
    return {text(p, "bgp:peer-group-tag"): p for p in findall(el, "bgp:peer-groups/bgp:peer-group")}


def peers(el):
    """Global peers of a bgp-instance, or vrf-peers of an address-family-vrf."""
    found = findall(el, "bgp:peers/bgp:peer") + findall(el, "bgp:vrf-peers/bgp:vrf-peer")
    return {text(p, "bgp:peer-address"): p for p in found}
