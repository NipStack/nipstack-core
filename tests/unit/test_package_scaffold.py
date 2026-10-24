"""Offline smoke tests for the initial NipStack Core package layout."""

from importlib import import_module, resources

import pytest


@pytest.mark.parametrize(
    "module_name",
    [
        "nipstack_core",
        "nipstack_core.catalog",
        "nipstack_core.cli",
        "nipstack_core.connectors",
        "nipstack_core.connectors.http",
        "nipstack_core.connectors.ssh",
        "nipstack_core.contracts",
        "nipstack_core.execution",
        "nipstack_core.exporters",
        "nipstack_core.parsers",
        "nipstack_core.parsers.jmespath",
        "nipstack_core.parsers.native",
        "nipstack_core.planning",
        "nipstack_core.profiles",
        "nipstack_core.resources",
        "nipstack_core.resources.profiles",
        "nipstack_core.validation",
    ],
)
def test_package_boundaries_are_importable(module_name: str) -> None:
    """All initially declared module boundaries remain importable."""
    assert import_module(module_name).__name__ == module_name


def test_package_is_marked_as_typed() -> None:
    """The public package keeps its PEP 561 marker."""
    assert resources.files("nipstack_core").joinpath("py.typed").is_file()
