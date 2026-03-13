# iOS Self-Contained Experience: Feasibility Analysis (Embedded Python Route)

## Executive Summary

Providing a self-contained NPPS4 experience on iOS via AltStore is **feasible but requires meaningful dependency work**. The recommended path is BeeWare Briefcase with Python-Apple-support. The two binary dependencies (`pycryptodomex` and `pydantic-core`) are the critical blockers, but both have viable solutions:

- **`pycryptodomex`**: Replace with `cryptography` (pyca), which already has [iOS wheels built by BeeWare](https://beeware.org/news/buzz/november-2025-status-update/). All crypto operations used by NPPS4 have direct equivalents.
- **`pydantic-core`**: [Maturin gained iOS support in v1.7.0](https://github.com/PyO3/maturin/releases/tag/v1.7.0), but [pydantic-core has not yet published iOS wheels](https://github.com/pydantic/pydantic-core/issues/1170). The wheel must be built from source using maturin's iOS cross-compilation, which is now technically possible but untested for pydantic-core specifically.

**Revised effort estimate: 2-4 person-months** for the embedded Python approach targeting AltStore distribution.

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

The sif-patcher **does not** modify the RSA key — it only changes the domain. The RSA key must be replaced separately by binary-patching the `LoveLive` Mach-O executable (finding the old public key bytes with `strings` and replacing them). Pre-patched community clients already have this done.

### Can the Patcher Patch a Briefcase-Produced App?

**No, and it doesn't need to.** The patcher modifies the *game client* (SIF), not the server app. The architecture is:

```
┌──────────────────────────┐     ┌──────────────────────────┐
│  NPPS4 Server App (IPA)  │     │  Patched SIF Client (IPA)│
│  Built with Briefcase    │     │  Patched with sif-patcher│
│  Contains: Python server │     │  Contains: Game client   │
│  Listens: 127.0.0.1:51376│◄────│  Connects to: 127.0.0.1 │
└──────────────────────────┘     └──────────────────────────┘
        Server IPA                       Client IPA
   (produced by us)              (produced by sif-patcher)
```

These are **two separate IPAs** installed side-by-side via AltStore:
- **Server IPA**: Built by Briefcase, embeds CPython + NPPS4. Not touched by sif-patcher
- **Client IPA**: The original SIF game, patched by sif-patcher to point to `http://127.0.0.1:51376` and use the community RSA public key

### iOS-Specific Concern: Cross-App Localhost

On iOS, two separate apps **can** communicate over localhost (`127.0.0.1`). iOS does not sandbox loopback networking between apps — any app can connect to any port on `127.0.0.1`. This has been tested and confirmed by various iOS development communities.

The workflow for the user would be:
1. Install **NPPS4 Server** via AltStore
2. Install **patched SIF** via AltStore (using sif-patcher with domain `http://127.0.0.1:51376`)
3. Open NPPS4 Server app, tap "Start Server"
4. Switch to SIF app, play normally
5. Keep NPPS4 Server in the foreground (or use Split View on iPad) to prevent iOS from suspending it

---

## Implementation Plan for Embedded Python Route

### Phase 1: Dependency Resolution (2-4 weeks)

1. **Replace pycryptodomex with cryptography** (~2 days)
   - Migrate `npps4/util.py`: RSA sign, RSA decrypt, AES-CBC decrypt
   - Migrate `npps4/data/schema.py`: PBKDF2, AES-CTR
   - Migrate `npps4/config/config.py`: RSA key loading
   - Update `requirements.txt`: replace `pycryptodomex` with `cryptography`
   - Run existing tests to verify

2. **Cross-compile pydantic-core for iOS** (~2-3 weeks)
   - Set up macOS build environment with Xcode, Rust toolchain, iOS SDK targets
   - Install maturin ≥1.7.0
   - Create BeeWare Python-Apple-support cross-compilation venv
   - Build pydantic-core wheel targeting `aarch64-apple-ios` and `aarch64-apple-ios-sim`
   - Test the wheel in a minimal Briefcase iOS app

### Phase 2: iOS App Shell (3-5 weeks)

3. **Create Briefcase project** (~1 week)
   - Initialize Briefcase iOS project
   - Configure `pyproject.toml` with all NPPS4 dependencies
   - Include NPPS4 source, alembic configs, game data
   - Add custom iOS wheels to project (pydantic-core, any others)

4. **Implement iOS `main.py` (similar to `android_main.py`)** (~1 week)
   - Port the `android_main.py` lifecycle API to iOS
   - `setup_server()`, `start_server()`, `stop_server()`
   - Database import/export
   - Add `sys.platform == "ios"` handling in config.py, evloop.py, requirements
   - **Critical**: iOS forbids `fork()`/`spawn()` — `subprocess` and `multiprocessing` raise `PermissionError`. The `android_main.py` pattern already avoids this (runs uvicorn in-process via `uvicorn.Server.run()`), so the same approach works. The `main.py` entrypoint (which uses `subprocess.call` for alembic/gunicorn) must NOT be used on iOS

5. **Build native iOS UI** (~2-3 weeks)
   - Swift/SwiftUI wrapper app with:
     - Server start/stop controls
     - Status indicator (server running/stopped)
     - Server URL display (for manual client configuration)
     - Database management (import/export/reset)
     - Configuration editor (server settings)
   - Integrate with Python via [PythonKit](https://github.com/pvieito/PythonKit) (Pythonic Swift API) or direct C-level embedding (`Py_Initialize()` / `PyRun_SimpleString()`)

### Phase 3: Client Integration & Distribution (2-3 weeks)

6. **Game client connectivity** (~1 week)
   - Test patched iOS client connecting to embedded server on localhost
   - Handle the "two apps" problem:
     - Option A: Use a URL scheme to launch the game client from the server app
     - Option B: Provide clear instructions for configuring the patched client
   - Verify game functionality end-to-end

7. **AltStore/TrollStore packaging** (~1 week)
   - `briefcase open iOS` → Xcode, configure signing, Archive → `.ipa`
   - Create AltStore source JSON (see format above)
   - Host `.ipa` and source JSON
   - Test installation via AltStore
   - Test on TrollStore (if available)
   - Document the installation process

8. **Testing & polish** (~1 week)
   - Test on multiple iOS versions (15+)
   - Test app suspension/resume behavior
   - Test memory pressure handling
   - Test database integrity under abrupt termination

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

4. **Background handling** — iOS kills apps ~30 seconds after backgrounding:
   - Use `BGTaskScheduler` for brief background execution
   - Checkpoint database (SQLite WAL flush) on `applicationWillResignActive`
   - Fast resume on `applicationDidBecomeActive`
   - Accept that the server stops when the app is backgrounded (same UX as game itself)

### Nice-to-Have Changes

5. **Reduced import time** — Briefcase apps load all Python at startup. Lazy imports help.
6. **Memory budget** — iOS gives ~300-500MB to foreground apps on modern devices. NPPS4 uses ~50-100MB. Comfortable headroom.

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| pydantic-core fails to cross-compile for iOS | Medium | **Blocks project** | Fall back to Pydantic v1 (Option 2b), or contribute the fix upstream to maturin/PyO3 |
| BeeWare/Briefcase has iOS bugs | Medium | Delays | Active project, responsive maintainers, file issues |
| Game client can't connect to localhost on iOS | Low | **Blocks project** | Standard iOS networking, well-tested by other apps |
| App gets killed during gameplay | Low | Poor UX | Users must keep server app foregrounded (split-screen or app switching) |
| AltStore 7-day re-signing annoys users | Medium | Poor UX | Recommend TrollStore where available; AltStore PAL in EU |
| Apple blocks embedded Python in sideloaded apps | Very Low | **Blocks project** | Not subject to App Store review; Apple doesn't police sideloaded app internals |

---

## Architecture Diagram

```
┌─────────────────────────────────────────────┐
│                iOS Device                    │
│                                              │
│  ┌─────────────────────────────────────────┐ │
│  │    NPPS4 Server App (via AltStore)      │ │
│  │                                         │ │
│  │  ┌──────────────────┐  ┌─────────────┐ │ │
│  │  │ Swift UI Shell   │  │ Python      │ │ │
│  │  │ (Start/Stop/     │──│ Runtime     │ │ │
│  │  │  Status/Config)  │  │ (BeeWare)   │ │ │
│  │  └──────────────────┘  │             │ │ │
│  │                        │ FastAPI     │ │ │
│  │                        │ uvicorn     │ │ │
│  │                        │ SQLite      │ │ │
│  │                        │ 127.0.0.1   │ │ │
│  │                        │ :51376      │ │ │
│  │                        └─────────────┘ │ │
│  └────────────────────────────┬────────────┘ │
│                               │ localhost    │
│  ┌────────────────────────────┴────────────┐ │
│  │    Patched SIF Client (via AltStore)    │ │
│  │    Points to 127.0.0.1:51376            │ │
│  └─────────────────────────────────────────┘ │
└──────────────────────────────────────────────┘
```

---

## Recommendation

**The embedded Python route via BeeWare Briefcase is viable and recommended for AltStore distribution.**

The critical path is:
1. Replace `pycryptodomex` → `cryptography` (pyca) — **low risk, 2 days**
2. Cross-compile `pydantic-core` for iOS via maturin — **medium risk, 2-3 weeks**
3. Build the Briefcase iOS app shell — **low risk, 3-5 weeks**
4. Package and test with AltStore — **low risk, 1-2 weeks**

**Total: 2-3 months** with the crypto library swap making the biggest single dependency (pycryptodomex) a non-issue.

The pydantic-core cross-compilation is the only real unknown, but the tooling (maturin iOS support, BeeWare's success with the `cryptography` package) strongly suggests it's achievable. If it proves impossible, falling back to Pydantic v1 is ugly but workable.

---

## References

- [BeeWare Python-Apple-support](https://github.com/beeware/Python-Apple-support)
- [BeeWare Briefcase iOS docs](https://briefcase.beeware.org/en/v0.3.16/reference/platforms/iOS.html)
- [BeeWare mobile wheels leaderboard](https://beeware.org/mobile-wheels/)
- [BeeWare November 2025 update (cryptography iOS wheels)](https://beeware.org/news/buzz/november-2025-status-update/)
- [Maturin iOS support (v1.7.0)](https://github.com/PyO3/maturin/releases/tag/v1.7.0)
- [Maturin iOS issue #1742](https://github.com/PyO3/maturin/issues/1742)
- [pydantic-core iOS support issue #1170](https://github.com/pydantic/pydantic-core/issues/1170)
- [kivy-ios pycryptodome issue #701](https://github.com/kivy/kivy-ios/issues/701)
- [kivy-ios pycryptodome issue #755](https://github.com/kivy/kivy-ios/issues/755)
- [PEP 730 — iOS platform tags](https://peps.python.org/pep-0730/)
- [pyca/cryptography RSA docs](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/rsa/)
- [PyO3 iOS/Android cross-compilation discussion #4824](https://github.com/PyO3/pyo3/discussions/4824)
- [Pydantic pure-Python fallback discussion #10859](https://github.com/pydantic/pydantic/discussions/10859)
- [Python-Apple-support static linking requirement #56](https://github.com/beeware/Python-Apple-support/issues/56)
- [CPython iOS usage docs](https://docs.python.org/3/using/ios.html)
- [Pyto — Python IDE on App Store (proof of concept)](https://github.com/ColdGrub1384/Pyto)
- [PythonKit — Swift-Python bridge](https://github.com/pvieito/PythonKit)
- [AltStore source format docs](https://faq.altstore.io/developers/make-a-source)
- [Python-Apple-support USAGE.md](https://github.com/beeware/Python-Apple-support/blob/main/USAGE.md)
