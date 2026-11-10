import hashlib
import io
import json
import runpy
import tarfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "tools/re2_source.py"
HELPERS = runpy.run_path(str(SCRIPT))


def archive_bytes(name, *, symlink=False, target="/etc/passwd"):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        member = tarfile.TarInfo(name)
        if symlink:
            member.type = tarfile.SYMTYPE
            member.linkname = target
            archive.addfile(member)
        else:
            member.size = 3
            archive.addfile(member, io.BytesIO(b"abc"))
    return buffer.getvalue()


def acquire(content, prefix, monkeypatch, digest=None):
    function = HELPERS["_acquire"]
    monkeypatch.setitem(function.__globals__, "urlopen", lambda *a, **k: io.BytesIO(content))
    digest = digest or hashlib.sha256(content).hexdigest()
    return function(prefix, "https://example.invalid/archive", digest, "sample")


def test_source_extraction_checks_hash_and_confines_paths(tmp_path, monkeypatch):
    content = archive_bytes("source/file")
    acquire(content, tmp_path, monkeypatch)
    assert (tmp_path / "source/file").read_bytes() == b"abc"
    with pytest.raises(RuntimeError, match="checksum"):
        acquire(content, tmp_path, monkeypatch, digest="0" * 64)


@pytest.mark.parametrize("name", ["../outside", "/absolute"])
def test_source_archive_traversal_rejected(tmp_path, monkeypatch, name):
    with pytest.raises(RuntimeError, match="Unsafe"):
        acquire(archive_bytes(name), tmp_path, monkeypatch)


def test_source_archive_symlinks_rejected(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="Unsafe"):
        acquire(archive_bytes("link", symlink=True), tmp_path, monkeypatch)


def test_internal_upstream_license_symlink_preserved(tmp_path, monkeypatch):
    content = archive_bytes("source/python/LICENSE", symlink=True, target="../LICENSE")
    acquire(content, tmp_path, monkeypatch)
    assert (tmp_path / "source/python/LICENSE").is_symlink()


def test_missing_compiler_does_not_attempt_install(tmp_path, monkeypatch):
    function = HELPERS["build_environment"]
    monkeypatch.setattr(function.__globals__["shutil"], "which", lambda name: None)
    with pytest.raises(RuntimeError, match="no system install"):
        function(tmp_path / "prefix")
    assert not (tmp_path / "prefix").exists()


def test_build_environment_only_scopes_github_actions(tmp_path, monkeypatch):
    function = HELPERS["build_environment"]
    globals_ = function.__globals__
    identity = {
        "sources": HELPERS["_SOURCES"],
        "packages": HELPERS["_BUILD_PACKAGES"],
        "compiler": "test-cxx",
    }
    (tmp_path / "prepared.json").write_text(json.dumps(identity))
    monkeypatch.setenv("CXX", "test-cxx")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(globals_["shutil"], "which", lambda name: "/private/" + name)
    monkeypatch.setattr(globals_["subprocess"], "check_output", lambda *a, **k: "/headers\n")
    environment = function(tmp_path)
    assert "GITHUB_ACTIONS" not in environment
    assert globals_["os"].environ["GITHUB_ACTIONS"] == "true"
    assert "-I/headers" in environment["CXXFLAGS"]
    assert str(tmp_path / "native/lib") in environment["LDFLAGS"]
