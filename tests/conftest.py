from pathlib import Path

import jinja2
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def jinja_env():
    return jinja2.Environment(loader=jinja2.FileSystemLoader(str(REPO_ROOT)))


@pytest.fixture
def render(jinja_env):
    def _render(template_path, context):
        return jinja_env.get_template(template_path).render(**context)

    return _render


@pytest.fixture
def rendered_lines():
    def _lines(output):
        return {line.strip() for line in output.splitlines() if line.strip()}

    return _lines

# router/ocnos is registered in NetBox with environment params
# {"trim_blocks": true, "lstrip_blocks": true} (see CLAUDE.md) - render it the same way
OCNOS_ENV_PARAMS = {"trim_blocks": True, "lstrip_blocks": True}


@pytest.fixture(scope="session")
def ocnos_env():
    return jinja2.Environment(loader=jinja2.FileSystemLoader(str(REPO_ROOT)), **OCNOS_ENV_PARAMS)


@pytest.fixture
def render_xml(ocnos_env):
    """Render a NETCONF-XML template (router/ocnos) with NetBox's environment params
    for it and parse it - a parse error fails the test, so every user also checks
    the payload is well-formed. Returns (root, raw_output)."""
    from ocnos_xml import parse

    def _render_xml(template_path, context):
        output = ocnos_env.get_template(template_path).render(**context)
        return parse(output), output

    return _render_xml
