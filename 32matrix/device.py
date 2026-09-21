"""Device capability probing over adb (useful to pick the right strategy)."""
from __future__ import annotations

import json
from typing import Dict, Optional

from . import toolbox

PROPS = [
    "ro.product.model",
    "ro.product.manufacturer",
    "ro.build.version.release",
    "ro.build.version.sdk",
    "ro.product.cpu.abilist",
    "ro.product.cpu.abilist32",
    "ro.product.cpu.abilist64",
    "ro.product.cpu.pagesize",
    "ro.product.cpu.pagesize.64",
    "ro.debuggable",
    "ro.build.type",
]


def _getprop(adb: str, serial: Optional[str], key: str) -> str:
    cmd = [adb]
    if serial:
        cmd += ["-s", serial]
    cmd += ["shell", "getprop", key]
    proc = toolbox.run(cmd, check=False)
    return (proc.stdout or "").strip()


def device_report(serial: Optional[str] = None) -> Dict[str, str]:
    adb = toolbox.find_adb()
    if not adb:
        raise toolbox.ToolError("adb not found on PATH; install platform-tools to probe a device")
    if serial is None:
        proc = toolbox.run([adb, "devices"], check=False)
        lines = [l for l in (proc.stdout or "").splitlines()[1:] if l.strip()]
        if len(lines) != 1:
            raise toolbox.ToolError(
                "expected exactly one adb device, found %d. Use --serial." % len(lines)
            )
        serial = lines[0].split()[0]
    report = {"serial": serial, "adb": adb}
    for key in PROPS:
        report[key] = _getprop(adb, serial, key)
    return report


def classify(report: Dict[str, str]) -> str:
    abilist64 = report.get("ro.product.cpu.abilist64", "")
    abilist32 = report.get("ro.product.cpu.abilist32", "")
    sdk = report.get("ro.build.version.sdk", "")
    lines = []
    if "arm64" in abilist64:
        lines.append("device is 64-bit ARM")
    if abilist32:
        lines.append("device still supports 32-bit: %s" % abilist32)
    else:
        lines.append("device is 64-bit only (no 32-bit support) -> translation required")
    try:
        if int(sdk) >= 35:
            lines.append("Android 15+ : native libraries should be 16 KiB page aligned")
    except ValueError:
        pass
    return "\n".join(lines)


def dump(report: Dict[str, str]) -> str:
    return json.dumps(report, indent=2, sort_keys=True)
