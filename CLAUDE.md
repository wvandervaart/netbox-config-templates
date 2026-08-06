# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A collection of Jinja2 templates consumed by NetBox's device config-rendering feature (Config Templates / `render_config()`), backed by this repo as a Git data source. There is no build tooling. `./lint.sh` runs a Jinja2 syntax linter (see "Linting" below) and a pytest suite exists under `tests/` covering `spine/eos`, `spine/junos`, `leaf/junos`, `router/eos`, `router/junos`, `ds/junos`, and `mgmt` — it renders each role's `main.j2` against either a hand-written mock device or a real device snapshot captured from NetBox, and asserts on specific output lines — see "Testing" below. For templates or scenarios not covered there, the only way to validate a change is to reason through the Jinja2 logic and, ideally, render it against real or sample NetBox device data.

Templates render vendor CLI configuration (`set ...` statements for Junos, block-style CLI for Arista EOS) from NetBox's data model. They rely on the [netbox-bgp](https://github.com/netbox-community/netbox-bgp) plugin for BGP data (`netbox_bgp.BGPSession`, `netbox_bgp.BGPPeerGroup`) and on config-context data injected by NetBox for things like `users`, `utility` (NTP/DNS/syslog/timezone), and `ddos_protection`.

## Structure

Templates are organized `<role>/<vendor>/<feature>.j2`:

- `common/` — shared includes for both `eos` and `junos`, pulled in by role-specific `main.j2` files (BGP policy/prefix-lists, interfaces, routing-instances, SNMP, sFlow, OSPF, PIM/IGMP, etc.)
- `spine/eos/` — spine switches (Arista EOS only)
- `leaf/junos/` — EVPN/VXLAN leaf switches (Junos only), includes `overlay/` (EVPN, switch-options, overlay policy) and `underlay.j2`
- `router/eos/`, `router/junos/` — border/edge routers, both vendors
- `ds/junos/` — distribution switches (Junos only), includes virtual-chassis (`vc.j2`)
- `mgmt/` — out-of-band management switch config (Junos only)

Each role/vendor pair has a `main.j2` that is the actual entry point registered in NetBox as the Config Template; it `{% include %}`s the feature-specific partials in a specific order (delete/cleanup statements first, then system, protocols, interfaces, routing). When adding a new feature template, wire it into the relevant `main.j2` include chain at the right point — order matters because later Junos `delete`/`set` statements can depend on earlier context.

Junos templates generally emit `set` (and sometimes leading `delete`) statements for load-merge. EOS templates emit native block-style CLI.

## Working with these templates

- Mirror the vendor style already used in sibling files in the same directory before inventing new patterns (macro helpers like `ri()`/`pgb()`/`nbb()` in `common/junos/bgp/bgp.j2` are a good example of the established idiom for building `routing-instances ... protocols bgp group ...` prefixes).
- Common context variables seen across templates: `device` (NetBox Device — `.name`, `.role.name`, `.tags.names()`, `.interfaces.all()`, `.primary_ip`, custom fields via `.cf`), `interface.cf.get('INPUT_FILTER'|'OUTPUT_FILTER')`, `bgp.asn`, `netbox_bgp.BGPSession.objects.filter(device=device)`, `netbox_bgp.BGPPeerGroup.objects.all()`, peer/peer-group custom fields (`pg.cf.AUTH_KEY`, `pg.cf.PREFIX_LIMIT`, `pg.cf.BFD`, `pg.cf.FILTER_PRIVATE_ASN`), and config-context data (`users.junos`, `users.exampleorg`, `utility.timezone`/`.ntp`/`.dns`/`.syslog`, `ddos_protection`).
- Each role's `main.j2` (or its `bgp/main.j2` sub-entry-point, where one exists — `leaf/junos`, `router/eos`, `spine/eos`) pre-fetches `bgp_sessions`, `bgp_peer_groups`, and `device_interfaces` once at the top, with `select_related`/`prefetch_related` covering what the partials below actually read, and `router/junos/main.j2` additionally resolves `loopback0`. Partials that need BGP sessions/peer-groups or device interfaces **must** consume these shared variables instead of calling `netbox_bgp.BGPSession.objects.filter(device=device)` / `netbox_bgp.BGPPeerGroup.objects.all()` / `device.interfaces.all()` directly — doing so bypasses the prefetch and reintroduces N+1 queries per device render. If a new partial needs a relation on `bgp_sessions`/`device_interfaces` that isn't already prefetched, extend the `select_related`/`prefetch_related` call in the relevant `main.j2` file(s) rather than querying it fresh in the partial. Note these variables can't live in a shared included partial themselves: Jinja2's `{% set %}` doesn't propagate back out of an `{% include %}` to the includer's scope, so each entry-point file needs its own copy — keep them in sync across the files noted in each copy's comment.
- A device's `maintenance` tag and the `is_maintenance` pattern (reject-all export policy) is a recurring convention for taking a device out of production traffic without deleting BGP sessions — reuse it rather than adding a new mechanism.
- Since custom fields (`.cf`) and config-context keys are not guaranteed present, follow existing templates' pattern of guarding with `is defined` / `.get(...)` before use.
- After editing a template covered by `tests/`, run `python3 -m pytest tests/` (see "Testing" below) and update/extend the fixtures and assertions for whatever changed. For templates without coverage, sanity-check by reading the rendered output mentally (or, if available, rendering it in a NetBox instance against a real device) — pay special attention to Junos `set`/`delete` ordering and to any loop that builds up state across multiple passes (e.g. `common/junos/bgp/bgp.j2` and `router/eos/bgp/bgp.j2` do a two-pass per-neighbor-then-per-peer-group render, tracking peer-group IDs and VRFs in dicts/lists across the passes).
- Run `./lint.sh` before committing a template change (see "Linting" below) — it's cheap and catches malformed `{% %}`/`{{ }}` syntax that would otherwise only surface when NetBox tries to render the template against a real device.

