"""APK signing via uber-apk-signer or apksigner, plus a signing verifier."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional

from . import toolbox


def sign_apk(
    apk: str,
    *,
    out_dir: Optional[str] = None,
    keystore: Optional[str] = None,
    ks_alias: Optional[str] = None,
    ks_pass: Optional[str] = None,
    ks_key_pass: Optional[str] = None,
    skip_zipalign: bool = True,
    overwrite: bool = False,
) -> str:
    """Sign *apk* and return the signed APK path.

    Defaults to a debug signature (fine for local/personal use).  When
    ``skip_zipalign`` is set, alignment is assumed to be already correct
    (16 KiB ``.so`` pages) and uber-apk-signer is told not to re-align.
    """
    java = toolbox.find_java()
    jar = toolbox.uber_apk_signer()
    apk = str(Path(apk).resolve())

    cmd: List[str] = [java, "-jar", str(jar), "-a", apk, "--allowResign"]
    if skip_zipalign:
        cmd.append("--skipZipAlign")
    if keystore:
        cmd += ["--ks", keystore, "--ksAlias", ks_alias or "androiddebugkey"]
        cmd += ["--ksPass", ks_pass or "android", "--ksKeyPass", ks_key_pass or ks_pass or "android"]
    if overwrite:
        cmd.append("--overwrite")
    if out_dir:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        cmd += ["-o", str(Path(out_dir).resolve())]

    proc = toolbox.run(cmd, check=False)
    if proc.returncode != 0:
        raise toolbox.ToolError("signing failed:\n%s" % (proc.stdout or ""))

    if overwrite:
        return apk
    target_dir = Path(out_dir) if out_dir else Path(apk).parent
    candidate = target_dir / (Path(apk).stem + "-aligned-signed.apk")
    if not candidate.exists():
        # uber-apk-signer sometimes drops the "-aligned" infix when not aligning
        for alt in target_dir.glob(Path(apk).stem + "-*signed.apk"):
            candidate = alt
            break
    if not candidate.exists():
        return apk
    return str(candidate)


def verify_apk(apk: str) -> str:
    java = toolbox.find_java()
    jar = toolbox.uber_apk_signer()
    proc = toolbox.run([java, "-jar", str(jar), "-a", str(apk), "-y", "--verbose"], check=False)
    return proc.stdout or ""
