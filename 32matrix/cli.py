"""32matrix command line interface."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, ZB_BUNDLED_ASSET, ZB_WRAPPER_PACKAGE, zipx
from . import device as devmod
from . import sign as signing
from . import toolbox
from . import wrap as wrapmod
from .apk import read_apk_info


def _print_info(info) -> None:
    print(info.summary())
    if info.native_libs:
        print("native libs:")
        for abi in info.abi_list:
            libs = info.native_libs.get(abi, [])
            print("  %-12s %d libs: %s" % (abi, len(libs), ", ".join(sorted(libs)[:6]) + ("..." if len(libs) > 6 else "")))


def cmd_inspect(args) -> int:
    info = read_apk_info(args.apk)
    if args.json:
        payload = {
            "path": info.path,
            "package": info.package,
            "versionName": info.version_name,
            "versionCode": info.version_code,
            "minSdk": info.min_sdk,
            "targetSdk": info.target_sdk,
            "abis": info.abi_list,
            "nativeLibs": info.native_libs,
            "has32bit": info.has_32bit,
            "has64bit": info.has_64bit,
            "launcherActivity": info.launcher_activity,
            "extractNativeLibs": info.extract_native_libs,
            "split": info.split_name,
            "isFeatureSplit": info.is_feature_split,
            "manifestError": info.manifest_error,
            "isZettaBridgeWrapper": info.package == ZB_WRAPPER_PACKAGE,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_info(info)
        if args.verify and Path(args.apk).exists():
            print(signing.verify_apk(args.apk))
    return 0


def cmd_wrap(args) -> int:
    out = args.out or str(Path(args.guest).with_name(Path(args.guest).stem + "-wrapped.apk"))
    print("32matrix: wrapping %s" % args.guest)
    info = read_apk_info(args.guest)
    _print_info(info)
    print("template : %s" % wrapmod.find_template(args.template))
    result = wrapmod.wrap_apk(
        args.guest,
        out,
        template=args.template,
        force_translate=args.force_translate,
        page=args.page,
        do_sign=not args.no_sign,
        keystore=args.keystore,
        ks_alias=args.ks_alias,
        ks_pass=args.ks_pass,
        ks_key_pass=args.ks_key_pass,
        keep_temp=args.keep_temp,
    )
    print("wrote    : %s" % result)
    if not args.no_sign:
        print("install  : adb install -r \"%s\"" % result)
    return 0


def cmd_repackage(args) -> int:
    out = args.out or str(Path(args.apk).with_name(Path(args.apk).stem + "-repacked.apk"))
    print("32matrix: repackaging %s (page=%d)" % (args.apk, args.page))
    strip = []
    if args.strip_arm64:
        strip.append("arm64-v8a")
    if args.strip_arm32:
        strip += ["armeabi-v7a", "armeabi"]
    result = wrapmod.repackage_apk(
        args.apk,
        out,
        page=args.page,
        strip_abis=strip,
        do_sign=not args.no_sign,
        keep_temp=args.keep_temp,
        keystore=args.keystore,
        ks_alias=args.ks_alias,
        ks_pass=args.ks_pass,
        ks_key_pass=args.ks_key_pass,
    )
    print("wrote    : %s" % result)
    return 0


def cmd_sign(args) -> int:
    result = signing.sign_apk(
        args.apk,
        out_dir=args.out,
        keystore=args.keystore,
        ks_alias=args.ks_alias,
        ks_pass=args.ks_pass,
        ks_key_pass=args.ks_key_pass,
        skip_zipalign=not args.align,
        overwrite=args.overwrite,
    )
    print("signed   : %s" % result)
    return 0


def cmd_verify(args) -> int:
    print(signing.verify_apk(args.apk))
    return 0


def cmd_device(args) -> int:
    report = devmod.device_report(args.serial)
    if args.json:
        print(devmod.dump(report))
    else:
        for k, v in report.items():
            print("%-28s %s" % (k, v))
        print("\n" + devmod.classify(report))
    return 0


def cmd_template(args) -> int:
    if args.action == "import":
        dest = wrapmod.import_template(args.apk, args.dest)
        print("imported : %s" % dest)
    elif args.action == "slim":
        if not args.apk:
            print("error: template slim requires a source runtime APK", file=sys.stderr)
            return 2
        dest = args.dest or (wrapmod.project_templates_dir() / "zb.apk")
        result = wrapmod.slim_template(args.apk, str(dest))
        print("slimmed  : %s" % result)
        print("note     : bundled guest removed; runtime kept (runtime binaries ")
        print("           are third-party and are NOT committed to the repo).")
    else:
        print(wrapmod.find_template(args.apk))
    return 0


def cmd_deps(args) -> int:
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import deps as depsmod
    extra = ["--os", args.os]
    if args.dry_run:
        extra.append("--dry-run")
    if args.adb:
        extra.append("--adb")
    return depsmod.main(extra)


def cmd_doctor(args) -> int:
    problems = 0
    try:
        print("java     : %s" % toolbox.find_java())
    except toolbox.ToolError as exc:
        problems += 1
        print("java     : MISSING (%s)" % exc)
    adb = toolbox.find_adb()
    print("adb      : %s" % (adb or "not found (device probing disabled)"))
    zipalign = toolbox.find_zipalign()
    print("zipalign : %s" % (zipalign or "not found (using built-in 16 KiB aligner)"))
    try:
        jar = toolbox.uber_apk_signer()
        print("signer   : %s" % jar)
    except toolbox.ToolError as exc:
        problems += 1
        print("signer   : MISSING (%s)" % exc)
    try:
        print("template : %s" % wrapmod.find_template(args.template))
    except wrapmod.WrapError as exc:
        print("template : not found (%s)" % exc)
        problems += 1
    return 1 if problems else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="32matrix",
        description="Wrap or repackage 32-bit APKs so they run on 64-bit-only Android devices.",
    )
    p.add_argument("--version", action="version", version="32matrix %s" % __version__)
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("inspect", help="show package, SDK, ABI and native lib facts")
    sp.add_argument("apk")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--verify", action="store_true", help="also verify the APK signature")
    sp.set_defaults(func=cmd_inspect)

    sp = sub.add_parser("wrap", help="wrap a 32-bit APK with the ZettaBridge runtime")
    sp.add_argument("guest")
    sp.add_argument("-o", "--out")
    sp.add_argument("--template", help="ZettaBridge wrapper APK to reuse")
    sp.add_argument("--force-translate", action="store_true", help="drop arm64 libs so 32-bit is emulated")
    sp.add_argument("--page", type=int, default=zipx.SO_PAGE, help="page size for .so alignment (default 16384)")
    sp.add_argument("--no-sign", action="store_true")
    sp.add_argument("--keystore")
    sp.add_argument("--ks-alias")
    sp.add_argument("--ks-pass")
    sp.add_argument("--ks-key-pass")
    sp.add_argument("--keep-temp", action="store_true")
    sp.set_defaults(func=cmd_wrap)

    sp = sub.add_parser("repackage", help="fallback: re-align/trim an APK and sign it")
    sp.add_argument("apk")
    sp.add_argument("-o", "--out")
    sp.add_argument("--page", type=int, default=zipx.SO_PAGE)
    sp.add_argument("--strip-arm64", action="store_true")
    sp.add_argument("--strip-arm32", action="store_true")
    sp.add_argument("--no-sign", action="store_true")
    sp.add_argument("--keystore")
    sp.add_argument("--ks-alias")
    sp.add_argument("--ks-pass")
    sp.add_argument("--ks-key-pass")
    sp.add_argument("--keep-temp", action="store_true")
    sp.set_defaults(func=cmd_repackage)

    sp = sub.add_parser("sign", help="sign an APK (debug keystore by default)")
    sp.add_argument("apk")
    sp.add_argument("-o", "--out", help="output directory")
    sp.add_argument("--align", action="store_true", help="let the signer zipalign too")
    sp.add_argument("--overwrite", action="store_true")
    sp.add_argument("--keystore")
    sp.add_argument("--ks-alias")
    sp.add_argument("--ks-pass")
    sp.add_argument("--ks-key-pass")
    sp.set_defaults(func=cmd_sign)

    sp = sub.add_parser("verify", help="verify an APK signature")
    sp.add_argument("apk")
    sp.set_defaults(func=cmd_verify)

    sp = sub.add_parser("device", help="probe a connected device's 32/64-bit support")
    sp.add_argument("--serial")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_device)

    sp = sub.add_parser("template", help="import, slim, or locate the runtime template")
    sp.add_argument("action", nargs="?", choices=["import", "slim", "path"], default="path")
    sp.add_argument("apk", nargs="?")
    sp.add_argument("--dest", help="where to write the imported/slimmed template")
    sp.set_defaults(func=cmd_template)

    sp = sub.add_parser("deps", help="install dependencies for this OS (Java, signer, adb)")
    sp.add_argument("--dry-run", action="store_true", help="preview commands without running them")
    sp.add_argument("--adb", action="store_true", help="also install Android platform-tools (adb)")
    sp.add_argument("--os", choices=["auto", "windows", "macos", "linux"], default="auto",
                    help="target OS (for preview/testing)")
    sp.set_defaults(func=cmd_deps)

    sp = sub.add_parser("doctor", help="check external dependencies and the template")
    sp.add_argument("--template")
    sp.set_defaults(func=cmd_doctor)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (wrapmod.WrapError, toolbox.ToolError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
