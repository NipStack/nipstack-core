"""Linux descriptor-relative reads, without claiming an adversarial filesystem sandbox."""

import errno
import os
import stat
import sys
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

from nipstack_core.contracts.errors import NipStackCoreUsageError

from ._load_types import ProfileLoadError
from .features import _validate_resource_reference


def _check_platform() -> None:
    if (
        sys.platform != "linux"
        or os.open not in os.supports_dir_fd
        or os.stat not in os.supports_dir_fd
        or os.stat not in os.supports_follow_symlinks
        or not all(
            hasattr(os, flag) for flag in ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK", "O_CLOEXEC")
        )
    ):
        raise ProfileLoadError("UNSUPPORTED_PLATFORM")


@contextmanager
def _open_root(root: Path) -> Iterator[int]:
    if not isinstance(root, Path) or root.anchor != "/" or ".." in root.parts:
        raise ProfileLoadError("INVALID_ARGUMENT", field="root")
    _check_platform()
    try:
        with ExitStack() as descriptors:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
            descriptor = os.open("/", flags)
            descriptors.callback(os.close, descriptor)
            for component in root.parts[1:]:
                descriptor = os.open(component, flags, dir_fd=descriptor)
                descriptors.callback(os.close, descriptor)
            yield descriptor
    except OSError as error:
        failure = ProfileLoadError(
            "UNSAFE_PATH" if error.errno in (errno.ELOOP, errno.ENOTDIR) else "IO_ERROR"
        )
    else:
        return
    raise failure


def _signature(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _read_regular_file(
    root_fd: int,
    reference: str,
    *,
    max_bytes: int,
    max_components: int,
) -> bytes:
    try:
        _validate_resource_reference(reference, "resource")
    except NipStackCoreUsageError:
        raise ProfileLoadError("UNSAFE_PATH") from None
    components = reference.split("/")
    if len(components) > max_components:
        raise ProfileLoadError("RESOURCE_LIMIT")
    try:
        with ExitStack() as descriptors:
            parent = root_fd
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
            for component in components[:-1]:
                parent = os.open(component, flags, dir_fd=parent)
                descriptors.callback(os.close, parent)
            before_open = os.stat(components[-1], dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISREG(before_open.st_mode):
                raise ProfileLoadError("UNSAFE_PATH")
            descriptor = os.open(
                components[-1],
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                dir_fd=parent,
            )
            descriptors.callback(os.close, descriptor)
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise ProfileLoadError("UNSAFE_PATH")
            if _signature(before_open) != _signature(before):
                raise ProfileLoadError("RESOURCE_CHANGED")
            if before.st_size > max_bytes:
                raise ProfileLoadError("RESOURCE_LIMIT")
            content = bytearray()
            while True:
                chunk = os.read(descriptor, min(65_536, max_bytes - len(content) + 1))
                if not chunk:
                    break
                if len(content) + len(chunk) > max_bytes:
                    raise ProfileLoadError("RESOURCE_LIMIT")
                content.extend(chunk)
            after = os.fstat(descriptor)
            if _signature(before) != _signature(after) or len(content) != after.st_size:
                raise ProfileLoadError("RESOURCE_CHANGED")
            return bytes(content)
    except OSError as error:
        failure = ProfileLoadError(
            "UNSAFE_PATH" if error.errno in (errno.ELOOP, errno.ENOTDIR) else "IO_ERROR"
        )
    raise failure
