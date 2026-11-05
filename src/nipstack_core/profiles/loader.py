"""Strict loading of one explicit local Profile, without validation or activation gates."""

from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from nipstack_core.contracts.errors import NipStackCoreUsageError
from nipstack_core.contracts.json_data import JSONDocument, JSONValue

from ._load_types import LoadedProfile, LoadLimits, ProfileLoadError
from ._resources import _open_root, _read_regular_file
from ._yaml import _decode_manifest_yaml
from .actions import (
    ActionDefinition,
    ArtifactDefinition,
    CLIActionDefinition,
    CLIContextDefinition,
    HTTPActionDefinition,
    HTTPRequestDefinition,
)
from .features import FeatureDefinition, ParserDefinition
from .profile import ConnectionDefinition, FingerprintDefinition, ProfileDefinition, ProfileMetadata

__all__ = ["LoadedProfile", "LoadLimits", "ProfileLoadError", "load_profile"]

_DEFAULT_LIMITS = LoadLimits()


def _mapping(
    value: JSONValue,
    field: str,
    *,
    required: tuple[str, ...] = (),
    optional: tuple[str, ...] = (),
    open_keys: bool = False,
) -> Mapping[str, JSONValue]:
    if not isinstance(value, Mapping):
        raise ProfileLoadError("INVALID_MANIFEST", field=field)
    if not open_keys and any(key not in required + optional for key in value):
        raise ProfileLoadError("INVALID_MANIFEST", field=field)
    if any(key not in value for key in required):
        raise ProfileLoadError("INVALID_MANIFEST", field=field)
    return value


def _string(value: JSONValue, field: str) -> str:
    if not isinstance(value, str):
        raise ProfileLoadError("INVALID_MANIFEST", field=field)
    return value


def _optional_string(value: JSONValue, field: str) -> str | None:
    return None if value is None else _string(value, field)


