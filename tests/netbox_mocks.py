"""Lightweight stand-ins for the NetBox/netbox-bgp object surface these Jinja2
templates actually touch (`.all()`/`.filter()`/`.cf`/`.tags.names()`/...).

Not a NetBox client and not exhaustive - only implements what the spine/junos
templates (and the common/junos partials they include) read, so it stays
readable rather than trying to model the whole data model.
"""
import types


def _key(value):
    """Resolve an object to something comparable for filter()/exclude().

    Lets `.filter(vrf=vrf_obj)` (compare identity) and `.filter(lag=iface.id)`
    (compare an object's .id against a bare id) both work.
    """
    return getattr(value, "id", value)


def _matches(obj, kwargs):
    for key, expected in kwargs.items():
        if "__" in key:
            field, lookup = key.split("__", 1)
        else:
            field, lookup = key, "exact"
        actual = getattr(obj, field, None)
        if lookup == "exact":
            if _key(actual) != _key(expected):
                return False
        elif lookup == "contains":
            if expected not in (actual or ""):
                return False
        elif lookup == "in":
            if _key(actual) not in [_key(v) for v in expected]:
                return False
        elif lookup == "name":
            # e.g. tags__name="maintenance" - membership on a FakeTags-like
            # relation exposing .names(), rather than a scalar field compare.
            if hasattr(actual, "names"):
                if expected not in actual.names():
                    return False
            elif getattr(actual, "name", None) != expected:
                return False
        else:
            raise NotImplementedError(f"unsupported lookup: {lookup}")
    return True


class FakeQuerySet(list):
    """A list that understands the tiny slice of the Django ORM API used here."""

    def all(self):
        return self

    def filter(self, **kwargs):
        return FakeQuerySet(o for o in self if _matches(o, kwargs))

    def exclude(self, **kwargs):
        return FakeQuerySet(o for o in self if not _matches(o, kwargs))

    def get(self, **kwargs):
        matches = [o for o in self if _matches(o, kwargs)]
        if not matches:
            raise LookupError(f"no object matching {kwargs}")
        return matches[0]

    def first(self):
        return self[0] if self else None

    def select_related(self, *args, **kwargs):
        return self

    def prefetch_related(self, *args, **kwargs):
        return self


class FakeManager:
    """Mimics `SomeModel.objects` for netbox_bgp.* lookalikes."""

    def __init__(self, items=None):
        self.objects = FakeQuerySet(items or [])


class FakePolicy:
    """A named routing-policy reference.

    Templates use these two ways: interpolated directly (`{{ vni.cf.EXPORT_POLICY }}`)
    and collected into a `pols` list that's later deduped with `not in` and
    walked via `.rules.all()`. Equality is by name (like a Django model's
    pk-based equality) so the same policy referenced from two places - e.g. a
    peer-group's export_policies and a VRF's VNI export policy - dedupes
    correctly. `.rules` is always empty here: we don't snapshot policy rule
    bodies, only which policies are referenced.
    """

    def __init__(self, name, rules=None, tags=None):
        self.name = name
        self.rules = FakeQuerySet(rules or [])
        self.tags = FakeTags(tags)

    def __str__(self):
        return self.name

    def __eq__(self, other):
        return isinstance(other, FakePolicy) and self.name == other.name

    def __hash__(self):
        return hash(self.name)


class FakeRoutingPolicyRule:
    """A `netbox_bgp.RoutingPolicyRule` lookalike (a single term of a RoutingPolicy)."""

    def __init__(
        self,
        routing_policy,
        index,
        action="permit",
        match_ip_address=None,
        match_ipv6_address=None,
        match_community=None,
        match_aspath_list=None,
        match_custom=None,
        set_actions=None,
    ):
        self.routing_policy = routing_policy
        self.index = index
        self.action = action
        self.match_ip_address = FakeQuerySet(match_ip_address or [])
        self.match_ipv6_address = FakeQuerySet(match_ipv6_address or [])
        self.match_community = FakeQuerySet(match_community or [])
        self.match_aspath_list = FakeQuerySet(match_aspath_list or [])
        self.match_custom = match_custom
        self.set_actions = set_actions


class FakePrefixList:
    """A `netbox_bgp.PrefixList` lookalike."""

    def __init__(self, id, name, tags=None):
        self.id = id
        self.name = name
        self.tags = FakeTags(tags)

    def __str__(self):
        return self.name

    def __eq__(self, other):
        return isinstance(other, FakePrefixList) and self.id == other.id

    def __hash__(self):
        return hash(self.id)


class FakePrefixListRule:
    """A `netbox_bgp.PrefixListRule` lookalike."""

    def __init__(self, prefix_list, index, prefix_custom, le=None, ge=None):
        self.prefix_list = prefix_list
        self.index = index
        self.prefix_custom = prefix_custom
        self.le = le
        self.ge = ge


