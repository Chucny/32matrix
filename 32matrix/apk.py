"""High level APK inspection: manifest facts, ABIs and native libraries."""
from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import axml

ABI_ORDER = ["arm64-v8a", "armeabi-v7a", "armeabi", "x86_64", "x86"]
ARM32_ABIS = {"armeabi", "armeabi-v7a"}
ARM64_ABI = "arm64-v8a"


@dataclass
class ApkInfo:
    path: str
    package: str = ""
    version_name: Optional[str] = None
    version_code: Optional[int] = None
    min_sdk: Optional[int] = None
    target_sdk: Optional[int] = None
    has_application: bool = False
    app_name: Optional[str] = None
    extract_native_libs: Optional[bool] = None
    launcher_activity: Optional[str] = None
    split_name: Optional[str] = None
    is_feature_split: bool = False
    abis: Dict[str, int] = field(default_factory=dict)
    native_libs: Dict[str, List[str]] = field(default_factory=dict)
    manifest_error: Optional[str] = None

    @property
    def abi_list(self) -> List[str]:
        return sorted(self.abis, key=lambda a: (ABI_ORDER.index(a) if a in ABI_ORDER else 99, a))

    @property
    def has_32bit(self) -> bool:
        return bool(ARM32_ABIS & set(self.abis))

    @property
    def has_64bit(self) -> bool:
        return ARM64_ABI in self.abis

    @property
    def is_split(self) -> bool:
        return bool(self.split_name) or self.is_feature_split

    @property
    def is_java_only(self) -> bool:
        return not self.abis

    def summary(self) -> str:
        bits = [
            "package   : %s" % (self.package or "?"),
            "version   : %s (%s)" % (self.version_name, self.version_code),
            "sdk       : min=%s target=%s" % (self.min_sdk, self.target_sdk),
            "abis      : %s" % (", ".join("%s(%d)" % (a, self.abis[a]) for a in self.abi_list) or "java only"),
            "launcher  : %s" % (self.launcher_activity or "none"),
            "extractNa : %s" % (self.extract_native_libs,),
            "split     : %s" % (self.split_name or ("feature" if self.is_feature_split else "no")),
        ]
        return "\n".join(bits)


def _find_launcher(manifest: axml.Element) -> Optional[str]:
    for app in manifest.find_all("application"):
        for comp in app.children:
            if comp.name not in ("activity", "activity-alias"):
                continue
            for f in comp.find_all("intent-filter"):
                actions = [a.get("android:name") for a in f.find_all("action")]
                cats = [c.get("android:name") for c in f.find_all("category")]
                if axml.ACTION_MAIN in actions and axml.CATEGORY_LAUNCHER in cats:
                    if comp.name == "activity-alias":
                        return comp.get("android:targetActivity") or comp.get("android:name")
                    return comp.get("android:name")
    return None


def read_apk_info(path: str, *, deep: bool = False) -> ApkInfo:
    info = ApkInfo(path=path)
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        for n in names:
            parts = n.split("/")
            if len(parts) == 3 and parts[0] == "lib" and parts[2]:
                info.abis[parts[1]] = info.abis.get(parts[1], 0) + 1
                info.native_libs.setdefault(parts[1], []).append(parts[2])
        try:
            manifest_bytes = z.read("AndroidManifest.xml")
        except KeyError:
            info.manifest_error = "AndroidManifest.xml missing"
            return info
        try:
            root = axml.parse_manifest(manifest_bytes)
        except Exception as exc:  # noqa: BLE001
            info.manifest_error = str(exc)
            return info

    if root.name != "manifest":
        info.manifest_error = "root element is <%s>, not <manifest>" % root.name
        return info

    info.package = root.get("package", "") or ""
    info.version_name = root.get("android:versionName")
    vc = root.get("android:versionCode")
    info.version_code = vc if isinstance(vc, int) else None
    info.split_name = root.get("split")
    info.is_feature_split = bool(root.get("android:isFeatureSplit"))
    # package may be hidden in an <manifest> attribute when using namespaces
    if not info.package:
        info.package = root.get_rid(axml.RID_NAME, "") or ""

    for el in root.children:
        if el.name == "uses-sdk":
            mn = el.get("android:minSdkVersion")
            tg = el.get("android:targetSdkVersion")
            info.min_sdk = mn if isinstance(mn, int) else None
            info.target_sdk = tg if isinstance(tg, int) else None
        elif el.name == "application":
            info.has_application = True
            info.app_name = el.get("android:label") or el.get("android:name")
            enl = el.get("android:extractNativeLibs")
            if isinstance(enl, bool):
                info.extract_native_libs = enl

    info.launcher_activity = _find_launcher(root)
    return info
