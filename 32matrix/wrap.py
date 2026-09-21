"""Wrapping strategies.

``wrap`` reuses the ZettaBridge emulation runtime: the template's bundled
32-bit guest is replaced with the target APK and the whole thing is re-aligned
and re-signed.  ``repackage`` is the fallback "install fixer": it re-packs an
APK with correct page alignment (for Android 15+ 16 KiB devices) and optionally
rewrites the manifest through apktool.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional

from . import ZB_BUNDLED_ASSET, ZB_WRAPPER_PACKAGE, zipx
from . import sign as signing
from . import toolbox
from .apk import ARM64_ABI, ApkInfo, read_apk_info


class WrapError(Exception):
    pass


def project_templates_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "templates"


def find_template(explicit: Optional[str] = None) -> str:
    """Locate a ZettaBridge wrapper APK to use as the runtime template."""
    candidates: List[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    env = os.environ.get("32MATRIX_TEMPLATE")
    if env:
        candidates.append(Path(env))
    candidates.append(project_templates_dir() / "zb.apk")
    cached = toolbox.cache_dir() / "zb-template.apk"
    candidates.append(cached)
    cwd = Path.cwd()
    candidates.extend(sorted(cwd.glob("*.apk")))

    seen = set()
    for cand in candidates:
        key = str(cand.resolve()) if cand.exists() else str(cand)
        if key in seen:
            continue
        seen.add(key)
        if not cand.exists():
            continue
        try:
            import zipfile

            with zipfile.ZipFile(cand) as z:
                names = set(z.namelist())
            if ZB_BUNDLED_ASSET not in names:
                continue
            info = read_apk_info(str(cand))
            if info.package == ZB_WRAPPER_PACKAGE:
                return str(cand)
        except Exception:  # noqa: BLE001
            continue
    raise WrapError(
        "no ZettaBridge template found. Pass --template <wrapper.apk>, set "
        "32MATRIX_TEMPLATE, or run '32matrix template slim <wrapper.apk>' once "
        "to produce the anonymous templates/zb.apk the tool auto-detects."
    )


def slim_template(
    src: str,
    out: str,
    *,
    page: int = zipx.SO_PAGE,
    placeholder: bytes = b"",
) -> str:
    """Strip the bundled 32-bit guest from *src*, producing a lean template.

    The result keeps only the emulation runtime (host library, sysroot, guest
    shims) and carries no bundled game/app payload. ``wrap`` inserts your guest
    into the empty bundle slot, so the shipped wrapper never contains the
    original template's bundled application.
    """
    entries = zipx.read_entries(src, page=page)
    entries = [e for e in entries if not zipx.is_signature_entry(e.name)]
    dummy = zipx.Entry(
        name=ZB_BUNDLED_ASSET,
        method=zipx.STORED,
        align=4,
        data=placeholder,
    )
    if not zipx.replace_entry(entries, ZB_BUNDLED_ASSET, dummy):
        entries.append(dummy)
    out = str(Path(out).resolve())
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    zipx.write_zip(out, entries)
    return out


def import_template(src: str, dest: Optional[str] = None) -> str:
    info = read_apk_info(src)
    if info.package != ZB_WRAPPER_PACKAGE:
        raise WrapError("%s is not a ZettaBridge wrapper (package=%s)" % (src, info.package))
    import zipfile

    with zipfile.ZipFile(src) as z:
        if ZB_BUNDLED_ASSET not in z.namelist():
            raise WrapError("%s has no %s" % (src, ZB_BUNDLED_ASSET))
    target = Path(dest) if dest else toolbox.cache_dir() / "zb-template.apk"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)
    return str(target)


def _validate_guest(guest: ApkInfo, force_translate: bool) -> Optional[str]:
    """Return a warning string, or raise WrapError for hard failures."""
    if guest.manifest_error:
        raise WrapError("cannot read guest manifest: %s" % guest.manifest_error)
    if guest.is_split:
        raise WrapError(
            "guest is a split APK (%s); split bundles are not supported by the "
            "runtime. Merge the splits into a single base APK first." % (guest.split_name or "feature split")
        )
    if not guest.has_application:
        raise WrapError("guest has no <application> element")
    if not guest.package:
        raise WrapError("guest has no package name")
    if guest.package == ZB_WRAPPER_PACKAGE:
        raise WrapError("guest is the wrapper itself; nothing to do")
    if not guest.launcher_activity:
        raise WrapError("guest has no launcher activity (MAIN/LAUNCHER); the runtime cannot start it")

    if guest.has_64bit and not guest.has_32bit:
        raise WrapError(
            "guest already ships arm64-v8a libraries; it is 64-bit and does not "
            "need wrapping."
        )
    if guest.has_64bit and guest.has_32bit:
        if not force_translate:
            raise WrapError(
                "guest ships both 32-bit and arm64 libraries. On a 64-bit-only "
                "device both are runnable but the runtime would pick arm64. Use "
                "--force-translate to drop the arm64 libraries and emulate the "
                "32-bit ones instead."
            )
        return "guest also had arm64-v8a libraries; they were removed (--force-translate)"
    if guest.is_java_only:
        return "guest has no native libraries; wrapping is unnecessary (it is already 64-bit safe)"
    return None


def wrap_apk(
    guest_path: str,
    out_path: str,
    *,
    template: Optional[str] = None,
    force_translate: bool = False,
    page: int = zipx.SO_PAGE,
    do_sign: bool = True,
    keystore: Optional[str] = None,
    ks_alias: Optional[str] = None,
    ks_pass: Optional[str] = None,
    ks_key_pass: Optional[str] = None,
    keep_temp: bool = False,
) -> str:
    template_path = find_template(template)
    guest = read_apk_info(guest_path)
    warn = _validate_guest(guest, force_translate)

    entries = zipx.read_entries(template_path, page=page)
    entries = zipx.drop_entries(entries, [e.name for e in entries if zipx.is_signature_entry(e.name)])
    if force_translate:
        entries = zipx.strip_abi(entries, ARM64_ABI)

    new_guest = zipx.make_entry(ZB_BUNDLED_ASSET, guest_path, method=zipx.STORED, page=page, align=4)
    if not zipx.replace_entry(entries, ZB_BUNDLED_ASSET, new_guest):
        entries.append(new_guest)

    out_path = str(Path(out_path).resolve())
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    tmpdir = Path(tempfile.mkdtemp(prefix="32matrix-"))
    tmp_apk = tmpdir / (Path(out_path).stem + ".unsigned.apk")
    try:
        zipx.write_zip(str(tmp_apk), entries)
        if do_sign:
            signed = signing.sign_apk(
                str(tmp_apk),
                keystore=keystore,
                ks_alias=ks_alias,
                ks_pass=ks_pass,
                ks_key_pass=ks_key_pass,
                overwrite=True,
            )
            shutil.move(signed, out_path)
        else:
            shutil.move(str(tmp_apk), out_path)
    finally:
        if not keep_temp:
            shutil.rmtree(tmpdir, ignore_errors=True)

    if warn:
        print("   note: %s" % warn)
    return out_path


def repackage_apk(
    apk_path: str,
    out_path: str,
    *,
    page: int = zipx.SO_PAGE,
    strip_abis: Optional[List[str]] = None,
    do_sign: bool = True,
    keep_temp: bool = False,
    **sign_kwargs,
) -> str:
    """Fallback strategy: re-align (and optionally trim) an APK, then sign it."""
    entries = zipx.read_entries(apk_path, page=page)
    entries = zipx.drop_entries(entries, [e.name for e in entries if zipx.is_signature_entry(e.name)])
    for abi in strip_abis or []:
        entries = zipx.strip_abi(entries, abi)

    out_path = str(Path(out_path).resolve())
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    tmpdir = Path(tempfile.mkdtemp(prefix="32matrix-"))
    tmp_apk = tmpdir / (Path(out_path).stem + ".unsigned.apk")
    try:
        zipx.write_zip(str(tmp_apk), entries)
        if do_sign:
            signed = signing.sign_apk(str(tmp_apk), overwrite=True, **sign_kwargs)
            shutil.move(signed, out_path)
        else:
            shutil.move(str(tmp_apk), out_path)
    finally:
        if not keep_temp:
            shutil.rmtree(tmpdir, ignore_errors=True)
    return out_path