class FakeASPathList:
    """A `netbox_bgp.ASPathList` lookalike."""

    def __init__(self, id, name):
        self.id = id
        self.name = name

    def __str__(self):
        return self.name

    def __eq__(self, other):
        return isinstance(other, FakeASPathList) and self.id == other.id

    def __hash__(self):
        return hash(self.id)


class FakeASPathListRule:
    """A `netbox_bgp.ASPathListRule` lookalike."""

    def __init__(self, aspath_list, description, pattern):
        self.aspath_list = aspath_list
        self.description = description
        self.pattern = pattern


class FakeTag:
    def __init__(self, name, slug=None):
        self.name = name
        self.slug = slug or name.lower()


class FakeTags:
    def __init__(self, tags=None):
        self._tags = [t if isinstance(t, FakeTag) else FakeTag(t) for t in (tags or [])]

    def names(self):
        return [t.name for t in self._tags]

    def all(self):
        return self._tags


class FakeCF:
    """Custom-field bag: supports `.get()`, `.FIELD` attribute access, and `'X' in cf`."""

    def __init__(self, **fields):
        self._fields = fields

    def get(self, key, default=None):
        return self._fields.get(key, default)

    def __contains__(self, key):
        return key in self._fields

    def __getattr__(self, key):
        # Only reached for missing attributes; mimics NetBox returning None
        # for a custom field that isn't set on this particular object.
        return self._fields.get(key)


class IPValue:
    """Mimics a NetBox IPAddress.address (netaddr-ish): str() is 'a.b.c.d/nn', .ip is 'a.b.c.d'."""

    def __init__(self, cidr):
        self._cidr = cidr
        self.ip = cidr.split("/")[0]

    def __str__(self):
        return self._cidr


class FakeIPAddress:
    def __init__(
        self, cidr, family=4, status="active", tags=None, assigned_object=None, vrf=None, cf=None
    ):
        self.address = IPValue(cidr)
        self.family = family
        self.status = status
        self.tags = FakeTags(tags)
        self.assigned_object = assigned_object
        self.vrf = vrf
        self.cf = FakeCF(**(cf or {}))


class FakeInterface:
    def __init__(
        self,
        name,
        enabled=True,
        mtu=None,
        type=None,
        tags=None,
        lag=None,
        mode=None,
        untagged_vlan=None,
        tagged_vlans=None,
        qinq_svlan=None,
        vrf=None,
        cf=None,
        ip_addresses=None,
        connected_endpoints=None,
        link_peers=None,
        description="",
        parent=None,
        mac_address=None,
        id=None,
    ):
        self.name = name
        self.enabled = enabled
        self.mtu = mtu
        self.type = type
        self.tags = FakeTags(tags)
        self.lag = lag
        self.mode = mode
        self.untagged_vlan = untagged_vlan
        self.tagged_vlans = FakeQuerySet(tagged_vlans or [])
        self.qinq_svlan = qinq_svlan
        self.vrf = vrf
        self.cf = FakeCF(**(cf or {}))
        self.ip_addresses = FakeQuerySet(ip_addresses or [])
        self.connected_endpoints = connected_endpoints or []
        self.link_peers = link_peers or []
        self.description = description
        self.parent = parent
        self.mac_address = mac_address
        self.id = id or name


def fake_endpoint(name, device_name=None):
    ep = types.SimpleNamespace(name=name)
    if device_name is not None:
        ep.device = types.SimpleNamespace(name=device_name)
    return ep


def fake_link_peer(cable_label=None):
    peer = types.SimpleNamespace()
    if cable_label:
        peer.cable = types.SimpleNamespace(label=cable_label)
    return peer


class FakeVRF:
    def __init__(self, name, rd=1, cf=None, import_targets=None, export_targets=None):
        self.name = name
        self.rd = rd
        self.cf = FakeCF(**(cf or {}))
        self.import_targets = FakeQuerySet(import_targets or [])
        self.export_targets = FakeQuerySet(export_targets or [])
        self.id = name


class FakeVlan:
    """A standalone ipam.VLAN lookalike, queryable by site/tags - distinct from
    the tagged_vlan/untagged_vlan references built inline in netbox_snapshot.py,
    which only need enough surface to render, not to be looked up."""

    def __init__(self, name, vid=None, site=None, tags=None, description="", qinq_svlan=None):
        self.name = name
        self.vid = vid
        self.site = site
        self.tags = FakeTags(tags)
        self.description = description
        self.id = name
        # Plain NetBox id of the S-VLAN this (customer) VLAN belongs to, or
        # None - not a FakeVlan reference, since _matches()'s _key() already
        # unwraps `.id` on either side of a filter(qinq_svlan=...) comparison.
        self.qinq_svlan = qinq_svlan


