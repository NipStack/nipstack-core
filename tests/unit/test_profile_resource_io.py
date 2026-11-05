"""Linux path confinement, bounded reads, observable races and descriptor lifetime."""

import errno
import os
import socket
from pathlib import Path

import pytest

from nipstack_core.profiles import _resources
from nipstack_core.profiles._resources import _open_root, _read_regular_file
from nipstack_core.profiles.loader import ProfileLoadError


def read(root_fd: int, reference: str, limit: int = 1024, components: int = 32) -> bytes:
    return _read_regular_file(root_fd, reference, max_bytes=limit, max_components=components)


def test_regular_and_empty_files_are_read_without_path_resolution(tmp_path: Path) -> None:
    directory = tmp_path / "resources"
    directory.mkdir()
    (directory / "é data").write_bytes(b"\xffopaque")
    (tmp_path / "empty").write_bytes(b"")
    with _open_root(tmp_path) as descriptor:
        assert read(descriptor, "resources/é data") == b"\xffopaque"
        assert read(descriptor, "empty", limit=0) == b""


@pytest.mark.parametrize("root", [Path("relative"), Path("/a/../b"), Path("//ambiguous"), "text"])
def test_root_must_be_an_explicit_absolute_path(root: object) -> None:
    with pytest.raises(ProfileLoadError) as failure:
        with _open_root(root):
            pytest.fail("Root must be rejected")
    assert failure.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize("parent_link", [False, True])
def test_root_and_parent_symlinks_are_rejected(tmp_path: Path, parent_link: bool) -> None:
    target = tmp_path / "real"
    (target / "profile").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(target if parent_link else target / "profile", target_is_directory=True)
    with pytest.raises(ProfileLoadError) as failure:
        with _open_root(link / "profile" if parent_link else link):
            pytest.fail("Symlink must be rejected")
    assert failure.value.code == "UNSAFE_PATH"


@pytest.mark.parametrize(
    "reference",
    ["../outside", "/absolute", "a/../b", "a//b", "./b", "a\\b", "~file", "$HOME/x", "a?b"],
)
def test_lexical_escapes_fail_before_reading(tmp_path: Path, reference: str) -> None:
    with _open_root(tmp_path) as descriptor:
        with pytest.raises(ProfileLoadError) as failure:
            read(descriptor, reference)
    assert failure.value.code == "UNSAFE_PATH"


@pytest.mark.parametrize("intermediate", [False, True])
def test_resource_symlinks_are_rejected(tmp_path: Path, intermediate: bool) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "data").write_bytes(b"data")
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "real" if intermediate else tmp_path / "real" / "data")
    with _open_root(tmp_path) as descriptor:
        with pytest.raises(ProfileLoadError) as failure:
            read(descriptor, "link/data" if intermediate else "link")
    assert failure.value.code == "UNSAFE_PATH"


@pytest.mark.parametrize("kind", ["directory", "fifo", "socket"])
def test_non_regular_files_fail_without_opening_the_leaf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    leaf = tmp_path / "special"
    connection = None
    if kind == "directory":
        leaf.mkdir()
    elif kind == "fifo":
        os.mkfifo(leaf)
    else:
        connection = socket.socket(socket.AF_UNIX)
        connection.bind(str(leaf))
    try:
        with _open_root(tmp_path) as descriptor:
            original = os.open

            def no_leaf(path, flags, *args, **kwargs):
                assert path != "special"
                return original(path, flags, *args, **kwargs)

            monkeypatch.setattr(os, "open", no_leaf)
            with pytest.raises(ProfileLoadError) as failure:
                read(descriptor, "special")
            assert failure.value.code == "UNSAFE_PATH"
    finally:
        if connection is not None:
            connection.close()


@pytest.mark.parametrize("size", [3, 4, 5])
def test_exact_file_byte_budget(tmp_path: Path, size: int) -> None:
    (tmp_path / "data").write_bytes(b"x" * size)
    with _open_root(tmp_path) as descriptor:
        if size > 4:
            with pytest.raises(ProfileLoadError) as failure:
                read(descriptor, "data", limit=4)
            assert failure.value.code == "RESOURCE_LIMIT"
        else:
            assert read(descriptor, "data", limit=4) == b"x" * size


def test_component_budget_counts_the_leaf(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "b").write_bytes(b"data")
    with _open_root(tmp_path) as descriptor:
        with pytest.raises(ProfileLoadError) as failure:
            read(descriptor, "a/b", components=1)
        assert failure.value.code == "RESOURCE_LIMIT"
        assert read(descriptor, "a/b", components=2) == b"data"


@pytest.mark.parametrize("substitution", ["symlink", "fifo", "regular"])
def test_leaf_substitution_between_stat_and_open_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, substitution: str
) -> None:
    leaf = tmp_path / "data"
    leaf.write_bytes(b"original")
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"changed")
    original = os.open
    with _open_root(tmp_path) as descriptor:

        def substitute(path, flags, *args, **kwargs):
            if path == "data":
                leaf.unlink()
                if substitution == "symlink":
                    leaf.symlink_to(replacement)
                elif substitution == "fifo":
                    os.mkfifo(leaf)
                else:
                    replacement.rename(leaf)
            return original(path, flags, *args, **kwargs)

        monkeypatch.setattr(os, "open", substitute)
        with pytest.raises(ProfileLoadError) as failure:
            read(descriptor, "data")
    assert failure.value.code in ("UNSAFE_PATH", "RESOURCE_CHANGED")


