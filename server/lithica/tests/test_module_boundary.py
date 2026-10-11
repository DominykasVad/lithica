"""
The module boundary (AGENTS.md, "Modules"): the engine never imports a
module, and a module never imports another module. import-linter checks it
from the contracts in pyproject.toml; CI runs it as its own step too.
"""

import sys
import tomllib
from pathlib import Path

import pytest
from importlinter import cli

SERVER_DIR = Path(__file__).resolve().parent.parent.parent
PACKAGE_DIR = SERVER_DIR / "lithica"
PYPROJECT = SERVER_DIR / "pyproject.toml"

# children of the package that are not the engine
NOT_ENGINE = {"modules", "tests"}


def _contracts() -> dict[str, dict]:
    with open(PYPROJECT, "rb") as handle:
        settings = tomllib.load(handle)["tool"]["importlinter"]
    assert settings["root_package"] == "lithica"
    return {contract["type"]: contract for contract in settings["contracts"]}


def test_contracts_hold(capsys):
    status = cli.lint_imports(config_filename=str(PYPROJECT), no_cache=True)
    assert status == 0, capsys.readouterr().out


def test_every_part_of_the_engine_is_guarded():
    parts = set()
    for child in PACKAGE_DIR.iterdir():
        if child.name.startswith("__") or child.name in NOT_ENGINE:
            continue
        if child.suffix == ".py":
            parts.add("lithica." + child.stem)
        elif (child / "__init__.py").exists():
            parts.add("lithica." + child.name)
    guarded = _contracts()["forbidden"]
    assert set(guarded["source_modules"]) == parts
    assert guarded["forbidden_modules"] == ["lithica.modules"]


def test_modules_are_guarded_from_each_other():
    assert _contracts()["independence"]["modules"] == ["lithica.modules.*"]


@pytest.fixture
def demo_package(tmp_path, monkeypatch):
    """
    A small package laid out like lithica, checked with contracts of the
    same two kinds as ours; returns a function that writes a file in it and
    one that runs the check.
    """
    root = tmp_path / "boundarydemo"
    for folder in ["", "modules", "modules/one", "modules/two"]:
        (root / folder).mkdir(exist_ok=True)
        (root / folder / "__init__.py").write_text("")
    (root / "engine.py").write_text("")
    contracts = _contracts()
    config = tmp_path / "demo.toml"
    config.write_text(
        """
[tool.importlinter]
root_package = "boundarydemo"

[[tool.importlinter.contracts]]
name = "engine"
type = "%s"
source_modules = ["boundarydemo.engine"]
forbidden_modules = ["boundarydemo.modules"]

[[tool.importlinter.contracts]]
name = "modules"
type = "%s"
modules = ["boundarydemo.modules.*"]
"""
        % (contracts["forbidden"]["type"], contracts["independence"]["type"])
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    def write(path: str, source: str) -> None:
        (root / path).write_text(source)

    def check() -> int:
        return cli.lint_imports(config_filename=str(config), no_cache=True)

    yield write, check
    for loaded in [name for name in sys.modules if name.startswith("boundarydemo")]:
        del sys.modules[loaded]


def test_module_importing_the_engine_is_allowed(demo_package, capsys):
    write, check = demo_package
    write("modules/one/__init__.py", "from boundarydemo import engine\n")
    assert check() == 0, capsys.readouterr().out


@pytest.mark.parametrize(
    "statement",
    [
        "import boundarydemo.modules.one\n",
        "from boundarydemo.modules import one\n",
        "def late():\n    from boundarydemo.modules.one import thing\n",
    ],
)
def test_engine_importing_a_module_is_caught(demo_package, capsys, statement):
    write, check = demo_package
    write("engine.py", statement)
    assert check() == 1
    output = capsys.readouterr().out
    assert "engine BROKEN" in output
    assert "modules KEPT" in output


def test_module_importing_another_module_is_caught(demo_package, capsys):
    write, check = demo_package
    write("modules/one/__init__.py", "from boundarydemo.modules import two\n")
    assert check() == 1
    output = capsys.readouterr().out
    assert "engine KEPT" in output
    assert "modules BROKEN" in output