class FakeDevice:
    def __init__(
        self,
        name,
        role_name,
        primary_ip=None,
        interfaces=None,
        tags=None,
        cf=None,
        region_slug="region1",
        site_slug="site1",
        location_slug="loc1",
        rack_name="rack1",
        static_routes=None,
        device_type_model="QFX5120-32C",
        config_template_name="junos-spine-config",
    ):
        self.name = name
        self.role = types.SimpleNamespace(name=role_name)
        self.tags = FakeTags(tags)
        self.interfaces = FakeQuerySet(interfaces or [])
        self.primary_ip = primary_ip
        self.cf = FakeCF(**(cf or {}))
        self.site = types.SimpleNamespace(
            slug=site_slug, region=types.SimpleNamespace(slug=region_slug)
        )
        self.location = types.SimpleNamespace(slug=location_slug)
        self.rack = types.SimpleNamespace(name=rack_name)
        self.static_routes = FakeQuerySet(static_routes or [])
        self.device_type = types.SimpleNamespace(model=device_type_model)
        self.config_template = types.SimpleNamespace(name=config_template_name)


class FakePeerGroup:
    def __init__(self, id, name, cf=None, export_policies=None, import_policies=None):
        self.id = id
        self.name = name
        self.cf = FakeCF(**(cf or {}))
        self.export_policies = FakeQuerySet(export_policies or [])
        self.import_policies = FakeQuerySet(import_policies or [])


class FakeBGPAddress:
    def __init__(self, cidr, vrf=None, family=4):
        self.address = IPValue(cidr)
        self.vrf = vrf
        self.family = family


class FakeBGPSession:
    def __init__(
        self,
        device,
        local_address,
        remote_address,
        local_as,
        remote_as,
        peer_group,
        description="",
        cf=None,
        status="active",
        tags=None,
        export_policies=None,
        import_policies=None,
    ):
        self.device = device
        self.local_address = local_address
        self.remote_address = remote_address
        self.local_as = types.SimpleNamespace(asn=local_as)
        self.remote_as = types.SimpleNamespace(asn=remote_as)
        self.peer_group = peer_group
        self.description = description
        self.cf = FakeCF(**(cf or {}))
        self.status = status
        self.tags = FakeTags(tags)
        self.export_policies = FakeQuerySet(export_policies or [])
        self.import_policies = FakeQuerySet(import_policies or [])


class FakeEsi:
    """A `netbox_custom_objects` 'esi' custom-object instance lookalike -
    holds the ESI value plus every interface (ae* and members, both leafs)
    sharing that ethernet segment."""

    def __init__(self, esi_id, interfaces=None, id=None):
        self.esi_id = esi_id
        self.interfaces = FakeQuerySet(interfaces or [])
        self.id = id or esi_id


class FakeEsiQuerySet(FakeQuerySet):
    """Only implements the one lookup leaf/junos/main.j2 actually issues
    (interfaces__in=<device_interfaces>) - a M2M "any of these interfaces
    is linked to this esi object" match, which the generic `_matches()`
    helper (built for scalar fields) doesn't express."""

    def filter(self, **kwargs):
        if "interfaces__in" in kwargs:
            wanted = {_key(i) for i in kwargs["interfaces__in"]}
            return FakeEsiQuerySet(
                esi for esi in self if wanted & {_key(i) for i in esi.interfaces.all()}
            )
        return FakeEsiQuerySet(super().filter(**kwargs))

    def distinct(self):
        return self


def fake_ipam(vlans=None):
    """Mimics the `ipam` app namespace NetBox's config-template renderer
    exposes (`ipam.VLAN.objects.filter(...)`), scoped to just VLAN since
    that's the only ipam model these templates query directly."""
    return types.SimpleNamespace(VLAN=FakeManager(vlans or []))


def fake_netbox_custom_objects(esi_objects=None):
    """Mimics `netbox_custom_objects.CustomObjectType.objects.get(name='esi').get_model()`
    resolving to a stand-in model class whose `.objects` is queryable."""
    esi_model = types.SimpleNamespace(objects=FakeEsiQuerySet(esi_objects or []))
    esi_type = types.SimpleNamespace(get_model=lambda: esi_model)
    return types.SimpleNamespace(
        CustomObjectType=types.SimpleNamespace(
            objects=types.SimpleNamespace(get=lambda name: {"esi": esi_type}[name])
        )
    )


def fake_netbox_bgp(
    sessions=None,
    peer_groups=None,
    routing_policies=None,
    prefix_lists=None,
    prefix_list_rules=None,
    aspath_list_rules=None,
):
    return types.SimpleNamespace(
        BGPSession=FakeManager(sessions),
        BGPPeerGroup=FakeManager(peer_groups),
        RoutingPolicy=FakeManager(routing_policies),
        PrefixList=FakeManager(prefix_lists),
        PrefixListRule=FakeManager(prefix_list_rules),
        ASPathListRule=FakeManager(aspath_list_rules),
    )
