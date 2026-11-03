"""Private explicit conversion of validated Collection results, never requests or auth."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from math import isfinite
from typing import TYPE_CHECKING

from .errors import NipStackCoreUsageError
from .json_data import JSONValue, _validate_json_string

if TYPE_CHECKING:
    from .artifacts import RawArtifact
    from .identities import ExecutionMetadata, ProfileIdentity, SchemaIdentity
    from .operational_errors import NipStackCoreDiagnostic, NipStackCoreError
    from .results import CollectionResult, FeatureResult


def _collection_result_to_dict(result: CollectionResult) -> dict[str, JSONValue]:
    return {
        "status": result.status.value,
        "profile": _profile_to_dict(result.profile),
        "target": _copy_json_value(result.target.to_dict()),
        "execution": _execution_to_dict(result.execution),
        "features": {key: _feature_to_dict(feature) for key, feature in result.features.items()},
        "artifacts": {
            key: _artifact_to_dict(artifact) for key, artifact in result.artifacts.items()
        },
        "error": _error_to_dict(result.error),
        "diagnostics": [_diagnostic_to_dict(item) for item in result.diagnostics],
    }


def _profile_to_dict(profile: ProfileIdentity) -> dict[str, JSONValue]:
    return {"profile_id": profile.profile_id, "version": profile.version}


def _schema_to_dict(schema: SchemaIdentity | None) -> dict[str, JSONValue] | None:
    if schema is None:
        return None
    return {"digest": schema.digest, "algorithm": schema.algorithm}


def _execution_to_dict(execution: ExecutionMetadata) -> dict[str, JSONValue]:
    return {
        "collection_id": execution.collection_id,
        "nipstack_core_version": execution.nipstack_core_version,
        "started_at": _timestamp_to_text(execution.started_at),
        "finished_at": _timestamp_to_text(execution.finished_at),
        "duration_ms": execution.duration_ms,
        "correlation_id": execution.correlation_id,
    }


def _feature_to_dict(feature: FeatureResult) -> dict[str, JSONValue]:
    return {
        "feature_id": feature.feature_id,
        "status": feature.status.value,
        "scope_hint": feature.scope_hint.value,
        "started_at": _timestamp_to_text(feature.started_at),
        "finished_at": _timestamp_to_text(feature.finished_at),
        "schema_identity": _schema_to_dict(feature.schema_identity),
        "data": _copy_json_value(feature.data),
        "error": _error_to_dict(feature.error),
        "source_artifact_refs": list(feature.source_artifact_refs),
    }


def _artifact_to_dict(artifact: RawArtifact) -> dict[str, JSONValue]:
    return {
        "artifact_id": artifact.artifact_id,
        "action_id": artifact.action_id,
        "kind": artifact.kind,
        "content_type": artifact.content_type,
        "content": _copy_json_value(artifact.content),
        "acquired_at": _timestamp_to_text(artifact.acquired_at),
        "duration_ms": artifact.duration_ms,
    }


def _error_to_dict(error: NipStackCoreError | None) -> dict[str, JSONValue] | None:
    if error is None:
        return None
    return {
        "code": error.code.value,
        "stage": error.stage.value,
        "retry_hint": error.retry_hint.value,
        "context": _copy_json_value(error.context),
        "message": error.message,
    }


def _diagnostic_to_dict(diagnostic: NipStackCoreDiagnostic) -> dict[str, JSONValue]:
    return {
        "code": diagnostic.code.value,
        "stage": diagnostic.stage.value,
        "context": _copy_json_value(diagnostic.context),
        "message": diagnostic.message,
    }


def _timestamp_to_text(timestamp: datetime) -> str:
    return timestamp.isoformat(timespec="microseconds").removesuffix("+00:00") + "Z"


def _copy_json_value(value: JSONValue) -> JSONValue:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        # Use the encoder itself, not str(value), to respect its current integer
        # limits without invoking subclass display hooks or changing global state.
        try:
            json.dumps(value)
        except ValueError:
            raise NipStackCoreUsageError(
                "An integer cannot be encoded by the standard JSON encoder."
            ) from None
        return value
    if isinstance(value, str):
        _validate_json_string(value)
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise NipStackCoreUsageError("JSON numbers must be finite.")
        return value
    if isinstance(value, Mapping):
        copied: dict[str, JSONValue] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise NipStackCoreUsageError("JSON object keys must be strings.")
            _validate_json_string(key)
            copied[key] = _copy_json_value(child)
        return copied
    if isinstance(value, (list, tuple)):
        return [_copy_json_value(child) for child in value]
    raise NipStackCoreUsageError("JSON content contains an unsupported value type.")
