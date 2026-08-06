#!/usr/bin/env bash
# Lints every Jinja2 template with j2lint (pip install -r tests/requirements.txt).
#
# Only real syntax errors (jinja-syntax-error) and tab-indentation
# (jinja-statements-no-tabs) fail the build. Every other built-in j2lint rule
# is ignored because it conflicts with idioms this repo already relies on
# throughout (see CLAUDE.md "Working with these templates"):
#   - whitespace-control macros like ri()/pgb()/nbb() in common/junos/bgp/bgp.j2
#     pack multiple statements per line and use {%- ... -%} intentionally
#   - NetBox custom-field names are UPPER_CASE by convention
#     (e.g. interface.cf.OSPF_AREA), which is the opposite of what j2lint wants
#   - indentation is not consistently 4-space-per-nesting-level across files
# Turning those rules on would flag ~2000 pre-existing, intentional lines
# with no bug behind them. If you want to see them anyway, drop `-i ...` or
# swap it for `-w ...` to get warnings without failing.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v j2lint >/dev/null 2>&1; then
  echo "lint.sh: j2lint not found. Install it with: pip install -r tests/requirements.txt" >&2
  exit 1
fi

IGNORE=(
  jinja-variable-lower-case
  jinja-variable-format
  jinja-statements-indentation
  jinja-statements-delimiter
  single-statement-per-line   # ri()/pgb()/nbb() macros + dedup-append guards
)

j2lint -i "${IGNORE[@]}" -- $(find common spine leaf router ds mgmt -name '*.j2')