## Linting

`./lint.sh` (needs `j2lint` from `tests/requirements.txt`) runs [j2lint](https://github.com/aristanetworks/j2lint) over every `.j2` file. Only `jinja-syntax-error` and `jinja-statements-no-tabs` are enabled — every other built-in j2lint rule is ignored because it conflicts with idioms this repo relies on throughout (whitespace-control macros like `ri()`/`pgb()`/`nbb()` that pack multiple statements per line, UPPER_CASE NetBox custom-field names, inconsistent nesting indentation) and would otherwise flag ~2000 pre-existing, intentional lines with no bug behind them. Exit code is non-zero on a real syntax error. If you want to see the ignored style rules anyway (e.g. before a larger cleanup), run `j2lint` directly without `lint.sh`'s `-i` flags, or swap `-i` for `-w` to get warnings instead of failures.

**Pre-commit hook**: `.githooks/pre-commit` runs `./lint.sh` and blocks the commit on failure. It lives in-repo rather than `.git/hooks` (which git doesn't version-control), so it needs a one-time opt-in per clone: `git config core.hooksPath .githooks`. Skip it for a single commit with `git commit --no-verify`.

There's also a **pre-push hook** (`.githooks/pre-push`) that runs the full pytest suite and blocks the push on failure — see "Testing" below. Both hooks live in `.githooks/` and are activated by the same one-time `git config core.hooksPath .githooks`.

## Testing

`tests/` holds a pytest suite (`pip install -r tests/requirements.txt`, then `python3 -m pytest tests/` from the repo root). There are two kinds of fixture data, both landing in the same shape of context dict and read by the same `render`/`rendered_lines` fixtures from `tests/conftest.py`:

**Hand-written mocks** (used by `spine/junos`, the one role with no real device in NetBox yet):
- `tests/netbox_mocks.py` — minimal stand-ins for the NetBox/netbox-bgp object surface these templates touch (`FakeDevice`, `FakeInterface`, `FakeQuerySet` with `.all()`/`.filter()`/`.get()`, `FakeCF`, `FakeBGPSession`, `FakePolicy`, etc.) — not a NetBox client, just enough attribute/method surface for Jinja2 to walk.
- `tests/fixtures.py` — builds representative context dicts (e.g. `build_spine_context()`) wiring those mocks into a plausible device.

**Real device snapshots** (used by every other role — `spine/eos`, `leaf/junos`, `router/eos`, `router/junos`, `ds/junos`, `mgmt`):
- `tests/fetch_netbox_snapshot.py` — a one-off/occasional script (`python3 tests/fetch_netbox_snapshot.py <device-name-or-id>`, needs `NETBOX_URL`/`NETBOX_TOKEN` env vars, **never** hardcode a token in a committed file) that pulls a real device's full data — interfaces, IPs, VRFs, VLANs, static routes, netbox-bgp sessions/peer-groups, and config-context — and writes it to `tests/snapshots/<device-name>.json`. It redacts secret-shaped and personally-identifying fields (encrypted passwords, BGP/OSPF auth keys, SNMPv3 keys, SSH public keys, contact emails, NetBox API `url` fields — see `REDACT_KEYS`) before anything touches disk, since `config_context` carries real production credentials (including Junos `$9$` values, which are reversible, not actually encrypted) and real employee SSH keys that shouldn't end up in git history even in a private repo. It also warns (doesn't block) if the device's own AS number looks like a real, WHOIS-attributable ASN rather than a private one. If you add a field to the snapshot schema, check whether it can carry secrets or PII and redact accordingly.
- `tests/snapshots/*.json` — the committed, redacted snapshots. Tests run fully offline against these; nothing in the test suite itself talks to NetBox.
- `tests/netbox_snapshot.py` — `load_context(device_name)` reads a snapshot and builds the same `Fake*` mock graph (from `netbox_mocks.py`) plus the full `render_config()` context. NetBox's actual context is `{"device": device, **device.get_config_context()}` — config-context keys are spread at the top level — and since Jinja2's attribute access on a dict falls back to item access, the raw JSON config-context dicts are used as-is without extra wrapping.
- `tests/test_*.py` — renders a role's `main.j2` against a fixture (mock or snapshot) and asserts specific `set ...`/`delete ...` lines are present or absent, rather than diffing a full golden file, so unrelated formatting/ordering changes don't break unrelated tests.

To refresh a snapshot after real NetBox data changes, re-run `fetch_netbox_snapshot.py` for that device and re-verify the test assertions still hold (the fixture is real data, so specific IPs/ASNs/peer names in the assertions can legitimately go stale).

**Pre-push hook**: `.githooks/pre-push` runs `python3 -m pytest tests/` and blocks the push on failure — same one-time opt-in as the pre-commit hook (`git config core.hooksPath .githooks`), and same escape hatch (`git push --no-verify`).

This only proves the Jinja2 logic does what's intended given known inputs — for the snapshot-based tests that's real NetBox data, but a snapshot is still a point-in-time capture, not a live validation. When adding templates or fixing bugs elsewhere, prefer a real-device snapshot over a hand-written mock if a suitable device exists in NetBox; fall back to hand-written mocks (as `spine/junos` does) only when no real device covers the scenario.
