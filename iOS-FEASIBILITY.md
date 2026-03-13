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

SIF uses [**PlaygroundOSS**](https://github.com/KLab/PlaygroundOSS), KLab's own game engine (open-sourced under Apache License v2.0). This is relevant because:
- It's **not Unity** — no IL2CPP/Mono complications when injecting native code. (Note: SIFAS/SIF2 used Unity, but the original SIF1 uses Playground)
- The engine is native **C (67%) / C++ (27%)** with Objective-C for iOS — a dylib injection via `LC_LOAD_DYLIB` is straightforward
- Uses a **standard `UIApplicationDelegate`** pattern (`Engine/porting/iOS/AppDelegate.mm`), meaning `__attribute__((constructor))` in an injected dylib fires cleanly before the engine's `application:didFinishLaunchingWithOptions:` runs
- The engine uses **Lua** for game scripting and **OpenGL ES 2** for rendering
- SIF has a significant startup sequence (launch splash → title screen → data download check) that provides **natural buffer time** for the Python server to initialize before the game makes its first network request
- The [SIF Win32 port](https://github.com/stlcours/SIF_Win32) and [Playground-SIF fork](https://github.com/kotori2/Playground-SIF) confirm this engine structure

#### How Dylib Injection Works

The technique injects a dynamic library into the game's Mach-O binary so it loads **before the game's `main()` runs**:

1. **Build a bootstrap dylib** as an iOS framework (`.framework` bundle — standalone `.dylib` files are [rejected on iOS](https://developer.apple.com/library/archive/technotes/tn2435/_index.html)):
   - `Python.xcframework` initialization via the `PyConfig` API ([PEP 587](https://peps.python.org/pep-0587/))
   - NPPS4 server startup code (equivalent to `android_main.py`)
   - A C function with `__attribute__((constructor))` — this runs automatically when the framework is loaded, before the app's `main()` is called

2. **Inject the framework** into the SIF binary using [**optool**](https://github.com/alexzielenski/optool):
   ```bash
   optool install -c load \
     -p "@executable_path/Frameworks/NPPSBootstrap.framework/NPPSBootstrap" \
     -t "Payload/LoveLive.app/LoveLive"
   ```
   This adds an `LC_LOAD_DYLIB` load command to the Mach-O header, telling iOS to load our framework when the app launches. The `@executable_path/Frameworks/` path works because the SIF binary already has an `LC_RPATH` pointing there (standard for iOS apps). Verify with `otool -l LoveLive | grep -A2 LC_RPATH`.

3. **Bundle everything** into the IPA's `Frameworks/` directory:
   - `NPPSBootstrap.framework` — the bootstrap dylib
   - `Python.framework` — CPython runtime (from BeeWare's Python-Apple-support)
   - All Python dependency frameworks (cryptography, pydantic-core, etc. — each `.so` must be converted to a signed `.framework`, see below)
   - NPPS4 source code and data files (in a resource bundle)

4. **Re-sign** the entire IPA — every `.framework` must be individually signed

#### Constructor Load Order

When the app launches, dyld processes load commands in order ([Apple Dynamic Library Design Guidelines](https://developer.apple.com/library/archive/documentation/DeveloperTools/Conceptual/DynamicLibraries/100-Articles/DynamicLibraryDesignGuidelines.html)):

```
Game's original dependencies (UIKit, OpenGLES, etc.)
→ Game's own static constructors (C++ globals, ObjC +load methods)
→ Python.framework constructors (NPPSBootstrap depends on it)
→ NPPSBootstrap's __attribute__((constructor))
→ main()
→ application:didFinishLaunchingWithOptions:  ← game's first network I/O is much later
```

Since `optool` appends our `LC_LOAD_DYLIB`, NPPSBootstrap loads after all original game dependencies. Our constructor runs after the game's own constructors but before `main()`. The game doesn't make network requests until well after `main()`, during `application:didFinishLaunchingWithOptions:` and the subsequent splash/title/download screens — giving the server seconds to initialize.

#### Bootstrap Sequence (Corrected)

The bootstrap must use the modern `PyConfig` API (not the deprecated `Py_Initialize()` + `setenv`), and must correctly release the GIL before dispatching work to a background thread:

```objc
// NPPSBootstrap.m
#import <Python/Python.h>
#import <dispatch/dispatch.h>

// Saved thread state for potential future main-thread Python calls
static PyThreadState *g_mainThreadState = NULL;

__attribute__((constructor))
static void npps4_bootstrap(void) {
    NSBundle *bundle = [NSBundle mainBundle];
    NSString *resourcePath = bundle.resourcePath;

    // ── Step 1: Pre-initialize (UTF-8 mode, required on iOS) ──
    PyPreConfig preconfig;
    PyPreConfig_InitIsolatedConfig(&preconfig);
    preconfig.utf8_mode = 1;

    PyStatus status = Py_PreInitialize(&preconfig);
    if (PyStatus_Exception(status)) {
        NSLog(@"NPPS4: Python pre-init failed: %s", status.err_msg);
        return;  // Don't crash the game — just skip server startup
    }

    // ── Step 2: Configure Python for iOS embedded mode ──
    PyConfig config;
    PyConfig_InitIsolatedConfig(&config);

    // iOS-mandatory settings (per CPython iOS docs):
    config.buffered_stdio = 0;      // iOS has no terminal stdio
    config.write_bytecode = 0;      // Bundle is read-only
    config.install_signal_handlers = 1;
#if PY_VERSION_HEX >= 0x030D0000  // Python 3.13+
    config.use_system_logger = 1;   // Route prints to os_log
#endif

    // Set Python home → bundled stdlib
    NSString *pythonHome = [resourcePath stringByAppendingPathComponent:@"python"];
    status = PyConfig_SetBytesString(&config, &config.home,
                                     pythonHome.UTF8String);
    if (PyStatus_Exception(status)) goto fail;

    // Set module search paths explicitly
    config.module_search_paths_set = 1;

    NSString *paths[] = {
        [NSString stringWithFormat:@"%@/python/lib/python3.14", resourcePath],
        [NSString stringWithFormat:@"%@/python/lib/python3.14/lib-dynload", resourcePath],
        [NSString stringWithFormat:@"%@/app", resourcePath],  // NPPS4 source
        [NSString stringWithFormat:@"%@/app_packages", resourcePath],  // pip dependencies
    };
    for (int i = 0; i < sizeof(paths)/sizeof(paths[0]); i++) {
        wchar_t *wpath = Py_DecodeLocale(paths[i].UTF8String, NULL);
        PyWideStringList_Append(&config.module_search_paths, wpath);
        PyMem_RawFree(wpath);
    }

    // ── Step 3: Initialize Python ──
    status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);

    if (PyStatus_Exception(status)) {
        NSLog(@"NPPS4: Python init failed: %s", status.err_msg);
        return;
    }

    // ── Step 4: Release the GIL ──
    // CRITICAL: After Py_Initialize, the calling thread holds the GIL.
    // We MUST release it before dispatch_async's thread can acquire it.
    // Without this, PyGILState_Ensure() in the block below DEADLOCKS.
    g_mainThreadState = PyEval_SaveThread();

    // ── Step 5: Start NPPS4 server on a background thread ──
    // dispatch_async returns immediately — game's main() runs next.
    NSString *documentsDir = NSSearchPathForDirectoriesInDomains(
        NSDocumentDirectory, NSUserDomainMask, YES).firstObject;

    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        PyGILState_STATE gstate = PyGILState_Ensure();

        // Set NPPS4 data directory to iOS Documents/ (writable, persists across updates)
        PyObject *code = PyUnicode_FromFormat(
            "import os\n"
            "os.environ['NPPS4_DATA_DIR'] = '%s'\n"
            "import ios_main\n"
            "ios_main.setup_server()\n"
            "ios_main.start_server('127.0.0.1', 51376)\n",
            documentsDir.UTF8String
        );
        PyObject *mainmod = PyImport_AddModule("__main__");
        PyObject *globals = PyModule_GetDict(mainmod);
        PyObject *result = PyRun_String(
            PyUnicode_AsUTF8(code), Py_file_input, globals, globals);

        if (result == NULL) {
            PyErr_Print();  // Log error but don't crash
        }
        Py_XDECREF(result);
        Py_DECREF(code);

        PyGILState_Release(gstate);
    });

    // ── Step 6: Return — game's main() runs ──
    return;

fail:
    PyConfig_Clear(&config);
    NSLog(@"NPPS4: Python config failed: %s", status.err_msg);
}
```

**Key correctness details:**

| Detail | Why it matters |
|---|---|
| `PyPreConfig.utf8_mode = 1` | iOS has no locale; UTF-8 mode avoids encoding errors |
| `PyConfig.buffered_stdio = 0` | No terminal on iOS; buffered stdio causes hangs |
| `PyConfig.write_bytecode = 0` | App bundle is read-only; `.pyc` writes would fail |
| `config.module_search_paths_set = 1` | Tells Python we provide paths explicitly (don't auto-discover) |
| `PyEval_SaveThread()` before `dispatch_async` | **Without this, the background thread deadlocks** — it calls `PyGILState_Ensure()` which waits for the GIL that the main thread never released |
| `QOS_CLASS_USER_INITIATED` | Higher priority than `DEFAULT`; server initialization is time-sensitive |
| Error handling with `return` (not `exit()`) | If Python fails, the game still launches — just without the server |
| Documents directory for data | Only writable persistent location on iOS; survives app updates |

#### Building NPPSBootstrap.framework

**Xcode project setup** — Create an iOS Framework target:

| Build Setting | Value | Why |
|---|---|---|
| `ARCHS` | `arm64` | Device only (SIF is arm64) |
| `IPHONEOS_DEPLOYMENT_TARGET` | `14.0` | Floor for TrollStore 14.0+, AltStore, BeeWare 13.0+ |
| `DYLIB_INSTALL_NAME_BASE` | `@rpath` | Default; install name becomes `@rpath/NPPSBootstrap.framework/NPPSBootstrap` |
| `LD_RUNPATH_SEARCH_PATHS` | `@executable_path/Frameworks @loader_path/Frameworks` | Finds Python.framework at runtime in the same Frameworks/ dir |
| `MACH_O_TYPE` | `mh_dylib` | Default for framework targets |

**Link against Python.xcframework**: Add to "Link Binary With Libraries" in Build Phases, but do **not** embed it (it goes into the IPA separately). NPPSBootstrap records a dependency on `@rpath/Python.framework/Python`, which dyld resolves via `@executable_path/Frameworks/Python.framework/Python` at runtime.

**Verify the built framework:**
```bash
# Check install name
otool -D NPPSBootstrap.framework/NPPSBootstrap
# → @rpath/NPPSBootstrap.framework/NPPSBootstrap

# Check it links against Python
otool -L NPPSBootstrap.framework/NPPSBootstrap
# → @rpath/Python.framework/Python

# Check rpaths
otool -l NPPSBootstrap.framework/NPPSBootstrap | grep -A2 LC_RPATH
# → @executable_path/Frameworks, @loader_path/Frameworks
```

#### Binary Module Conversion (`.so` → `.framework`)

iOS does not allow standalone `.so` or `.dylib` files in the app bundle ([TN2435](https://developer.apple.com/library/archive/technotes/tn2435/_index.html)). Every Python C extension must be converted to a signed `.framework` bundle. CPython 3.13+ on iOS includes `AppleFrameworkLoader` which reads `.fwork` marker files to redirect imports.

BeeWare's `build_utils.sh` (bundled inside `Python.xcframework`) automates this via the `install_python` function. To use it in the Xcode build phase:

```bash
set -e
source $PROJECT_DIR/Python.xcframework/build/build_utils.sh
install_python Python.xcframework app app_packages
```

**The conversion for each module** (e.g., `_pydantic_core.cpython-314-darwin.so`):

```
1. Create:  Frameworks/_pydantic_core.framework/
2. Move:    .so binary → Frameworks/_pydantic_core.framework/_pydantic_core
3. Create:  Frameworks/_pydantic_core.framework/Info.plist
4. Marker:  lib/python3.14/lib-dynload/_pydantic_core.cpython-314-darwin.fwork
            Contents: "Frameworks/_pydantic_core/_pydantic_core"
5. Origin:  Frameworks/_pydantic_core.framework/_pydantic_core.origin
            Contents: path back to .fwork file
6. Sign:    codesign --force --sign <identity> Frameworks/_pydantic_core.framework
```

For nested modules (e.g., `cryptography.hazmat.bindings._rust`), the framework name uses dots to flatten the path: `cryptography.hazmat.bindings._rust.framework`.

For the **merged-IPA patcher workflow** (building outside Xcode), this conversion logic must be replicated in the patcher tool. It's ~50 lines of shell/Python.

#### Code Signing

Every binary in the IPA must be signed with the same identity:

| Distribution method | Signing tool | Notes |
|---|---|---|
| **TrollStore** | `ldid -S` | Ad-hoc signing; TrollStore re-signs on install via CoreTrust bypass |
| **AltStore** | Automatic | AltStore re-signs everything with the user's Apple ID |
| **Sideloadly** | Automatic | Similar to AltStore |
| **macOS build** | `codesign -fs "identity"` | For development/testing with an Apple developer certificate |

```bash
# Practical signing for TrollStore distribution:
find Payload/LoveLive.app/Frameworks -name "*.framework" -exec \
  sh -c 'ldid -S "$1/$(basename "$1" .framework)"' _ {} \;
ldid -S Payload/LoveLive.app/LoveLive
```

#### Extended Patcher Workflow

The sif-patcher tool would be extended to perform these additional steps:

```
Input: Community-patched SIF IPA (RSA key already replaced)
       + Python.xcframework (pre-built from BeeWare)
       + NPPSBootstrap.framework (pre-built from Xcode)
       + NPPS4 source bundle (pre-compiled .pyc)
       + Pre-compiled iOS wheels (pydantic-core, cryptography, etc.)

Steps:
 1. Unzip IPA
 2. Replace server_info.json domain → http://127.0.0.1:51376 (existing patcher)
 3. Copy Python.framework → Payload/LoveLive.app/Frameworks/
 4. Copy NPPSBootstrap.framework → Payload/LoveLive.app/Frameworks/
 5. Run .so → .framework conversion for all binary Python modules
 6. Copy converted dependency .frameworks → Payload/LoveLive.app/Frameworks/
 7. Create .fwork marker files at original module paths
 8. Copy NPPS4 source + data → Payload/LoveLive.app/app/
 9. Copy pip dependencies → Payload/LoveLive.app/app_packages/
10. Copy Python stdlib → Payload/LoveLive.app/python/
11. Inject LC_LOAD_DYLIB via optool → LoveLive binary
12. Re-sign all frameworks and the main binary (ldid or codesign)
13. Re-zip as IPA

Output: Single IPA with game client + embedded NPPS4 server
```

This could be a **command-line Python tool** (using `optool` as a subprocess) or integrated into the existing web-based sif-patcher (optool logic is just Mach-O header editing — a pure-JS/WASM reimplementation is feasible).

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
   - Must call `npps4.config.config._override_script_mode(False)` before other npps4 imports
   - `setup_server()`: Run Alembic migrations + data migrations (same as `android_main.py`)
   - `start_server(host, port)`: Create `uvicorn.Config` with `loop="npps4.evloop:new_event_loop"`, run `uvicorn.Server(cfg).run()` (blocks — called from background thread)
   - `stop_server()`: Set `server_instance.should_exit = True` (cross-thread safe)
   - **Critical**: iOS forbids `fork()`/`spawn()` — the `android_main.py` pattern (in-process `uvicorn.Server.run()`) must be used
   - Database/data path: Use iOS `Documents/` directory via env var set by bootstrap
   - `evloop.py` already handles missing uvloop gracefully — falls back to `asyncio.new_event_loop`

4. **Build NPPSBootstrap.framework** (~2 weeks)
   - Create Xcode framework project: arm64, iOS 14.0+, linked against `Python.xcframework`
   - Implement `__attribute__((constructor))` bootstrap using `PyConfig` API (see Bootstrap Sequence above)
   - **GIL handling**: `Py_InitializeFromConfig()` → `PyEval_SaveThread()` → `dispatch_async` + `PyGILState_Ensure()`. The `SaveThread` call is critical — without it the background thread deadlocks
   - Error handling: Log failures via `NSLog`, return without crashing the game
   - Module search paths: `python/lib/python3.14`, `python/lib/python3.14/lib-dynload`, `app/` (NPPS4), `app_packages/` (pip deps)
   - Verify with `otool -L` / `otool -D` that install name and rpaths are correct
   - Test on real device (simulator won't have the SIF client)

5. **Convert Python dependencies to iOS frameworks** (~1 week)
   - Use BeeWare's `build_utils.sh` / `install_python` for `.so` → `.framework` conversion
   - Each binary module becomes a signed `.framework` with an `.fwork` marker file (CPython's `AppleFrameworkLoader` reads these)
   - Required frameworks: `_cffi_backend`, `cryptography.hazmat.bindings._rust`, `_pydantic_core`
   - Pure-Python packages (FastAPI, uvicorn, starlette, pydantic, etc.) go as-is in `app_packages/`
   - Prune unused stdlib modules (test, tkinter, idlelib, etc.) — saves ~20 MB

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

5. **Reduced import time** — `Py_InitializeFromConfig()` takes ~200-500ms. Module imports (NPPS4 + deps) take ~1-3s but run on the background thread so they don't block the game. Pre-compiling all `.py` to `.pyc` saves ~30% import time. Lazy imports help further.
6. **Memory budget** — Estimated runtime memory:

   | Component | RSS Estimate |
   |---|---|
   | CPython interpreter (initialized) | ~15-25 MB |
   | Stdlib + NPPS4 + deps (FastAPI, uvicorn, pydantic) | ~40-75 MB |
   | SQLite database (in-memory cache) | ~5-20 MB |
   | **Total Python overhead** | **~60-120 MB** |
   | SIF game (existing) | ~100-150 MB |
   | **Combined** | **~160-270 MB** |

   Modern iOS devices give foreground apps 300-500 MB (iPhone 8+) to 1-2 GB (iPhone 12+). Combined footprint stays well within budget.

7. **IPA size impact** — Python.framework adds ~100 MB uncompressed (~30-40 MB in IPA's ZIP). Stdlib can be pruned by ~20 MB (remove test, tkinter, idlelib, etc.). NPPSBootstrap.framework itself is <100 KB. Total IPA size increase: ~50-70 MB compressed.
8. **Startup race condition mitigation** — Server needs ~2-4 seconds from app launch to be ready. SIF's own startup takes 5-10 seconds (splash screen → title screen → data download check). In practice, the game won't make its first network request until well after the server is listening. If needed, add a `usleep()` in the constructor or a retry loop in `ios_main.py`.

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| pydantic-core fails to cross-compile for iOS | Medium | **Blocks project** | Fall back to Pydantic v1 (Option 2b), or contribute the fix upstream to maturin/PyO3 |
| Python initialization too slow (delays game start) | Low-Medium | Poor UX | `Py_InitializeFromConfig` is ~200-500ms (before `main()`); imports run on background thread. Pre-compile `.pyc`, prune stdlib |
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
│  │  │  → Py_InitializeFromConfig()       │        │  │
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

### iOS Dylib Injection & Code Signing
- [optool — Mach-O binary manipulation](https://github.com/alexzielenski/optool)
- [iOS Dylib Injection Demo (with patchapp.sh)](https://github.com/depoon/iOSDylibInjectionDemo)
- [How to perform iOS Code Injection on .ipa files](https://medium.com/@kennethpoon/how-to-perform-ios-code-injection-on-ipa-files-1ba91d9438db)
- [ios-dylib-inject — Script for dylib injection + re-signing](https://github.com/gnithin/ios-dylib-inject)
- [iPA-Edit — Cross-platform IPA modification tool](https://github.com/SHAJON-404/iPA-Edit)
- [Apple TN2435 — Embedding Frameworks In An App](https://developer.apple.com/library/archive/technotes/tn2435/_index.html)
- [Apple Dynamic Library Design Guidelines (constructor load order)](https://developer.apple.com/library/archive/documentation/DeveloperTools/Conceptual/DynamicLibraries/100-Articles/DynamicLibraryDesignGuidelines.html)
- [Understanding @executable_path, @loader_path and @rpath](https://itwenty.me/posts/01-understanding-rpath/)

### Python Embedding
- [PEP 587 — Python Initialization Configuration (PyConfig API)](https://peps.python.org/pep-0587/)
- [CPython Android testbed — mobile embedding reference](https://github.com/python/cpython/tree/main/Android/testbed)

### SIF Game Engine
- [PlaygroundOSS — KLab's open-source game engine (official repo)](https://github.com/KLab/PlaygroundOSS)
- [SIF Win32 port (confirms PlaygroundOSS engine)](https://github.com/stlcours/SIF_Win32)
- [Playground-SIF — All-platform SIF port using PlaygroundOSS](https://github.com/kotori2/Playground-SIF)

### Distribution
- [AltStore source format docs](https://faq.altstore.io/developers/make-a-source)
- [PythonKit — Swift-Python bridge](https://github.com/pvieito/PythonKit)