def _strings(value: JSONValue, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ProfileLoadError("INVALID_MANIFEST", field=field)
    return tuple(_string(item, field) for item in value)


def _timeout(value: JSONValue, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProfileLoadError("INVALID_MANIFEST", field=field)
    return value


def _artifact(value: JSONValue, field: str) -> ArtifactDefinition:
    data = _mapping(value, field, required=("kind",), optional=("expose_by_default",))
    expose = data.get("expose_by_default", False)
    if not isinstance(expose, bool):
        raise ProfileLoadError("INVALID_MANIFEST", field=field)
    return ArtifactDefinition(kind=_string(data["kind"], field), expose_by_default=expose)


def _connection(value: JSONValue) -> ConnectionDefinition:
    field = "connection"
    data = _mapping(
        value,
        field,
        required=("connector",),
        optional=(
            "driver",
            "authentication",
            "session_setup",
            "connect_timeout",
            "operation_timeout",
        ),
    )
    connector = data["connector"]
    kind: Literal["ssh", "http"]
    if connector == "ssh":
        kind = "ssh"
    elif connector == "http":
        kind = "http"
    else:
        raise ProfileLoadError("INVALID_MANIFEST", field=field)
    return ConnectionDefinition(
        connector=kind,
        driver=_optional_string(data.get("driver"), field),
        authentication=_optional_string(data.get("authentication"), field),
        session_setup=_strings(data.get("session_setup", []), field),
        connect_timeout=_timeout(data.get("connect_timeout"), field),
        operation_timeout=_timeout(data.get("operation_timeout"), field),
    )


def _query(value: JSONValue, field: str) -> tuple[tuple[str, str], ...] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ProfileLoadError("INVALID_MANIFEST", field=field)
    pairs: list[tuple[str, str]] = []
    for pair in value:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ProfileLoadError("INVALID_MANIFEST", field=field)
        pairs.append((_string(pair[0], field), _string(pair[1], field)))
    return tuple(pairs)


def _request(value: JSONValue, field: str) -> HTTPRequestDefinition:
    data = _mapping(
        value, field, required=("path",), optional=("method", "query", "headers", "body")
    )
    method = data.get("method", "GET")
    verb: Literal["GET", "POST"]
    if method == "GET":
        verb = "GET"
    elif method == "POST":
        verb = "POST"
    else:
        raise ProfileLoadError("INVALID_MANIFEST", field=field)
    headers: dict[str, str] | None = None
    if data.get("headers") is not None:
        headers = {
            key: _string(item, field + ".headers")
            for key, item in _mapping(data["headers"], field + ".headers", open_keys=True).items()
        }
    body = data.get("body")
    document: JSONDocument | None
    if body is None or isinstance(body, (Mapping, list)):
        document = body
    else:
        raise ProfileLoadError("INVALID_MANIFEST", field=field + ".body")
    return HTTPRequestDefinition(
        path=_string(data["path"], field + ".path"),
        method=verb,
        query=_query(data.get("query"), field + ".query"),
        headers=headers,
        body=document,
    )


def _action(action_id: str, value: JSONValue, field: str) -> ActionDefinition:
    data = _mapping(value, field, open_keys=True)
    if data.get("type") == "cli":
        data = _mapping(
            data,
            field,
            required=("type", "command", "artifact"),
            optional=("context", "operation_timeout"),
        )
        context = None
        if data.get("context") is not None:
            item = _mapping(data["context"], field + ".context", optional=("enter", "exit"))
            context = CLIContextDefinition(
                enter=_strings(item.get("enter", []), field + ".context.enter"),
                exit=_strings(item.get("exit", []), field + ".context.exit"),
            )
        return CLIActionDefinition(
            action_id=action_id,
            command=_string(data["command"], field + ".command"),
            artifact=_artifact(data["artifact"], field + ".artifact"),
            context=context,
            operation_timeout=_timeout(data.get("operation_timeout"), field),
        )
    if data.get("type") == "http":
        data = _mapping(
            data, field, required=("type", "request", "artifact"), optional=("operation_timeout",)
        )
        return HTTPActionDefinition(
            action_id=action_id,
            request=_request(data["request"], field + ".request"),
            artifact=_artifact(data["artifact"], field + ".artifact"),
            operation_timeout=_timeout(data.get("operation_timeout"), field),
        )
    raise ProfileLoadError("INVALID_MANIFEST", field=field)


def _feature(feature_id: str, value: JSONValue, field: str) -> FeatureDefinition:
    data = _mapping(value, field, required=("inputs", "parser", "schema"))
    parser = _mapping(data["parser"], field + ".parser", required=("engine", "template"))
    engine = parser["engine"]
    kind: Literal["native", "jmespath"]
    if engine == "native":
        kind = "native"
    elif engine == "jmespath":
        kind = "jmespath"
    else:
        raise ProfileLoadError("INVALID_MANIFEST", field=field + ".parser")
    return FeatureDefinition(
        feature_id=feature_id,
        inputs=_strings(data["inputs"], field + ".inputs"),
        parser=ParserDefinition(
            engine=kind, template=_string(parser["template"], field + ".parser.template")
        ),
        schema=_string(data["schema"], field + ".schema"),
    )


def _fingerprint(value: JSONValue) -> FingerprintDefinition | None:
    if value is None:
        return None
    data = _mapping(value, "identification", required=("action", "match"))
    match = _mapping(
        data["match"], "identification.match", required=("include",), optional=("exclude",)
    )
    return FingerprintDefinition(
        action_id=_string(data["action"], "identification.action"),
        include=_strings(match["include"], "identification.match.include"),
        exclude=_strings(match.get("exclude", []), "identification.match.exclude"),
    )


def _construct_profile(
    document: Mapping[str, JSONValue], *, limits: LoadLimits
) -> ProfileDefinition:
    data = _mapping(
        document,
        "manifest",
        required=("spec_version", "id", "version", "metadata", "connection", "actions", "features"),
        optional=("identification",),
    )
    if type(data["spec_version"]) is not int or data["spec_version"] != 1:
        raise ProfileLoadError("INVALID_MANIFEST", field="spec_version")
    metadata = _mapping(
        data["metadata"], "metadata", required=("name", "vendor", "platform_id", "access_variant")
    )
    actions = _mapping(data["actions"], "actions", open_keys=True)
    features = _mapping(data["features"], "features", open_keys=True)
    if len(actions) > limits.max_actions or len(features) > limits.max_features:
        raise ProfileLoadError("RESOURCE_LIMIT")
    return ProfileDefinition(
        profile_id=_string(data["id"], "id"),
        version=_string(data["version"], "version"),
        spec_version=1,
        metadata=ProfileMetadata(
            name=_string(metadata["name"], "metadata.name"),
            vendor=_string(metadata["vendor"], "metadata.vendor"),
            platform_id=_string(metadata["platform_id"], "metadata.platform_id"),
            access_variant=_string(metadata["access_variant"], "metadata.access_variant"),
        ),
        connection=_connection(data["connection"]),
        actions={
            key: _action(key, item, f"actions[{index}]")
            for index, (key, item) in enumerate(actions.items())
        },
        features={
            key: _feature(key, item, f"features[{index}]")
            for index, (key, item) in enumerate(features.items())
        },
        fingerprint=_fingerprint(data.get("identification")),
    )


def _check_action_references(definition: ProfileDefinition) -> None:
    for index, feature in enumerate(definition.features.values()):
        if any(action not in definition.actions for action in feature.inputs):
            raise ProfileLoadError("INVALID_REFERENCE", field=f"features[{index}].inputs")
    if (
        definition.fingerprint is not None
        and definition.fingerprint.action_id not in definition.actions
    ):
        raise ProfileLoadError("INVALID_REFERENCE", field="identification.action")


def load_profile(root: Path, *, limits: LoadLimits = _DEFAULT_LIMITS) -> LoadedProfile:
    """Load one explicitly selected Linux directory into definitions and byte snapshots.

    Resources remain opaque: this performs no parser/schema compilation,
    capability verification, fingerprint matching or Profile activation.
    Filesystem checks resist symlink substitution, not arbitrary local writers,
    mount manipulation, hard links or all concurrent directory renames.

    Args:
        root: Absolute Profile directory, without symlink components.
        limits: Caller-controlled per-load budgets; never read from the manifest.

    Returns:
        Owned immutable data, independent of later filesystem changes.

    Raises:
        ProfileLoadError: Arguments, platform, files, manifest or references fail.
    """
    if not isinstance(limits, LoadLimits):
        raise ProfileLoadError("INVALID_ARGUMENT", field="limits")
    try:
        with _open_root(root) as root_fd:
            manifest = _read_regular_file(
                root_fd,
                "profile.yaml",
                max_bytes=min(limits.max_manifest_bytes, limits.max_total_bytes),
                max_components=limits.max_path_components,
            )
            definition = _construct_profile(
                _decode_manifest_yaml(manifest, limits=limits), limits=limits
            )
            _check_action_references(definition)
            references: dict[str, None] = {}
            for feature in definition.features.values():
                for reference in (feature.parser.template, feature.schema):
                    if reference not in references:
                        if len(references) >= limits.max_resource_files:
                            raise ProfileLoadError("RESOURCE_LIMIT")
                        references[reference] = None
            resources: dict[str, bytes] = {}
            total = len(manifest)
            for reference in references:
                if reference == "profile.yaml":
                    if len(manifest) > limits.max_resource_bytes:
                        raise ProfileLoadError("RESOURCE_LIMIT")
                    content = manifest
                else:
                    content = _read_regular_file(
                        root_fd,
                        reference,
                        max_bytes=min(limits.max_resource_bytes, limits.max_total_bytes - total),
                        max_components=limits.max_path_components,
                    )
                    total += len(content)
                resources[reference] = content
            return LoadedProfile(definition=definition, resources=resources)
    except ProfileLoadError:
        raise
    except NipStackCoreUsageError:
        raise ProfileLoadError("INVALID_MANIFEST") from None
