"""NipStack Core: network collection and structured observations.

Public APIs are introduced incrementally as the approved contracts are implemented.
"""

from .contracts import FeatureSelection, FeatureSelectionKind, NipStackCoreUsageError

__all__ = ["FeatureSelection", "FeatureSelectionKind", "NipStackCoreUsageError"]