def test_intermediate_symlink_substitution_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / "directory"
    parent.mkdir()
    (parent / "data").write_bytes(b"data")
    original = os.open
    with _open_root(tmp_path) as descriptor:

        def substitute(path, flags, *args, **kwargs):
            if path == "directory":
                parent.rename(tmp_path / "moved")
                parent.symlink_to(tmp_path / "moved")
            return original(path, flags, *args, **kwargs)

        monkeypatch.setattr(os, "open", substitute)
        with pytest.raises(ProfileLoadError) as failure:
            read(descriptor, "directory/data")
    assert failure.value.code == "UNSAFE_PATH"


@pytest.mark.parametrize("change", ["grow", "rewrite", "truncate"])
def test_changes_during_read_are_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    leaf = tmp_path / "data"
    leaf.write_bytes(b"original")
    original = os.read
    changed = False

    def changing_read(descriptor: int, count: int) -> bytes:
        nonlocal changed
        data = original(descriptor, count)
        if not changed:
            changed = True
            metadata = leaf.stat()
            leaf.write_bytes(
                {"grow": b"larger content", "rewrite": b"replaced", "truncate": b""}[change]
            )
            os.utime(leaf, ns=(metadata.st_atime_ns, metadata.st_mtime_ns + 2_000_000_000))
        return data

    with _open_root(tmp_path) as descriptor:
        monkeypatch.setattr(os, "read", changing_read)
        with pytest.raises(ProfileLoadError) as failure:
            read(descriptor, "data")
    assert failure.value.code == "RESOURCE_CHANGED"


def test_growth_cannot_bypass_read_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    leaf = tmp_path / "data"
    leaf.write_bytes(b"1234")
    original = os.read
    calls: list[int] = []

    def growing_read(descriptor: int, count: int) -> bytes:
        calls.append(count)
        if len(calls) == 1:
            leaf.write_bytes(b"x" * 100)
        return original(descriptor, count)

    with _open_root(tmp_path) as descriptor:
        monkeypatch.setattr(os, "read", growing_read)
        with pytest.raises(ProfileLoadError) as failure:
            read(descriptor, "data", limit=4)
    assert failure.value.code == "RESOURCE_LIMIT"
    assert calls == [5]


@pytest.mark.parametrize("mode", ["success", "budget", "missing", "read_error", "caller_error"])
def test_all_descriptors_are_closed_on_every_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    (tmp_path / "directory").mkdir()
    (tmp_path / "directory" / "data").write_bytes(b"content")
    opened: list[int] = []
    original = os.open

    def tracked_open(path, flags, *args, **kwargs):
        descriptor = original(path, flags, *args, **kwargs)
        opened.append(descriptor)
        return descriptor

    def unreadable(*args, **kwargs):
        raise OSError(errno.EIO, "SYNTHETIC_PRIVATE")

    monkeypatch.setattr(os, "open", tracked_open)
    monkeypatch.setattr(os, "supports_dir_fd", os.supports_dir_fd | {tracked_open})
    try:
        with _open_root(tmp_path) as descriptor:
            if mode == "read_error":
                monkeypatch.setattr(os, "read", unreadable)
            read(
                descriptor,
                "missing" if mode == "missing" else "directory/data",
                limit=1 if mode == "budget" else 1024,
            )
            if mode == "caller_error":
                raise ValueError("Synthetic caller failure")
    except (ProfileLoadError, ValueError):
        assert mode != "success"
    else:
        assert mode == "success"
    assert opened
    for descriptor in opened:
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_unsupported_platform_fails_before_opening(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_resources.sys, "platform", "unsupported")

    def forbidden(*args, **kwargs):
        pytest.fail("Unsupported platform must not open files")

    monkeypatch.setattr(os, "open", forbidden)
    with pytest.raises(ProfileLoadError) as failure:
        with _open_root(tmp_path):
            pytest.fail("Unsupported platform must fail")
    assert failure.value.code == "UNSUPPORTED_PLATFORM"


@pytest.mark.parametrize("flag", ["O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK", "O_CLOEXEC"])
def test_missing_secure_primitive_has_no_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    monkeypatch.delattr(os, flag)
    with pytest.raises(ProfileLoadError) as failure:
        with _open_root(tmp_path):
            pytest.fail("Missing secure primitives must fail")
    assert failure.value.code == "UNSUPPORTED_PLATFORM"


def test_io_error_is_sanitized(tmp_path: Path) -> None:
    with _open_root(tmp_path) as descriptor:
        with pytest.raises(ProfileLoadError) as failure:
            read(descriptor, "SYNTHETIC_PRIVATE")
    assert failure.value.code == "IO_ERROR"
    assert "SYNTHETIC_PRIVATE" not in str(failure.value) + repr(failure.value)
    assert failure.value.__context__ is None
