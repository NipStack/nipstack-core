"""Typed public contracts independent of implementation modules."""

from .authentication import BearerTokenAuth, NoAuth, SSHKeyAuth, UsernamePasswordAuth
from .connection_target import ConnectionTarget, HTTPEndpoint, SSHEndpoint, TargetDescriptor
from .errors import NipStackCoreUsageError
from .feature_selection import FeatureSelection, FeatureSelectionKind
from .secrets import SecretValue

__all__ = [
    "BearerTokenAuth",
    "ConnectionTarget",
    "FeatureSelection",
    "FeatureSelectionKind",
    "HTTPEndpoint",
    "NipStackCoreUsageError",
    "NoAuth",
    "SecretValue",
    "SSHKeyAuth",
    "SSHEndpoint",
    "TargetDescriptor",
    "UsernamePasswordAuth",
]
