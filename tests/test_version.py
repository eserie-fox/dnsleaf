from __future__ import annotations

import tomllib
from pathlib import Path

import dnsleaf
import dnsleaf.config as config_package
import dnsleaf.logging as logging_package
from dnsleaf.version import __version__ as module_version


def test_all_package_inits_are_thin() -> None:
    init_paths = [Path("tests/__init__.py"), *sorted(Path("src/dnsleaf").rglob("__init__.py"))]

    for path in init_paths:
        contents = path.read_text(encoding="utf-8")
        significant_lines = [
            line.strip()
            for line in contents.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        import_lines = [line for line in significant_lines if line.startswith(("from ", "import "))]

        assert "__all__: list[str] = []" in contents
        assert import_lines == [], path.as_posix()


def test_root_package_is_thin_and_version_stays_direct() -> None:
    assert dnsleaf.__all__ == []
    assert not hasattr(dnsleaf, "__version__")
    assert module_version


def test_pyproject_uses_dynamic_version() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert "version" not in pyproject["project"]
    assert pyproject["project"]["dynamic"] == ["version"]
    assert pyproject["build-system"]["build-backend"] == "setuptools.build_meta"
    assert pyproject["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "dnsleaf.version.__version__"
    }


def test_config_package_is_thin() -> None:
    assert config_package.__all__ == []
    assert not hasattr(config_package, "OutsideWorkspaceConfig")
    assert not hasattr(config_package, "read_text")


def test_logging_package_is_thin() -> None:
    assert logging_package.__all__ == []
    assert not hasattr(logging_package, "configure_default_logging")
    assert not hasattr(logging_package, "workspace_logging_context")
