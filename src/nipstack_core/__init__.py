"""NipStack Core: network collection and structured observations.

Public APIs are introduced incrementally as the approved contracts are implemented.
"""

from .contracts import (
    BearerTokenAuth,
    ConnectionTarget,
    FeatureSelection,
    FeatureSelectionKind,
    HTTPEndpoint,
    NipStackCoreUsageError,
    NoAuth,
    SecretValue,
    SSHEndpoint,
    SSHKeyAuth,
    TargetDescriptor,
    UsernamePasswordAuth,
)

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
