"""Exceptions for misuse of the public Python API."""


class NipStackCoreUsageError(ValueError):
    """A public contract received invalid values, rather than an operational failure."""
