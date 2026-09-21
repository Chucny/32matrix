"""32matrix - turn 32-bit-only APKs into installable wrappers for 64-bit devices.

Strategy "zettabridge": reuse the emulation runtime from a ZettaBridge wrapper
APK, swapping the bundled 32-bit guest for the APK you want to run.
Strategy "repackage": plain (re)packaging fixes for APKs that only need their
manifest / native library flags adjusted.
"""

__version__ = "0.1.0"

ZB_WRAPPER_PACKAGE = "com.zettabridge.launcher"
ZB_BUNDLED_ASSET = "assets/bundled/plugin.apk"
