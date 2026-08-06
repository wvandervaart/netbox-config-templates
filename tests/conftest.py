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