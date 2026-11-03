"""One-target collection request data, without Profile resolution or execution."""

from dataclasses import dataclass, field

from .artifacts import RawArtifactPolicy
from .connection_target import ConnectionTarget
from .errors import NipStackCoreUsageError
from .events import ExecutionControl
from .feature_selection import FeatureSelection
from .identities import _validate_text


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class CollectionRequest:
    """Explicit collection intent for one logical target, with identity equality/hash.

    Selection is mandatory, including when the caller explicitly selects ALL.
    The envelope is immutable, but an optional caller-owned control remains a
    live object: it is not inspected, copied or invoked. Its type is checked
    statically, not at runtime. Intended display omits target, selection, IDs
    and control. Reflective serialization of this credential-bearing object is
    not safe; there is no public request serializer.

    Raises:
        NipStackCoreUsageError: Identifiers, target, selection or raw policy are invalid.
    """

    profile_id: str = field(repr=False)
    target: ConnectionTarget = field(repr=False)
    selection: FeatureSelection = field(repr=False)
    raw_artifact_policy: RawArtifactPolicy = RawArtifactPolicy.NONE
    correlation_id: str | None = field(default=None, repr=False)
    execution_control: ExecutionControl | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _validate_text(self.profile_id, "profile_id")
        if not isinstance(self.target, ConnectionTarget):
            raise NipStackCoreUsageError("target must be a ConnectionTarget.")
        if not isinstance(self.selection, FeatureSelection):
            raise NipStackCoreUsageError("selection must be an explicit FeatureSelection.")
        if not isinstance(self.raw_artifact_policy, RawArtifactPolicy):
            raise NipStackCoreUsageError("raw_artifact_policy must be a RawArtifactPolicy.")
        if self.correlation_id is not None:
            _validate_text(self.correlation_id, "correlation_id")
