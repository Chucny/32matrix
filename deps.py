"""Automated dependency installer for 32matrix (Windows / Linux / macOS).

Runnable directly in three ways:

  py -3 deps.py            # Windows
  python3 deps.py          # Linux / macOS
  32matrix deps            # through the regular CLI

What it installs:

  * Java (+ JRE)  - required for APK signing. Installed through the native
                    package manager: winget/scoop on Windows, Homebrew on
                    macOS, apt/dnf/yum/pacman/zypper/apk on Linux.
  * uber-apk-signer.jar - the bundled verifier, auto-downloaded to the cache.
  * adb (--adb)   - optional Android platform-tools for installs and device
                    probing.

It never touches Python itself (you are already running it), and zipalign is
covered by 32matrix's built-in aligner, so no Android SDK is required.

Run with --dry-run to preview every command without executing anything.
"""
from __future__ import annotations

import importlib.util
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

MIN_PYTHON = (3, 8)


def _os_name() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _is_root() -> bool:
    if os.name == "nt":
        return False
    return hasattr(os, "geteuid") and os.geteuid() == 0


def have(*names: str) -> Optional[str]:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def _java_home() -> Optional[Path]:
    home = os.environ.get("JAVA_HOME")
    if home:
        exe = Path(home) / "bin" / ("java.exe" if os.name == "nt" else "java")
        if exe.exists():
            return Path(home)
    return None


def _phpkg() -> Optional[str]:
    for name in ("apt-get", "dnf", "yum", "pacman", "zypper", "apk"):
        if have(name):
            return name
    return None


def _run(cmd: List[str], *, dry: bool, sudo: bool = False) -> int:
    effective = (["sudo"] + cmd) if (sudo and not _is_root()) else cmd
    print("  $ %s" % shlex.join(effective))
    if dry:
        return 0
    return subprocess.call(effective)


def _run_elevated(cmd: List[str], *, dry: bool) -> int:
    if os.name == "nt":
        return _run(cmd, dry=dry)
    return _run(cmd, dry=dry, sudo=True)


# --------------------------------------------------------------------------- #
# Install plans, per operating system.
# --------------------------------------------------------------------------- #

def _linux_plan(installer: str, packages: List[str]) -> List[List[str]]:
    base = {
        "apt-get": ["apt-get", "install", "-y", "%s"],
        "dnf": ["dnf", "install", "-y", "%s"],
        "yum": ["yum", "install", "-y", "%s"],
        "pacman": ["pacman", "-S", "--noconfirm", "--needed", "%s"],
        "zypper": ["zypper", "--non-interactive", "install", "%s"],
        "apk": ["apk", "add", "--no-cache", "%s"],
    }[installer]
    pre = [["apt-get", "update"]] if installer == "apt-get" else []
    return pre + [[p % pkg if "%s" in p else p for p in base] for pkg in packages]


LINUX_JAVA_PACKAGES = {
    "apt-get": ["openjdk-17-jre-headless", "default-jre-headless", "openjdk-21-jre-headless"],
    "dnf": ["java-17-openjdk-headless", "java-11-openjdk-headless", "java-21-openjdk-headless"],
    "yum": ["java-11-openjdk-headless", "java-17-openjdk-headless"],
    "pacman": ["jre17-openjdk-headless", "jre-openjdk-headless", "jdk17-openjdk"],
    "zypper": ["java-17-openjdk-headless", "java-11-openjdk-headless"],
    "apk": ["openjdk17-jre", "openjdk21-jre"],
}

LINUX_ADB_PACKAGES = {
    "apt-get": ["adb"],
    "dnf": ["android-tools"],
    "yum": ["android-tools"],
    "pacman": ["android-tools"],
    "zypper": ["android-tools"],
    "apk": ["android-tools"],
}


def _java_plans(os_name: str) -> List[List[str]]:
    if os_name == "windows":
        plans: List[List[str]] = []
        if have("winget"):
            plans.append([
                "winget", "install", "--id", "EclipseAdoptium.Temurin.21.JRE",
                "-e", "--silent",
                "--accept-package-agreements", "--accept-source-agreements",
            ])
        if have("scoop"):
            plans.append(["scoop", "install", "openjdk"])
        return plans
    if os_name == "macos":
        if have("brew"):
            return [["brew", "install", "--cask", "temurin"]]
        return []
    installer = _phpkg()
    if not installer:
        return []
    return _linux_plan(installer, LINUX_JAVA_PACKAGES[installer])


