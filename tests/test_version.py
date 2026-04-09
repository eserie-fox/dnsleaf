from __future__ import annotations

import tomllib
from pathlib import Path

import arbor_ddns
import arbor_ddns.config as config_package
import arbor_ddns.logging as logging_package
from arbor_ddns.version import __version__ as module_version


def test_all_package_inits_are_thin() -> None:
    init_paths = [Path("tests/__init__.py"), *sorted(Path("src/arbor_ddns").rglob("__init__.py"))]

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
    assert arbor_ddns.__all__ == []
    assert not hasattr(arbor_ddns, "__version__")
    assert module_version


def test_pyproject_uses_dynamic_version() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert "version" not in pyproject["project"]
    assert pyproject["project"]["dynamic"] == ["version"]
    assert pyproject["tool"]["hatch"]["version"]["path"] == "src/arbor_ddns/version.py"


def test_config_package_is_thin() -> None:
    assert config_package.__all__ == []
    assert not hasattr(config_package, "OutsideWorkspaceConfig")
    assert not hasattr(config_package, "read_text")


def test_logging_package_is_thin() -> None:
    assert logging_package.__all__ == []
    assert not hasattr(logging_package, "configure_default_logging")
    assert not hasattr(logging_package, "workspace_logging_context")
