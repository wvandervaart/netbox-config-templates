# netbox-config-templates

A collection of Jinja2 templates for NetBox's device config-rendering feature
(Config Templates / `render_config()`), backed by this repo as a Git data
source. Templates render vendor CLI configuration (`set ...` statements for
Junos, block-style CLI for Arista EOS) from NetBox's data model, using the
[netbox-bgp](https://github.com/netbox-community/netbox-bgp) plugin for BGP
data and config-context data for things like NTP/DNS/syslog and local users.

See [CLAUDE.md](CLAUDE.md) for repo structure, conventions, linting, and
testing, and [NETBOX.md](NETBOX.md) for the NetBox custom fields, tags, and
config-context keys these templates read.

This is a sanitized copy for public sharing - see `scripts/` for how
company-identifying values were scrubbed from the original private repo.