def _adb_plans(os_name: str) -> List[List[str]]:
    if os_name == "windows":
        plans: List[List[str]] = []
        if have("winget"):
            plans.append(["winget", "install", "--id", "Google.PlatformTools",
                          "-e", "--silent",
                          "--accept-package-agreements", "--accept-source-agreements"])
        if have("scoop"):
            plans.append(["scoop", "install", "platform-tools"])
        return plans
    if os_name == "macos":
        if have("brew"):
            return [["brew", "install", "android-platform-tools"]]
        return []
    installer = _phpkg()
    if not installer:
        return []
    return _linux_plan(installer, LINUX_ADB_PACKAGES[installer])


def _manually(what: str) -> None:
    print("  -> automatic install unavailable; install %s manually." % what)


# --------------------------------------------------------------------------- #
# Steps.
# --------------------------------------------------------------------------- #

def ensure_python() -> bool:
    print("[python]")
    version = (sys.version_info.major, sys.version_info.minor)
    if version >= MIN_PYTHON:
        print("  ok: Python %d.%d.%d" % sys.version_info[:3])
        return True
    print("  too old: Python %d.%d (< %d.%d). Upgrade Python and re-run this."
          % (version[0], version[1], MIN_PYTHON[0], MIN_PYTHON[1]))
    return False


def ensure_java(os_name: str, *, dry: bool) -> bool:
    print("[java]")
    if have("java", "java.exe"):
        print("  ok: %s" % have("java", "java.exe"))
        return True
    if _java_home():
        print("  ok: %s (JAVA_HOME)" % _java_home())
        return True
    print("  missing - installing via package manager:")
    ok = False
    for plan in _java_plans(os_name):
        if all(_run_elevated(cmd, dry=dry) == 0 for cmd in plan):
            if have("java", "java.exe") or _java_home():
                ok = True
                break
    if not ok:
        _manually("Java for signing (recommended: an Adoptium Temurin JRE, "
                  "https://adoptium.net) then set JAVA_HOME")
    return ok


def _toolbox():
    return importlib.import_module("32matrix.toolbox")


def ensure_signer(*, dry: bool) -> bool:
    print("[signer]")
    try:
        toolbox = _toolbox()
        cached = toolbox.cache_dir() / "uber-apk-signer.jar"
        if cached.exists() and cached.stat().st_size > 0:
            print("  ok: %s" % cached)
            return True
        if dry:
            print("  would download: %s" % toolbox.UBER_APK_SIGNER_URL)
            return True
        jar = toolbox.uber_apk_signer()
        print("  ok: %s" % jar)
        return True
    except Exception as exc:  # noqa: BLE001
        print("  failed: %s" % exc)
        _manually("uber-apk-signer.jar into %s" %
                  (os.environ.get("32MATRIX_HOME") or "~/.32matrix"))
        return False


def ensure_adb(os_name: str, *, dry: bool) -> bool:
    print("[adb (optional)]")
    toolbox = _toolbox()
    if toolbox.find_adb():
        print("  ok: %s" % toolbox.find_adb())
        return True
    print("  not found - installing platform-tools:")
    ok = False
    for plan in _adb_plans(os_name):
        if all(_run_elevated(cmd, dry=dry) == 0 for cmd in plan):
            if toolbox.find_adb():
                ok = True
                break
    if not ok:
        _manually("Android platform-tools (adb)")
    return ok


# --------------------------------------------------------------------------- #
# Entry point.
# --------------------------------------------------------------------------- #

def main(argv: Optional[List[str]] = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    import argparse
    p = argparse.ArgumentParser(prog="32matrix deps",
                                description="Install 32matrix dependencies for this OS.")
    p.add_argument("--dry-run", action="store_true", help="preview commands without running them")
    p.add_argument("--adb", action="store_true", help="also install Android platform-tools (adb)")
    p.add_argument("--os", choices=["auto", "windows", "macos", "linux"], default="auto",
                   help="target OS (for preview/testing)")
    args = p.parse_args(argv)

    os_name = _os_name() if args.os == "auto" else args.os
    print("32matrix deps              (target: %s)" % os_name)
    print("working directory: %s\n" % Path.cwd())

    results = [
        ("python", ensure_python()),
        ("java", ensure_java(os_name, dry=args.dry_run)),
        ("signer", ensure_signer(dry=args.dry_run)),
    ]
    if args.adb:
        results.append(("adb", ensure_adb(os_name, dry=args.dry_run)))

    if importlib.util.find_spec("32matrix"):
        toolbox = _toolbox()
        print("\nadb      : %s" % (toolbox.find_adb() or "not found (optional)"))
        print("zipalign : %s" % (toolbox.find_zipalign()
                                 or "not found (built-in 16 KiB aligner is used)"))

    print("\nsummary:")
    failed = 0
    for name, ok in results:
        print("  %-8s %s" % (name, "ok" if ok else "MISSING"))
        if not ok:
            failed += 1
    if failed and not args.dry_run:
        print("\nSome dependencies are still missing. Follow the printed hints, "
              "then run `32matrix doctor`.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())