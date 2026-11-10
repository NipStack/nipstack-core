"""Build private native RE2 prerequisites, then run one command with scoped build settings.

No system install, custom wheel publication or upstream patch is performed.
Requires a C++17 compiler (CC/CXX may select a private compiler), uv and Linux.
"""

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from urllib.request import urlopen

_SOURCES = (
    (
        "abseil",
        "https://codeload.github.com/abseil/abseil-cpp/tar.gz/"
        "d38452e1ee03523a208362186fd42248ff2609f6",
        "d1abe9da2003e6cbbd7619b0ced3e52047422f4f4ac6c66a9bef5d2e99fea837",
        "abseil-cpp-d38452e1ee03523a208362186fd42248ff2609f6",
    ),
    (
        "re2",
        "https://codeload.github.com/google/re2/tar.gz/refs/tags/2025-11-05",
        "87f6029d2f6de8aa023654240a03ada90e876ce9a4676e258dd01ea4c26ffd67",
        "re2-2025-11-05",
    ),
)
_BUILD_PACKAGES = (
    "cmake==3.31.6",
    "ninja==1.13.2",
    "pybind11==3.1.0",
    "setuptools==80.9.0",
    "wheel==0.45.1",
)


def _acquire(prefix: Path, url: str, digest: str, name: str) -> Path:
    archive_path = prefix / (name + ".tar.gz")
    with urlopen(url, timeout=60) as response:
        content = response.read(32 * 1024 * 1024 + 1)
    if len(content) > 32 * 1024 * 1024:
        raise RuntimeError("Native dependency archive exceeds its size limit.")
    if hashlib.sha256(content).hexdigest() != digest:
        raise RuntimeError("Native dependency archive checksum mismatch.")
    archive_path.write_bytes(content)
    with tarfile.open(archive_path) as archive:
        # Sources are pinned, but extraction must still be confined to the private prefix.
        for member in archive.getmembers():
            path = prefix / member.name
            safe_link = (
                member.issym()
                and not Path(member.linkname).is_absolute()
                and (path.parent / member.linkname).resolve().is_relative_to(prefix)
            )
            if not path.resolve().is_relative_to(prefix) or not (
                member.isfile() or member.isdir() or safe_link
            ):
                raise RuntimeError("Unsafe native dependency archive member.")
        archive.extractall(prefix, filter="data")
    return archive_path


def build_environment(prefix: Path) -> dict[str, str]:
    """Prepare a caller-owned prefix and return settings for one build subprocess."""
    if sys.platform != "linux" or platform.machine() != "x86_64":
        raise RuntimeError("This source bootstrap is qualified only on Linux x86-64.")
    compiler = os.environ.get("CXX", "c++")
    if shutil.which(compiler) is None or shutil.which("uv") is None:
        raise RuntimeError("A C++17 compiler and uv are required; no system install is attempted.")
    prefix.mkdir(parents=True, exist_ok=True)
    marker = prefix / "prepared.json"
    identity = {"sources": _SOURCES, "packages": _BUILD_PACKAGES, "compiler": compiler}
    expected = json.loads(json.dumps(identity))
    if marker.exists():
        if json.loads(marker.read_text()) != expected:
            raise RuntimeError("Native build prefix belongs to a different toolchain.")
    elif any(prefix.iterdir()):
        raise RuntimeError("Native build prefix must be empty or previously prepared by this tool.")

    tools = prefix / "tools"
    native = prefix / "native"
    environment = os.environ.copy()
    environment["UV_CACHE_DIR"] = str(prefix / "uv-cache")
    environment["TMPDIR"] = str(prefix / "tmp")
    Path(environment["TMPDIR"]).mkdir(exist_ok=True)

    def run(*command: str) -> None:
        subprocess.run(command, env=environment, cwd=prefix, check=True)

    if not marker.exists():
        run("uv", "venv", "--no-project", "--python", sys.executable, str(tools))
        run("uv", "pip", "install", "--python", str(tools / "bin/python"), *_BUILD_PACKAGES)
        environment["PATH"] = str(tools / "bin") + os.pathsep + environment["PATH"]
        for name, url, digest, directory in _SOURCES:
            _acquire(prefix, url, digest, name)
            arguments = [
                "cmake",
                "-S",
                str(prefix / directory),
                "-B",
                str(prefix / ("build-" + name)),
                "-G",
                "Ninja",
                "-DCMAKE_BUILD_TYPE=Release",
                "-DCMAKE_CXX_STANDARD=17",
                "-DCMAKE_POSITION_INDEPENDENT_CODE=ON",
                f"-DCMAKE_INSTALL_PREFIX={native}",
                f"-DCMAKE_CXX_COMPILER={shutil.which(compiler)}",
            ]
            if name == "abseil":
                arguments += ["-DABSL_BUILD_TESTING=OFF", "-DABSL_PROPAGATE_CXX_STD=ON"]
            else:
                arguments += [
                    f"-DCMAKE_PREFIX_PATH={native}",
                    "-DRE2_BUILD_TESTING=OFF",
                    "-DBUILD_SHARED_LIBS=ON",
                ]
            run(*arguments)
            run("cmake", "--build", str(prefix / ("build-" + name)), "--parallel", "2")
            run("cmake", "--install", str(prefix / ("build-" + name)))
        marker.write_text(json.dumps(expected, indent=2) + "\n")
    headers = subprocess.check_output(
        [str(tools / "bin/python"), "-c", "import pybind11; print(pybind11.get_include())"],
        text=True,
        cwd=prefix,
    ).strip()
    environment["PATH"] = str(tools / "bin") + os.pathsep + os.environ["PATH"]
    environment["CXXFLAGS"] = f"-I{native / 'include'} -I{headers} -std=c++17 " + os.environ.get(
        "CXXFLAGS", ""
    )
    environment["CPPFLAGS"] = f"-I{native / 'include'} " + os.environ.get("CPPFLAGS", "")
    environment["LDFLAGS"] = f"-L{native / 'lib'} -Wl,-rpath,{native / 'lib'} " + os.environ.get(
        "LDFLAGS", ""
    )
    environment["LDCXXSHARED"] = compiler + " -shared"
    environment["LDSHARED"] = compiler + " -shared"
    environment.pop("GITHUB_ACTIONS", None)
    environment.pop("UV_NO_CONFIG", None)
    return environment


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    command = arguments.command
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("A subprocess command is required after --.")
    prefix = arguments.prefix.resolve()
    repository = Path(__file__).resolve().parents[1]
    if prefix.is_relative_to(repository) or " " in str(prefix):
        parser.error("Use a private prefix outside the repository, without spaces.")
    environment = build_environment(prefix)
    subprocess.run(command, env=environment, check=True)


if __name__ == "__main__":
    main()
