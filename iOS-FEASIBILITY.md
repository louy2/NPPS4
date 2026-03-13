# iOS Self-Contained Experience: Feasibility Analysis

## Executive Summary

Providing a self-contained NPPS4 experience on iOS via AltStore is **feasible using a merged single-IPA architecture** — the NPPS4 Python server is injected directly into the patched SIF game client, running in-process alongside the game. This solves the critical iOS limitation where background apps are killed after ~30 seconds.

The approach uses:
- **BeeWare's Python-Apple-support** to embed CPython as a framework in the game IPA
- **Dylib injection** (`optool` + `__attribute__((constructor))`) to bootstrap the Python server before the game's `main()` runs
- **`cryptography` (pyca)** replacing `pycryptodomex` (iOS wheels already available)
- **Cross-compiled `pydantic-core`** via maturin's iOS support

The two binary dependencies are the critical blockers, but both have viable solutions:
- **`pycryptodomex`**: Replace with `cryptography` (pyca), which already has [iOS wheels built by BeeWare](https://beeware.org/news/buzz/november-2025-status-update/). All crypto operations used by NPPS4 have direct equivalents.
- **`pydantic-core`**: [Maturin gained iOS support in v1.7.0](https://github.com/PyO3/maturin/releases/tag/v1.7.0), but [pydantic-core has not yet published iOS wheels](https://github.com/pydantic/pydantic-core/issues/1170). The wheel must be built from source using maturin's iOS cross-compilation.

**Effort estimate: 2-3 person-months** for the merged single-IPA approach targeting AltStore distribution.

---

## How Android Works Today

The Android self-contained experience uses:

1. **Chaquopy** — a Gradle plugin that embeds CPython into an Android app. The native Android (Java/Kotlin) app starts the Python server via `android_main.py`.
2. **Server binds to `127.0.0.1:51376`** — only accessible on-device (loopback).
3. **Patched game client** — a modified APK that points to the local server instead of the official one. The client patcher at `ethanaobrien.github.io/sif-patcher/` supports both iOS and Android clients.
4. **SQLite database** — the server's default storage, requiring no external database server.
5. The Android app provides lifecycle management: `setup_server()`, `start_server()`, `stop_server()`, and database import/export.

---

## iOS Platform: What Works and What Doesn't

### CPython Official iOS Support (PEP 730)

**iOS is an officially supported CPython platform since Python 3.13** (October 2024, [Tier 3](https://peps.python.org/pep-0730/)). This is a major enabler. BeeWare's [Python-Apple-support](https://github.com/beeware/Python-Apple-support) provides **pre-built binaries of standard CPython** (3.10–3.14) as `Python.xcframework` bundles ready to embed in Xcode projects. [Briefcase](https://briefcase.beeware.org/) automates downloading these binaries, bundling your Python code, and generating the Xcode project. In short: we embed CPython 3.14, using BeeWare's tooling to build and package it.

Key constraints of CPython on iOS:
- Python runs in **embedded mode only** — `libPython` must be linked into a native iOS app; you call `Py_Initialize()` from Swift/ObjC
- **`fork()` and `spawn()` do not work** — `subprocess` and `multiprocessing` raise `PermissionError`. The server must run fully in-process (NPPS4's `android_main.py` already does this)
- All `.so` binary modules must be converted into individually signed `.framework` bundles inside `Frameworks/` (Briefcase handles this automatically)
- Embedding adds **~100 MB** to app size
- Apple permits interpreted code only if **bundled with the app**, not downloaded at runtime

### Prior Art: Pyto (App Store proof)

[Pyto](https://github.com/ColdGrub1384/Pyto) is a full Python IDE on the App Store — **proof that Apple accepts embedded CPython**. It bundles Python via BeeWare's Python-Apple-support, includes NumPy/Pandas/scikit-learn as pre-compiled frameworks, and uses Rubicon-ObjC to bridge Python↔iOS APIs.

---

## iOS Tooling Landscape (as of early 2026)

### BeeWare / Briefcase (Recommended)

[BeeWare's Python-Apple-support](https://github.com/beeware/Python-Apple-support) provides pre-compiled `Python.xcframework` bundles for iOS. Available for Python 3.10 through 3.14 (latest builds: January 2026). [Briefcase](https://briefcase.beeware.org/en/v0.3.16/reference/platforms/iOS.html) generates Xcode projects from Python apps.

Key milestones reached:
- **CPython 3.13+**: iOS is Tier 3 supported per [PEP 730](https://peps.python.org/pep-0730/)
- **pip 24.3**: Supports iOS platform tags
- **PyPI**: Accepts iOS wheel uploads (enabled 2025)
- **cibuildwheel**: Supports iOS builds
- **iOS wheels for `cryptography`**: [Built by BeeWare](https://beeware.org/news/buzz/november-2025-status-update/) (Rust-based, via maturin)
- **[Mobile wheel tracking](https://beeware.org/mobile-wheels/)**: Covers top 360 binary packages
- **Debugger support**: PDB and VSCode debugging work on iOS (November 2025)

Swift-Python bridge options:
- **[PythonKit](https://github.com/pvieito/PythonKit)** — Swift framework that dynamically loads libPython, provides Pythonic Swift API (`let sys = Python.import("sys")`). Demonstrated working on iOS in the [BeeSwift project](https://github.com/radcli14/BeeSwift)
- **[Rubicon-ObjC](https://rubicon-objc.readthedocs.io/)** — Bridge from Python side to ObjC/Swift APIs (used by Pyto)
- **Direct C API** — Call `Py_Initialize()`, `PyRun_SimpleString()` etc. from Swift

### Kivy / python-for-ios (Alternative)

[kivy-ios](https://github.com/kivy/kivy-ios) (latest: 2025.5.17) provides a recipe-based toolchain. No pycryptodome recipe exists ([issue #701](https://github.com/kivy/kivy-ios/issues/701), [issue #755](https://github.com/kivy/kivy-ios/issues/755)). The cross-compilation environment sets the C compiler to `/bin/false`, causing C extension builds to fail. Less suitable than BeeWare for a non-Kivy server app.

### Maturin / PyO3 iOS support

[Maturin v1.7.0 added initial iOS support](https://github.com/PyO3/maturin/issues/1742). v1.10+ adds PEP 730-compliant wheel naming and iOS cross-platform venv support. Rust-based Python packages (like pydantic-core) can be cross-compiled for iOS using this toolchain.

### AltStore Distribution

AltStore installs IPAs via sideloading. Key facts:
- App must be a standard IPA file
- **AltStore Classic** (worldwide): Re-signing every 7 days (free Apple ID), or 1 year ($99/yr developer account). Requires AltServer on Mac/PC as companion
- **AltStore PAL** (EU/Japan, iOS 17.4+): Apple-notarized, no re-signing. Now free (was EUR 1.50/yr). Developers submit apps through AltStore PAL's process
- **TrollStore** (iOS 14.0-16.6.1): Permanent install, no re-signing, no companion needed
- No App Store review guidelines apply — embedded interpreters are fine

AltStore sources use a [JSON format](https://faq.altstore.io/developers/make-a-source) for app distribution:
```json
{
  "name": "NPPS4",
  "identifier": "com.example.npps4",
  "apiVersion": "v2",
  "apps": [{
    "name": "NPPS4 Server",
    "bundleIdentifier": "com.example.npps4",
    "versions": [{
      "version": "1.0",
      "downloadURL": "https://.../npps4.ipa",
      "size": 12345678,
      "minOSVersion": "16.0"
    }]
  }]
}
```

---

## Deep Dive: The Two Binary Dependencies

### 1. `pycryptodomex` → Replace with `cryptography` (pyca)

**Status**: No iOS wheels exist for pycryptodomex. [No kivy-ios recipe](https://github.com/kivy/kivy-ios/issues/701). Cross-compilation has [known issues](https://github.com/kivy/kivy-ios/issues/755). Furthermore, iOS [does not allow dynamically loaded `.so` files](https://github.com/beeware/Python-Apple-support/issues/56) — C extensions must be compiled as static libraries (`.a`) and linked into the app binary, making a naive cross-compile insufficient.

**Solution**: Replace with [`cryptography`](https://cryptography.io/) (pyca), which **already has iOS wheels** built by BeeWare (with the static linking problem solved). This is also a more actively maintained library.

#### NPPS4 Crypto Operations Inventory

From analyzing the codebase, NPPS4 uses exactly these Cryptodome operations:

**`npps4/util.py`** — core request/response crypto:
```
Cryptodome.Hash.SHA1          — SHA1 hashing for message signing
Cryptodome.Signature.pkcs1_15 — RSA PKCS1v1.5 signature (sign with server RSA key)
Cryptodome.Cipher.PKCS1_v1_5  — RSA PKCS1v1.5 decryption (decrypt client messages)
Cryptodome.Cipher.AES         — AES-CBC decryption (decrypt client payloads)
Cryptodome.Util.Padding       — PKCS7 unpadding (used with AES-CBC, but code does manual unpadding)
```

**`npps4/data/schema.py`** — serial code encryption:
```
Cryptodome.Hash.SHA256         — SHA256 for PBKDF2
Cryptodome.Protocol.KDF.PBKDF2 — Key derivation for serial codes
Cryptodome.Cipher.AES          — AES-CTR encryption/decryption
```

**`npps4/config/config.py`** — key loading:
```
Cryptodome.PublicKey.RSA       — Load RSA private key from PEM file
```

#### Mapping to `cryptography` (pyca) equivalents

Every operation has a direct equivalent:

| NPPS4 Usage | PyCryptodome | `cryptography` (pyca) Equivalent |
|---|---|---|
| Load RSA key | `Cryptodome.PublicKey.RSA.import_key()` | `serialization.load_pem_private_key()` |
| RSA sign (SHA1 + PKCS1v1.5) | `pkcs1_15.new(key).sign(sha1_hash)` | `key.sign(data, padding.PKCS1v15(), hashes.SHA1())` |
| RSA decrypt (PKCS1v1.5) | `PKCS1_v1_5.new(key).decrypt(data, None)` | `key.decrypt(data, padding.PKCS1v15())` |
| AES-CBC decrypt | `AES.new(key, MODE_CBC, iv=iv)` | `Cipher(algorithms.AES(key), modes.CBC(iv))` |
| AES-CTR encrypt/decrypt | `AES.new(key, MODE_CTR, nonce=n)` | `Cipher(algorithms.AES(key), modes.CTR(nonce))` |
| SHA1 hash | `Cryptodome.Hash.SHA1.new(data)` | `hashes.Hash(hashes.SHA1())` |
| SHA256 hash | `Cryptodome.Hash.SHA256` | `hashes.SHA256()` (for PBKDF2) |
| PBKDF2 | `Cryptodome.Protocol.KDF.PBKDF2()` | `PBKDF2HMAC(hashes.SHA256(), ...)` |

**Effort to migrate**: ~1-2 days. Only 3 files need changes (`util.py`, `data/schema.py`, `config/config.py`), plus the import in `make_server_key.py` and `util/decrypt_db_row.py` (utility scripts).

**Risk**: Low. The `cryptography` package API is well-documented and the operations are standard. The migration is purely mechanical — same algorithms, different API surface.

### 2. `pydantic-core` → Build from source or downgrade to Pydantic v1

**Status**: [No iOS wheels on PyPI](https://github.com/pydantic/pydantic-core/issues/1170). Issue #1170 remains open. The maintainer's position: "If rust/maturin/pyo3 can build for iOS, we would absolutely support it."

**Since then**: Maturin v1.7.0+ supports iOS (with PEP 730-compliant wheel naming as of v1.10). BeeWare has successfully built other Rust-based iOS wheels (cryptography). The tooling is ready, but nobody has submitted a PR to pydantic-core's CI to add iOS wheel builds. There is [no pure-Python fallback for pydantic-core, and none is planned](https://github.com/pydantic/pydantic/discussions/10859).

#### Option 2a: Cross-compile pydantic-core for iOS (Recommended)

**Approach**:
1. Clone pydantic-core
2. Install maturin ≥1.10 and Rust with iOS targets (`aarch64-apple-ios`, `aarch64-apple-ios-sim`)
3. Set up a cross-compilation venv using BeeWare's Python-Apple-support
4. Set `PYO3_CROSS=1` and `PYO3_CROSS_LIB_DIR` pointing to iOS-compiled libpython ([per PyO3 docs](https://github.com/PyO3/pyo3/discussions/4824))
5. Run `maturin build --target aarch64-apple-ios`
6. The resulting wheel should use PEP 730 tags: `ios_X_Y_arm64_iphoneos`
7. Use the resulting wheel in the Briefcase project

**Effort**: 2-3 weeks (mostly fighting build system edge cases). BeeWare's success with `cryptography` proves the maturin→iOS pipeline works. The pydantic-core build is more complex (larger codebase, more Rust dependencies) but uses the same toolchain.

**Risk**: Medium. Nobody has publicly reported a successful pydantic-core iOS cross-compilation. Build failures are likely and may require upstream patches to maturin or PyO3. However, BeeWare's team (notably @freakboy3742) is actively contributing iOS fixes to maturin and responsive to issues.

#### Option 2b: Downgrade to Pydantic v1 (pure Python)

**Approach**: Pin `pydantic<2.0` and adapt NPPS4 code to Pydantic v1 API.

**Effort**: 2-4 weeks. NPPS4 uses Pydantic v2 features extensively (50+ files import pydantic, uses `model_validate`, `RootModel`, `model_computed_fields`, `TypeAdapter`, `pydantic-settings` v2 API). The migration would be significant and would sacrifice validation performance (5-50x slower per Pydantic benchmarks).

**Risk**: High. Pydantic v1 is in maintenance-only mode (1.10.x-fixes branch). This creates ongoing maintenance burden and prevents using any Pydantic v2+ features.

**Verdict**: Option 2a is strongly preferred. Option 2b is a last resort fallback.

#### Option 2c: Build a minimal pydantic-core stub

**Approach**: Create a pure-Python shim that implements just the pydantic-core validators NPPS4 actually uses.

**Effort**: 3-6 weeks (reverse-engineering which pydantic-core validators are used).

**Risk**: Very high. pydantic-core's API is internal and undocumented. Pydantic updates would break the shim.

**Verdict**: Not recommended.

#### Note on Pydantic v1 Python version support

Pydantic v1 (1.10.x) will not support Python 3.14+, which is NPPS4's target runtime per the README badge. This further argues against the Pydantic v1 downgrade path.

---

## How the iOS Client Patcher Works

### The Two-Part Client Modification

To connect to a private server, the SIF game client needs two modifications:

1. **Server URL replacement** (in `server_info.json`)
2. **RSA public key replacement** (in the game binary)

These are independent operations serving different purposes.

### Part 1: Server URL — `server_info.json`

The game client ships with an encrypted `server_info.json` at `Payload/LoveLive.app/ProjectResources/config/server_info.json`. This file contains:

```json
{
  "name": "server_information",
  "domain": "https://prod-jp.lovelive.ge.klabgames.net",
  "end_point": "/main.php",
  "consumer_key": "lovelive_test",
  "application_key": "b6e6c940a93af2357ea3e0ace0b98afc",
  "api_uri": { ... }
}
```

The [sif-patcher web tool](https://github.com/ethanaobrien/sif-patcher) works by:
1. Loading the IPA (ZIP archive)
2. Decrypting `server_info.json` using **libhonoka** (compiled to WebAssembly)
3. String-replacing the official domain with the user's private server URL
4. Re-encrypting the file with libhonoka
5. Writing the modified file back into the IPA

For localhost use (self-contained iOS), the domain would be `http://127.0.0.1:51376`.

**NPPS4's server-side auto-fix**: When the `download.send_patched_server_info` config is enabled (default: `true`), the server dynamically generates a correct `server_info.json` during the download/update flow (`npps4/svinfo.py`). It uses `honkypy` (Python equivalent of libhonoka) to encrypt a `server_info.json` with all URLs pointing to the actual server address. This is delivered as a game update package, overriding whatever was baked into the IPA. **This means the initial `server_info.json` in the IPA just needs to point to the server once** — after the first download/update, the server replaces it with a correctly-configured version.

### Part 2: RSA Public Key — Binary Patch

Server responses include an `X-Message-Sign` header containing an RSA PKCS#1 v1.5 signature (1024-bit RSA, SHA-1). The client verifies this signature using a public key embedded in the native binary (`LoveLive` Mach-O executable on iOS).

The [community-standard RSA key](https://github.com/DarkEnergyProcessor/NPPS4#using-provided-private-key) (used by NPPS4 by default, LLSIF@Home, and community-patched clients) has this public key:
```
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDE0RNd6047aeBirzVb61DolatY
YWpaEUIPugOIkobHDc9qVR5iliMLyC0ErXO1siLBwN+U3zaDVOa5uhXbiS7uYq5c
cpxComxTnZtcn/b+mKDpYWLaC0Gv7UoiT8rpNqN3Vko645usz9OFc4VciijsHGRP
XmmmoP6qykfI/vba8wIDAQAB
```

The sif-patcher **does not** modify the RSA key — it only changes the domain. The RSA key replacement is a separate binary-level modification to the `LoveLive` Mach-O executable. In practice, the community distributes **pre-patched client builds** (e.g., via Internet Archive) that already have the community-standard RSA key baked in. The sif-patcher web tool expects these pre-patched builds as input — it then only needs to swap the domain. So for end users, the workflow is: get the community-patched IPA → run it through sif-patcher with `http://127.0.0.1:51376` → sideload via AltStore.

### Why Not Two Separate IPAs?

The obvious approach — a separate server IPA and client IPA communicating over localhost — **fails on iOS** due to background execution limits. iOS suspends background apps after ~30 seconds. When the user switches from the server app to the game client, the server gets suspended and the game can't reach it. Split View on iPad is a workaround but not viable on iPhone and is a poor UX.

### Solution: Merged Single-IPA Architecture

**Merge the NPPS4 server directly into the patched game client IPA.** The server runs in-process alongside the game, solving the background execution problem entirely — when the game is in the foreground, so is the server.

#### SIF Game Engine: Playground OSS

SIF uses [**Playground OSS**](https://github.com/nickyma/playground-win), KLab's custom open-source C/C++ game engine. This is relevant because:
- It's **not Unity** — no IL2CPP/Mono complications when injecting native code
- The engine is native C/C++ — a dylib injection via `LC_LOAD_DYLIB` is straightforward
- The [SIF Win32 port](https://github.com/stlcours/SIF_Win32) confirms this engine structure

#### How Dylib Injection Works

The technique injects a dynamic library into the game's Mach-O binary so it loads **before the game's `main()` runs**:

1. **Build a bootstrap dylib** containing:
   - `Python.xcframework` initialization (`Py_Initialize()`)
   - NPPS4 server startup code (equivalent to `android_main.py`)
   - A C function with `__attribute__((constructor))` — this runs automatically when the dylib is loaded into memory, before the app's `main()` is called

2. **Inject the dylib** into the SIF binary using [**optool**](https://github.com/alexzielenski/optool):
   ```bash
   optool install -c load \
     -p "@executable_path/Frameworks/NPPSBootstrap.framework/NPPSBootstrap" \
     -t "Payload/LoveLive.app/LoveLive"
   ```
   This adds an `LC_LOAD_DYLIB` load command to the Mach-O header, telling iOS to load our framework when the app launches.

3. **Bundle everything** into the IPA's `Frameworks/` directory:
   - `NPPSBootstrap.framework` — the bootstrap dylib
   - `Python.framework` — CPython runtime (from BeeWare's Python-Apple-support)
   - All Python dependency frameworks (cryptography, pydantic-core, etc.)
   - NPPS4 source code and data files (in a resource bundle)

4. **Re-sign** the entire IPA (all frameworks must be individually signed)

#### Bootstrap Sequence

```c
// NPPSBootstrap.m
#import <Python/Python.h>

__attribute__((constructor))
static void npps4_bootstrap(void) {
    // 1. Set up Python home to point to bundled stdlib
    NSBundle *bundle = [NSBundle mainBundle];
    NSString *pythonHome = [bundle.resourcePath stringByAppendingPathComponent:@"python"];
    setenv("PYTHONHOME", pythonHome.UTF8String, 1);

    // 2. Initialize Python interpreter
    Py_Initialize();

    // 3. Start NPPS4 server on background thread
    //    (must not block — game's main() needs to run next)
    dispatch_async(dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_DEFAULT, 0), ^{
        PyGILState_STATE gstate = PyGILState_Ensure();
        PyRun_SimpleString(
            "import ios_main\n"
            "ios_main.setup_server()\n"
            "ios_main.start_server('127.0.0.1', 51376)\n"
        );
        PyGILState_Release(gstate);
    });

    // 4. Return — game's main() runs, game initializes and connects to 127.0.0.1:51376
}
```

Key details:
- `__attribute__((constructor))` fires before `main()`, giving the server time to bind its port
- Server startup is dispatched to a background thread so it doesn't block the game's initialization
- The game's network stack takes a moment to initialize, giving the server enough time to be ready
- If a race condition occurs, the game retries connections (standard behavior for network errors)

#### Extended Patcher Workflow

The sif-patcher tool would be extended to perform these additional steps:

```
Input: Community-patched SIF IPA (RSA key already replaced)
       + Python.framework (pre-built from BeeWare)
       + NPPS4 source bundle
       + Pre-compiled iOS wheels (pydantic-core, cryptography, etc.)

Steps:
1. Unzip IPA
2. Replace server_info.json domain → http://127.0.0.1:51376 (existing)
3. Copy Python.framework → Payload/LoveLive.app/Frameworks/
4. Copy NPPSBootstrap.framework → Payload/LoveLive.app/Frameworks/
5. Copy dependency .frameworks → Payload/LoveLive.app/Frameworks/
6. Copy NPPS4 source + data → Payload/LoveLive.app/npps4/
7. Inject LC_LOAD_DYLIB via optool → LoveLive binary
8. Re-sign all frameworks and the main binary
9. Re-zip as IPA

Output: Single IPA with game client + embedded NPPS4 server
```

This could be a **command-line tool** (macOS/Linux, since code signing requires `codesign` or `ldid`) or an extension to the existing web-based sif-patcher (though binary manipulation in WASM is more complex).

#### Advantages Over Two-IPA Approach

| | Two IPAs | Merged Single IPA |
|---|---|---|
| Background execution | Server suspended after ~30s | Server lives as long as game does |
| User workflow | Start server → switch to game | Just launch the game |
| AltStore app slots | Uses 2 of 3 free slots | Uses 1 slot |
| Localhost networking | Works but fragile | In-process, guaranteed |
| App size | ~100MB server + ~200MB game | ~300MB single app |
| Complexity | Simpler build, harder UX | Harder build, seamless UX |

---

## Implementation Plan for Merged Single-IPA Route

### Phase 1: Dependency Resolution (2-4 weeks)

1. **Replace pycryptodomex with cryptography** (~2 days)
   - Migrate `npps4/util.py`: RSA sign, RSA decrypt, AES-CBC decrypt
   - Migrate `npps4/data/schema.py`: PBKDF2, AES-CTR
   - Migrate `npps4/config/config.py`: RSA key loading
   - Update `requirements.txt`: replace `pycryptodomex` with `cryptography`
   - Run existing tests to verify

2. **Cross-compile pydantic-core for iOS** (~2-3 weeks)
   - Set up macOS build environment with Xcode, Rust toolchain, iOS SDK targets
   - Install maturin ≥1.10
   - Create BeeWare Python-Apple-support cross-compilation venv
   - Build pydantic-core wheel targeting `aarch64-apple-ios`
   - Set `PYO3_CROSS=1` and `PYO3_CROSS_LIB_DIR` pointing to iOS-compiled libpython
   - Convert resulting `.so` to signed `.framework` bundle
   - Test the wheel in a minimal test harness on-device

### Phase 2: Bootstrap Dylib & Server Integration (3-4 weeks)

3. **Create `ios_main.py`** (modeled on `android_main.py`) (~3 days)
   - `setup_server()`, `start_server(host, port)`, `stop_server()`
   - Add `sys.platform == "ios"` handling in config.py, requirements
   - **Critical**: iOS forbids `fork()`/`spawn()` — the `android_main.py` pattern (in-process `uvicorn.Server.run()`) must be used
   - Database path must point to the app's `Documents/` directory (writable on iOS)
   - `evloop.py` already handles missing uvloop gracefully — no changes needed

4. **Build NPPSBootstrap.framework** (~2 weeks)
   - Create Xcode framework project targeting iOS (arm64)
   - Link against `Python.xcframework` from BeeWare's Python-Apple-support
   - Implement `__attribute__((constructor))` bootstrap (see Bootstrap Sequence above)
   - Handle Python GIL correctly — server runs on a background thread via `dispatch_async`
   - Set up `PYTHONHOME` and `PYTHONPATH` to find bundled stdlib and NPPS4 source
   - Handle edge cases: What if Python init fails? What if port is already in use?
   - Test on real device (simulator won't have the SIF client)

5. **Convert Python dependencies to iOS frameworks** (~1 week)
   - Each `.so` binary module must become a signed `.framework` bundle
   - BeeWare's Briefcase has tooling for this conversion — extract and adapt it
   - Required frameworks: `_cffi_backend`, `_rust` (cryptography internals), `_pydantic_core`
   - Pure-Python packages (FastAPI, uvicorn, starlette, etc.) go in a resource bundle as-is

### Phase 3: Patcher Extension & Distribution (2-3 weeks)

6. **Extend sif-patcher or build new CLI patcher** (~2 weeks)
   - Implement the Extended Patcher Workflow (see above)
   - Input: community-patched SIF IPA + pre-built server components
   - Operations: inject `LC_LOAD_DYLIB`, copy frameworks, copy Python source/data
   - Use optool (or reimplement LC_LOAD_DYLIB injection — it's just Mach-O header editing)
   - Re-sign with `ldid` (for TrollStore) or `codesign` (for AltStore with Apple ID)
   - Output: single merged IPA
   - Could be a Python CLI tool (ironic but practical) or integrated into the web patcher

7. **AltStore/TrollStore packaging & testing** (~1 week)
   - Create AltStore source JSON for distribution
   - Test installation via AltStore Classic, AltStore PAL (EU), and TrollStore
   - Test on multiple iOS versions (15+)
   - Test memory pressure handling (game + server sharing ~300-500MB budget)
   - Test database integrity under app termination
   - Verify end-to-end gameplay: launch game → server auto-starts → play normally

---

## iOS-Specific Code Changes in NPPS4

### Required Changes

1. **Platform detection** — `sys.platform` returns `"ios"` on CPython 3.13+ per [PEP 730](https://peps.python.org/pep-0730/)
   - `config.py:106`: Add iOS to the `sys.platform == "android"` branch
   - `requirements.txt`: Add iOS platform markers (same as Android minus uvloop)
   - `evloop.py`: Already handles missing uvloop gracefully

2. **Crypto library swap** (see Phase 1 above)

3. **`ios_main.py`** — New file, modeled on `android_main.py`:
   ```python
   # Same API surface as android_main.py:
   # setup_server(), start_server(), stop_server()
   # import_database(), export_database(), nuke_database()
   ```
   Key differences from `android_main.py`:
   - Database path: Use iOS `Documents/` directory (writable, persists across updates)
   - No UI integration needed — server starts automatically via constructor bootstrap
   - `start_server()` called from background thread (GIL-safe via `PyGILState_Ensure`)
   - Server lifecycle tied to the game's process lifecycle (no separate stop needed)

4. **Background/foreground handling** — In the merged architecture, the server's lifecycle matches the game's:
   - When the game is foregrounded, the server runs
   - When the game is backgrounded, both the game and server are suspended together (~30s)
   - When the game is terminated, the server process dies with it
   - SQLite WAL checkpoint on `applicationWillResignActive` (handled via ObjC notification observer in the bootstrap dylib)
   - On next launch, the constructor fires again, reinitializing Python and the server

### Nice-to-Have Changes

5. **Reduced import time** — Python initialization happens in the constructor before `main()`. Lazy imports help reduce the delay before the game starts.
6. **Memory budget** — iOS gives ~300-500MB to foreground apps on modern devices. SIF uses ~100-150MB, NPPS4 uses ~50-100MB. Combined ~200-250MB with comfortable headroom.
7. **Startup race condition mitigation** — Add a small `usleep()` after dispatching the server thread, or have the bootstrap set an environment variable/file that the patched `server_info.json` domain check could wait on. In practice, the game's own initialization (loading assets, showing splash screen) takes several seconds, giving the server plenty of time to bind.

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| pydantic-core fails to cross-compile for iOS | Medium | **Blocks project** | Fall back to Pydantic v1 (Option 2b), or contribute the fix upstream to maturin/PyO3 |
| Python initialization too slow (delays game start) | Medium | Poor UX | Lazy imports, pre-compiled `.pyc` files, move init to background thread |
| Bootstrap race condition (game connects before server ready) | Low-Medium | Game shows network error | Game retries on network error; add `usleep()` delay; game splash screen provides natural buffer |
| Memory pressure (game + Python runtime) | Low | Crashes | NPPS4 is lightweight (~50-100MB); combined with SIF (~100-150MB) stays within iOS budget |
| `optool` injection breaks code signing | Low | Build fails | Well-tested technique in iOS tweak community; `ldid`/`codesign` re-sign handles this |
| AltStore 7-day re-signing annoys users | Medium | Poor UX | Recommend TrollStore where available; AltStore PAL in EU |
| Apple restricts sideloaded apps with interpreters | Very Low | **Blocks project** | Not subject to App Store review; Apple doesn't police sideloaded app internals |
| SIF game binary updates break injection | Very Low | Build fails | SIF is discontinued (shut down March 2023); binary is fixed and archived |

---

## Architecture Diagram

```
┌──────────────────────────────────────────────────────┐
│                    iOS Device                         │
│                                                      │
│  ┌────────────────────────────────────────────────┐  │
│  │     Merged SIF + NPPS4 IPA (via AltStore)      │  │
│  │                                                │  │
│  │  ┌────────────────────────────────────┐        │  │
│  │  │ LoveLive (Mach-O binary)           │        │  │
│  │  │ + LC_LOAD_DYLIB: NPPSBootstrap     │        │  │
│  │  └──────────┬─────────────────────────┘        │  │
│  │             │ loads before main()               │  │
│  │  ┌──────────▼─────────────────────────┐        │  │
│  │  │ NPPSBootstrap.framework            │        │  │
│  │  │  __attribute__((constructor))       │        │  │
│  │  │  → Py_Initialize()                 │        │  │
│  │  │  → dispatch_async: start_server()  │        │  │
│  │  └──────────┬─────────────────────────┘        │  │
│  │             │                                  │  │
│  │  ┌──────────▼──────────┐  ┌─────────────────┐ │  │
│  │  │ Python.framework    │  │ SIF Game Engine  │ │  │
│  │  │ (BeeWare CPython)   │  │ (Playground OSS) │ │  │
│  │  │                     │  │                  │ │  │
│  │  │ FastAPI + uvicorn   │  │ Connects to:     │ │  │
│  │  │ NPPS4 server code   │  │ 127.0.0.1:51376  │ │  │
│  │  │ SQLite database     │◄─│                  │ │  │
│  │  │ 127.0.0.1:51376     │  │ (via patched     │ │  │
│  │  │ (background thread) │  │  server_info)    │ │  │
│  │  └─────────────────────┘  └─────────────────┘ │  │
│  │                                                │  │
│  │  Frameworks/                                   │  │
│  │  ├── NPPSBootstrap.framework                   │  │
│  │  ├── Python.framework                          │  │
│  │  ├── _cffi_backend.framework                   │  │
│  │  ├── _pydantic_core.framework                  │  │
│  │  └── ... (other binary modules)                │  │
│  └────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────┘
```

---

## Recommendation

**The merged single-IPA approach — injecting the NPPS4 Python server into the patched SIF game client — is the recommended architecture for iOS.**

It solves the fatal flaw of the two-IPA approach (iOS background execution limits) and provides a seamless user experience: launch the game, play. No separate server app, no app switching, no split-screen workarounds.

The critical path is:
1. Replace `pycryptodomex` → `cryptography` (pyca) — **low risk, 2 days**
2. Cross-compile `pydantic-core` for iOS via maturin — **medium risk, 2-3 weeks**
3. Build NPPSBootstrap.framework + `ios_main.py` — **medium risk, 2 weeks**
4. Build/extend patcher tool for IPA injection — **medium risk, 2 weeks**
5. Testing & distribution — **low risk, 1 week**

**Total: 2-3 months.** The approach builds on well-established iOS tweak injection techniques and BeeWare's proven iOS Python toolchain. The pydantic-core cross-compilation remains the single biggest risk, with the bootstrap dylib development being the main new work compared to the (abandoned) two-IPA approach.

### User Workflow (End Result)

1. Download pre-built merged IPA (or run the patcher tool themselves)
2. Install via AltStore / TrollStore
3. Launch the game
4. Play — server is already running in-process

---

## References

### Python on iOS
- [BeeWare Python-Apple-support](https://github.com/beeware/Python-Apple-support)
- [BeeWare Briefcase iOS docs](https://briefcase.beeware.org/en/v0.3.16/reference/platforms/iOS.html)
- [BeeWare mobile wheels leaderboard](https://beeware.org/mobile-wheels/)
- [BeeWare November 2025 update (cryptography iOS wheels)](https://beeware.org/news/buzz/november-2025-status-update/)
- [PEP 730 — iOS platform tags](https://peps.python.org/pep-0730/)
- [CPython iOS usage docs](https://docs.python.org/3/using/ios.html)
- [Python-Apple-support USAGE.md](https://github.com/beeware/Python-Apple-support/blob/main/USAGE.md)
- [Python-Apple-support static linking requirement #56](https://github.com/beeware/Python-Apple-support/issues/56)
- [Pyto — Python IDE on App Store (proof of concept)](https://github.com/ColdGrub1384/Pyto)

### Rust/PyO3 iOS Cross-Compilation
- [Maturin iOS support (v1.7.0)](https://github.com/PyO3/maturin/releases/tag/v1.7.0)
- [Maturin iOS issue #1742](https://github.com/PyO3/maturin/issues/1742)
- [PyO3 iOS/Android cross-compilation discussion #4824](https://github.com/PyO3/pyo3/discussions/4824)
- [pydantic-core iOS support issue #1170](https://github.com/pydantic/pydantic-core/issues/1170)
- [Pydantic pure-Python fallback discussion #10859](https://github.com/pydantic/pydantic/discussions/10859)

### Crypto Library Migration
- [pyca/cryptography RSA docs](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/rsa/)
- [kivy-ios pycryptodome issue #701](https://github.com/kivy/kivy-ios/issues/701)
- [kivy-ios pycryptodome issue #755](https://github.com/kivy/kivy-ios/issues/755)

### iOS Dylib Injection
- [optool — Mach-O binary manipulation](https://github.com/alexzielenski/optool)
- [iOS Dylib Injection Demo (with patchapp.sh)](https://github.com/depoon/iOSDylibInjectionDemo)
- [How to perform iOS Code Injection on .ipa files](https://medium.com/@kennethpoon/how-to-perform-ios-code-injection-on-ipa-files-1ba91d9438db)
- [ios-dylib-inject — Script for dylib injection + re-signing](https://github.com/gnithin/ios-dylib-inject)
- [iPA-Edit — Cross-platform IPA modification tool](https://github.com/SHAJON-404/iPA-Edit)

### SIF Game Engine
- [SIF Win32 port (confirms Playground OSS engine)](https://github.com/stlcours/SIF_Win32)
- [Playground OSS — KLab's open-source game engine](https://github.com/nickyma/playground-win)

### Distribution
- [AltStore source format docs](https://faq.altstore.io/developers/make-a-source)
- [PythonKit — Swift-Python bridge](https://github.com/pvieito/PythonKit)
