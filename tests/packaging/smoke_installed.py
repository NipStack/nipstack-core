"""Minimal installed-package smoke; functional validation belongs to unit tests."""

import argparse
import json
import sys
from datetime import UTC, datetime
from importlib import import_module, resources
from importlib.metadata import version
from pathlib import Path
from pkgutil import walk_packages
from types import ModuleType


def assert_installed_location(module: ModuleType, environment: Path) -> None:
    assert module.__file__ is not None, f"Module has no installed file: {module.__name__}"
    location = Path(module.__file__).resolve()
    assert location.is_relative_to(environment.resolve()), (
        f"{module.__name__} imported from outside the isolated environment: {location}"
    )


def smoke_installed(expected_version: str) -> None:
    assert sys.flags.isolated, "Run the installed-package smoke with python -I"
    import nipstack_core
    from nipstack_core import (
        CollectionResult,
        CollectionStatus,
        ExecutionMetadata,
        FeatureResult,
        FeatureSelection,
        FeatureStatus,
        ProfileIdentity,
        RawArtifact,
        SchemaIdentity,
        TargetDescriptor,
        contracts,
    )
    from nipstack_core.profiles import (
        ArtifactDefinition,
        CLIActionDefinition,
        HTTPRequestDefinition,
    )

    environment = Path(sys.prefix)
    assert_installed_location(nipstack_core, environment)
    for info in walk_packages(nipstack_core.__path__, "nipstack_core."):
        module = import_module(info.name)
        assert_installed_location(module, environment)
        for name in getattr(module, "__all__", ()):
            getattr(module, name)
    assert resources.files(nipstack_core).joinpath("py.typed").is_file()
    assert version("nipstack-core") == expected_version
    assert set(nipstack_core.__all__) == set(contracts.__all__)
    for name in nipstack_core.__all__:
        assert getattr(nipstack_core, name) is getattr(contracts, name)

    now = datetime(2026, 1, 1, tzinfo=UTC)
    artifact = RawArtifact(
        artifact_id="raw-version",
        action_id="show_version",
        kind="command_output",
        content_type="text/plain",
        content=None,
        acquired_at=now,
        duration_ms=0,
    )
    feature = FeatureResult(
        feature_id="check.global.show_version",
        status=FeatureStatus.SUCCESS,
        started_at=now,
        finished_at=now,
        schema_identity=SchemaIdentity(digest="sha256:" + "a" * 64),
        data={"version": "synthetic"},
        source_artifact_refs=[artifact.artifact_id],
    )
    result = CollectionResult(
        status=CollectionStatus.SUCCESS,
        profile=ProfileIdentity(profile_id="example.switch.cli", version="1.0.0"),
        target=TargetDescriptor(scheme="ssh", host="switch.example.invalid", port=22),
        execution=ExecutionMetadata(
            collection_id="installed-smoke",
            nipstack_core_version=expected_version,
            started_at=now,
            finished_at=now,
            duration_ms=0,
        ),
        features={feature.feature_id: feature},
        artifacts={artifact.artifact_id: artifact},
    )
    assert FeatureSelection.features(feature.feature_id).values == (feature.feature_id,)
    assert json.loads(json.dumps(result.to_dict(), allow_nan=False))["status"] == "SUCCESS"
    CLIActionDefinition(
        action_id="show_version",
        command="show version",
        artifact=ArtifactDefinition(kind="command_output"),
    )
    HTTPRequestDefinition(path="/api/status", query=[("item", "first"), ("item", "second")])
    print(f"Installed nipstack-core {expected_version} smoke passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("expected_version")
    smoke_installed(parser.parse_args().expected_version)
