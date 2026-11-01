"""Typed public contracts independent of implementation modules."""

from .artifacts import RawArtifact, RawArtifactPolicy
from .authentication import BearerTokenAuth, NoAuth, SSHKeyAuth, UsernamePasswordAuth
from .connection_target import ConnectionTarget, HTTPEndpoint, SSHEndpoint, TargetDescriptor
from .errors import NipStackCoreUsageError
from .feature_selection import FeatureSelection, FeatureSelectionKind
from .identities import ExecutionMetadata, ProfileIdentity, SchemaIdentity
from .json_data import JSONDocument, JSONValue
from .operational_errors import (
    DiagnosticCode,
    ErrorCode,
    ErrorStage,
    NipStackCoreDiagnostic,
    NipStackCoreError,
    RetryHint,
)
from .results import CollectionResult, CollectionStatus, FeatureResult, FeatureStatus, ScopeHint
from .secrets import SecretValue

__all__ = [
    "BearerTokenAuth",
    "CollectionResult",
    "CollectionStatus",
    "ConnectionTarget",
    "DiagnosticCode",
    "ErrorCode",
    "ErrorStage",
    "ExecutionMetadata",
    "FeatureResult",
    "FeatureSelection",
    "FeatureSelectionKind",
    "FeatureStatus",
    "HTTPEndpoint",
    "JSONDocument",
    "JSONValue",
    "NipStackCoreDiagnostic",
    "NipStackCoreError",
    "NipStackCoreUsageError",
    "NoAuth",
    "ProfileIdentity",
    "RawArtifact",
    "RawArtifactPolicy",
    "RetryHint",
    "SchemaIdentity",
    "ScopeHint",
    "SecretValue",
    "SSHKeyAuth",
    "SSHEndpoint",
    "TargetDescriptor",
    "UsernamePasswordAuth",
]
