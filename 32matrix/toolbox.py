"""External tool discovery, caching and small process helpers."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import List, Optional

UBER_APK_SIGNER_URL = (
    "https://github.com/patrickfav/uber-apk-signer/releases/download/"
    "v1.3.0/uber-apk-signer-1.3.0.jar"
)
APKTOOL_URL = (
    "https://github.com/iBotPeaches/Apktool/releases/download/"
    "v3.0.3/apktool_3.0.3.jar"
)


class ToolError(Exception):
    pass


def cache_dir() -> Path:
    env = os.environ.get("32MATRIX_HOME")
    base = Path(env) if env else Path.home() / ".32matrix"
    base.mkdir(parents=True, exist_ok=True)
    return base


def download(url: str, dest: Path, label: str = "") -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    print("   downloading %s" % (label or dest.name), file=sys.stderr)
    try:
        with urllib.request.urlopen(url, timeout=120) as resp, open(tmp, "wb") as fh:
            shutil.copyfileobj(resp, fh, 1 << 20)
    except Exception as exc:  # noqa: BLE001
        tmp.unlink(missing_ok=True)
        raise ToolError("download failed for %s: %s" % (url, exc)) from exc
    tmp.replace(dest)
    return dest


def uber_apk_signer() -> Path:
    jar = cache_dir() / "uber-apk-signer.jar"
    return download(UBER_APK_SIGNER_URL, jar, "uber-apk-signer")


def apktool() -> Path:
    jar = cache_dir() / "apktool.jar"
    return download(APKTOOL_URL, jar, "apktool")


def _which(*names: str) -> Optional[str]:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def _first_existing(paths) -> Optional[str]:
    for cand in paths:
        if cand and Path(cand).exists():
            return str(cand)
    return None


def _sdk_roots():
    for var in ("ANDROID_HOME", "ANDROID_SDK_ROOT", "ANDROID_SDK", "ANDROID_USER_HOME"):
        value = os.environ.get(var)
        if value:
            yield Path(value)


def find_java() -> str:
    home = os.environ.get("JAVA_HOME")
    if home:
        exe = Path(home) / "bin" / ("java.exe" if os.name == "nt" else "java")
        if exe.exists():
            return str(exe)
    found = _which("java", "java.exe")
    if found:
        return found
    raise ToolError(
        "java not found. Install a JDK (e.g. Temurin) or set JAVA_HOME; "
        "signing needs it."
    )


def find_apksigner() -> Optional[str]:
    return _which("apksigner", "apksigner.bat")


def find_zipalign() -> Optional[str]:
    return _which("zipalign", "zipalign.exe")


def find_adb() -> Optional[str]:
    found = _which("adb", "adb.exe")
    if found:
        return found
    exe = "adb.exe" if os.name == "nt" else "adb"
    candidates = [root / "platform-tools" / exe for root in _sdk_roots()]
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            candidates.append(Path(local) / "Android" / "Sdk" / "platform-tools" / "adb.exe")
    else:
        candidates += [
            Path.home() / "Android" / "Sdk" / "platform-tools" / "adb",
            Path("/usr/lib/android-sdk/platform-tools/adb"),
            Path("/usr/local/lib/android/sdk/platform-tools/adb"),
            Path("/opt/android-sdk/platform-tools/adb"),
            Path("/snap/bin/adb"),
            Path("/opt/homebrew/bin/adb"),
        ]
    return _first_existing(candidates)


def run(cmd: List[str], *, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.STDOUT if capture else None,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise ToolError("command not found: %s" % cmd[0]) from exc
    if check and proc.returncode != 0:
        raise ToolError(
            "command failed (%d): %s\n%s" % (proc.returncode, " ".join(cmd), proc.stdout or "")
        )
    return proc
