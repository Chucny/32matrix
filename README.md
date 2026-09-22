# 32matrix
---
### Build installable Android packages for 32-bit-only applications on 64-bit-only devices.
### Approximately 60%-85% of apps converted with 32matrix work.
---

> "Information wants to be free. History shows that trying to lock it down doesn't work." 
> — **Aaron Swartz**

---

## 🚫 The Backstory: Out-Coding the Gatekeepers

When you build something that breaks boundaries, the people who profit off gatekeeping will panic. 

While developing **32matrix**, a closed-source community project called "Kanto" (https://kanto.ac) was tryig to prevent me. When they realized they were out-engineered, their leadership completely lost their composure and dropped this unhinged threat:

```text
"Anyway I'm not arguing with a petulant child anymore
You've made ur mind up, you've ruined your reputation
And I never want to speak with you ever again.
Either get some mental health help, or off yourself before you're 18
Either option I don't care"
```

**They wanted to kill the project. Instead, I made it open source.** 

32matrix is the answer to closed-source gatekeeping. It is the first-ever open-source tool that handles 32-bit to 64-bit translation packaging seamlessly, making applications accessible to everyone on flagship devices without VPhoneOS or closed-source translation layers. 

Let the binaries be free.

Build installable Android packages for 32-bit-only applications on 64-bit-only
devices.
---
### Anyways, let's get into it.
32matrix is a cross-platform command-line tool that takes an APK built only for
the 32-bit ARM ABI (`armeabi` / `armeabi-v7a`) and produces a signed, correctly
aligned APK that installs and launches on hardware where 32-bit execution has
been removed (Snapdragon 8 Gen 1+, Google Tensor, Dimensity 9000+ and later).
It does not ship an emulator of its own: it packages your application so it can
run under an existing ARM32-to-ARM64 translation runtime, and it also exposes a
general-purpose APK repackaging/alignment tool.

```
$ 32matrix wrap yourapp.apk -o yourapp-wrapped.apk
$ adb install -r yourapp-wrapped.apk
```

---

## Contents

- [Overview](#overview)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Command reference](#command-reference)
- [How it works](#how-it-works)
- [Wrapping rules](#wrapping-rules)
- [Alignment and signing](#alignment-and-signing)
- [Configuration](#configuration)
- [Architecture](#architecture)
- [Troubleshooting](#troubleshooting)
- [Limitations and non-goals](#limitations-and-non-goals)
- [Security and legal](#security-and-legal)
- [Development](#development)
- [Acknowledgements](#acknowledgements)
- [License](#license)

---

## Overview

Modern Android flagships ship a 64-bit-only kernel and userspace: the `arm64-v8a`
ABI is the only supported target and the 32-bit runtime is absent. Applications
that contain only 32-bit native libraries therefore fail to install or crash with
`INSTALL_FAILED_NO_MATCHING_ABIS`.

Many such applications cannot simply be rebuilt, because their authors never
published a 64-bit artifact. 32matrix addresses this at the packaging layer:

- **wrap** — reuse an ARM32-to-ARM64 translation runtime and replace its bundled
  32-bit payload with your application, producing a ready-to-install wrapper.
- **repackage** — re-pack an APK with correct page alignment and optional ABI
  trimming, then re-sign it. This resolves a large class of installation
  failures on Android 15+ 16 KiB-page devices without any emulation.

32matrix is dependency-free (Python standard library only), runs on Windows,
Linux and macOS, and automates the external tooling it needs (signing) on first
use.

## Requirements

| Requirement | Needed for | Notes |
| --- | --- | --- |
| Python 3.9+ | everything | standard library only; no third-party packages |
| Java (JRE/JDK 8+) | `wrap`, `repackage`, `sign` | `uber-apk-signer` is downloaded automatically |
| `adb` | `device`, installing | optional; only for device probing |
| A translation runtime APK | `wrap` | see [Configuration](#configuration) |

## Installation

No packaging step is required. From a checkout:

```sh
# Linux / macOS
cd 32matrix
chmod +x 32matrix.sh
./32matrix.sh deps        # installs Java + the bundled signer for this OS
./32matrix.sh doctor
```

```bat
:: Windows (cmd or PowerShell)
cd 32matrix
32matrix.cmd deps         :: installs Java + the bundled signer for this OS
32matrix.cmd doctor
```

`deps` is idempotent: it skips what is already present and installs only what
is missing, through the native package manager (winget/scoop on Windows,
Homebrew on macOS, apt/dnf/yum/pacman/zypper/apk on Linux — `sudo` is used when
needed). It never installs Python itself and never needs an Android SDK.
Preview every command with `32matrix deps --dry-run`; get adb too with
`--adb`.

Optionally install as a console script:

```sh
pip install -e .
32matrix doctor
```

The launchers set `PYTHONPATH` only. They do **not** change the working
directory, so relative output paths remain relative to where you invoked them.

## Quick start

```sh
# 1. Verify the environment and locate a runtime template
./32matrix.sh doctor

# 2. Build the local slim template from a runtime you possess (once)
#    (strips the runtime's bundled app - the repo and your wrappers never ship it)
./32matrix.sh template slim /path/to/your-runtime.apk

# 3. Inspect the target application
./32matrix.sh inspect yourapp.apk

# 4. Build a wrapper
./32matrix.sh wrap yourapp.apk -o yourapp-wrapped.apk

# 5. Install
adb install -r yourapp-wrapped.apk
```

## Command reference

```
32matrix [--version] <command> ...
```

| Command | Purpose |
| --- | --- |
| `inspect` | Print package, SDK, ABI, native-library and launcher facts. |
| `wrap` | Build a translation wrapper around a 32-bit APK. |
| `repackage` | Re-align / trim / re-sign an APK (fallback). |
| `sign` | Sign an APK (debug key by default). |
| `verify` | Verify signature and alignment. |
| `device` | Probe a connected device's 32-bit support and page size. |
| `template` | Import, slim or locate the translation runtime. |
| `deps` | Install missing dependencies for this OS (Python extras, Java, signer, adb). |
| `doctor` | Validate dependencies and configuration. |

### `inspect`

```
32matrix inspect <apk> [--json] [--verify]
```

Recovers facts directly from the compiled `AndroidManifest.xml` (no `aapt`
required): package name, version, `minSdk`/`targetSdk`, `extractNativeLibs`,
split/App-Bundle status, the launcher activity, and every ABI with its native
libraries. `--json` emits machine-readable output.

### `wrap`

```
32matrix wrap <guest.apk> [-o OUT] [--template T] [--force-translate]
               [--page N] [--no-sign] [--keep-temp] [keystore options]
```

Produces a wrapper carrying your application. The output is page-aligned and
signed, ready for `adb install -r`. Without `-o`, the output is written **next
to your APK** as `<name>-wrapped.apk`.

### `repackage`

```
32matrix repackage <apk> [-o OUT] [--page N] [--strip-arm64 | --strip-arm32]
                    [--no-sign] [--keep-temp] [keystore options]
```

The fallback path, useful when the application is already arm64-capable or
Java-only but fails to install due to packaging problems. Without `-o`, the
output is written **next to the APK** as `<name>-repacked.apk`.

### `sign`, `verify`, `device`, `template`, `doctor`

```
32matrix sign <apk> [-o DIR] [--align] [--overwrite] [keystore options]
32matrix verify <apk>
32matrix device [--serial S] [--json]
32matrix template import <runtime.apk> [--dest P]
32matrix template slim <runtime.apk> [--dest P]   # strips the bundled app
32matrix template path [runtime.apk]
32matrix doctor [--template T]
```

### `deps`

```
32matrix deps [--dry-run] [--adb] [--os auto|windows|macos|linux]
```

Installs whatever this computer still needs, through the native package
manager and `sudo`/admin elevation when required. Java for signing comes from
winget or scoop (Windows), Homebrew (macOS) or apt/dnf/yum/pacman/zypper/apk
(Linux); the signing jar is downloaded into the cache automatically. `--adb`
adds Android platform-tools; `--dry-run` only prints the commands. Idempotent —
present tools are left alone. Verify afterwards with `doctor`.

Keystore options (accepted by `wrap`, `repackage`, `sign`):

| Flag | Description |
| --- | --- |
| `--keystore` | Keystore file. Omit to use a debug signature. |
| `--ks-alias` | Key alias inside the keystore. |
| `--ks-pass` | Keystore password. |
| `--ks-key-pass` | Key password (defaults to `--ks-pass`). |

A debug signature is appropriate for personal side-loading. Supply a release
keystore for distribution.

## How it works

On 64-bit-only hardware, 32-bit machine code cannot execute natively; a
translation layer is required. 32matrix does not reimplement one. Instead it
targets a runtime that already provides the required pieces — an ARM32
interpreter/JIT, a user-space ELF loader, a 32-bit bionic sysroot, and a
JNI/EGL/GLES bridge — and rewrites the single payload the runtime consumes.

The runtime used here ships as an installable wrapper APK. It contains:

- `lib/arm64-v8a/libzbridge.so` — the 64-bit host library (JIT, loader, syscalls),
- `assets/zb/sysroot/...` — a 32-bit bionic sysroot and `linker`,
- `assets/zb/host/libzbproxy.so` — the 64-bit proxy stub loaded under guest names,
- `assets/bundled/plugin.apk` — the bundled 32-bit guest.

On first launch the runtime imports `assets/bundled/plugin.apk` through the
Android package parser, extracts the guest's native libraries for the selected
ABI, and starts it under translation. Because the import path is
content-agnostic, 32matrix only needs to replace that one asset:

```
template APK  →  replace assets/bundled/plugin.apk  →  re-align  →  re-sign
```

Everything else — the 64-bit host library, sysroot, proxy and manifest — is
reused unchanged, so the wrapper package, its permissions, its stub activities
and its launch behaviour stay intact.

## Wrapping rules

`wrap` validates the guest before doing any work and fails early with an
actionable message when a wrapper cannot help:

| Condition | Result |
| --- | --- |
| Split APK / App Bundle | Rejected — merge to a single base APK first. |
| No `MAIN`/`LAUNCHER` activity | Rejected — the runtime cannot start it. |
| No `<application>` or package name | Rejected. |
| Guest is the runtime itself | Rejected. |
| arm64-only libraries | Rejected — already 64-bit; no wrapping needed. |
| Both 32-bit and arm64 libraries | Rejected unless `--force-translate` (drops arm64 libs and translates the 32-bit ones). |
| Java-only (no native libraries) | Warning — already 64-bit safe. |
| 32-bit only | Accepted. |

## Alignment and signing

32matrix writes the output ZIP itself rather than relying on the standard
library's `zipfile` writer, because Android requires precise entry alignment:

- every stored `.so` is aligned to a **16 KiB page** boundary (required on
  Android 15+ devices with 16 KiB pages; also valid on 4 KiB devices);
- other stored entries are aligned to 4 bytes;
- uncompressed entries stay uncompressed, so `resources.arsc` and native
  libraries can be mapped directly;
- any pre-existing signing block and `META-INF` signatures are discarded;
- the result is signed with APK Signature Scheme **v2 and v3**.

The bundled guest is copied byte-for-byte from disk, so multi-hundred-megabyte
payloads are never loaded into memory.

## Configuration

| Variable | Effect |
| --- | --- |
| `32MATRIX_TEMPLATE` | Path to the runtime template APK. |
| `32MATRIX_HOME` | Cache directory. Defaults to `~/.32matrix`. |

The template is resolved in this order: an explicit `--template` argument,
`32MATRIX_TEMPLATE`, the project's `templates/zb.apk`, the cache copy from
`template import`, then any `.apk` in the current directory. `templates/zb.apk`
is git-ignored: the public repository ships no runtime binaries.

`wrap` therefore works out of the box as soon as `templates/zb.apk` exists.

`template slim` creates that file from any runtime APK you possess. It removes
the bundled 32-bit application completely (shrinking e.g. a 164 MiB runtime to
~6 MiB), leaving only the emulation runtime. Your wrapper never contains the
template's original bundled app, because `wrap` fills that slot with your guest.

## Architecture

```
32matrix/
  pyproject.toml       packaging metadata and console entry point
  32matrix.cmd         Windows launcher
  32matrix.sh          Linux / macOS launcher
  deps.py              cross-platform dependency installer (deps command)
  templates/           local runtime template (git-ignored, see Configuration)
  32matrix/
    __main__.py        module entry point
    cli.py             argument parsing and command dispatch
    apk.py             manifest / ABI / launcher inspection
    axml.py            minimal binary AndroidManifest.xml parser
    zipx.py            alignment-aware ZIP reader / writer
    wrap.py            wrapping and repackaging strategies
    sign.py            uber-apk-signer / apksigner integration
    toolbox.py         dependency discovery, downloads, process helpers
    device.py          adb-backed device capability probe
```

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `java not found` | Install a JDK/JRE or set `JAVA_HOME`. |
| `no runtime template found` | Run `template slim <runtime.apk>` (or `template import` / pass `--template`). |
| `guest is a split APK` | Merge the App Bundle splits into one base APK. |
| `guest has no launcher activity` | The app has no `MAIN`/`LAUNCHER` entry to start. |
| `guest already ships arm64-v8a` | Nothing to do; install as-is. |
| Install fails with `INSTALL_FAILED_NO_MATCHING_ABIS` after `wrap` | The guest still contains arm64 libs; retry with `--force-translate`. |
| Network blocked during first `sign` | Pre-download `uber-apk-signer` into the cache directory or sign externally. |

## Limitations and non-goals

- There is no free, drop-in mechanism to convert arbitrary 32-bit machine code
  into 64-bit machine code. On 64-bit-only CPUs, translation is mandatory, and
  this tool relies on an existing translation runtime rather than providing one.
- Translated workloads run slower than native code. GPU-heavy or highly
  optimized native code may stutter or misbehave.
- Applications with anti-tamper or anti-emulation checks (banking, some games)
  may refuse to run in a translated environment.
- `repackage` does not edit `AndroidManifest.xml`; it corrects alignment and ABI
  packaging only.
- `wrap` is validated for packaging, alignment and signing. Behaviour of a
  specific guest inside the translation runtime cannot be guaranteed and must be
  tested on the target device.

## Security and legal

- Use 32matrix only for applications you are legally entitled to run and
  modify.
- Debug-signed outputs are for personal use. For distribution, sign with your
  own release key.
- The translation runtime reused by `wrap` is third-party software and remains
  subject to its own license. 32matrix neither ships nor relicenses it.
- The public repository ships **no runtime binaries** and **no runtime-bundled
  application**. The runtime you generate locally with `template slim` stays
  outside git (`templates/*.apk` is ignored) and produces wrappers whose only
  bundled payload is your own guest APK. This keeps the project redistribution-
  safe for both the runtime's authors and any application bundled inside it.

## Development

```sh
git clone <repo>
cd 32matrix
python3 -m 32matrix --help      # run from source, no install required
python3 -m compileall 32matrix  # syntax check
```

Design notes:

- `zipx.py` owns all binary ZIP layout. Treat its alignment logic as the
  correctness-critical core and cover changes with round-trip tests.
- `axml.py` is intentionally a subset parser; keep it dependency-free.
- New strategies belong in `wrap.py` behind the same validation and reporting
  conventions as the existing ones.

## Acknowledgements

- The ARM32-to-ARM64 translation runtime and the wrapper package format belong
  to their respective authors.
- [uber-apk-signer](https://github.com/patrickfav/uber-apk-signer) — signing and
  verification.
- [Apktool](https://github.com/iBotPeaches/Apktool) — optional manifest work.

## License

32matrix source is released under the **GNU General Public License v3.0
(GPL-3.0)** — strong copyleft. Anyone who distributes or modifies the code must
keep it under GPL-3.0, keep your copyright notices intact, and make the
corresponding source code available on request.

Third-party components, including any translation runtime you supply, keep
their original licenses; GPL-3.0 applies to 32matrix's own code. See the
[LICENSE](LICENSE) file for the full text.
