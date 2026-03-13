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

## iOS Tooling Landscape (as of early 2026)

### BeeWare / Briefcase (Recommended)

[BeeWare's Python-Apple-support](https://github.com/beeware/Python-Apple-support) provides pre-compiled CPython frameworks for iOS. [Briefcase](https://briefcase.beeware.org/en/v0.3.16/reference/platforms/iOS.html) is BeeWare's packaging tool that generates Xcode projects from Python apps.

Key milestones reached:
- **pip 24.3** supports iOS platform tags per [PEP 730](https://peps.python.org/pep-0730/)
- **PyPI now accepts iOS wheel uploads** (enabled in 2025)
- **cibuildwheel** supports iOS builds
- BeeWare has published [iOS wheels for the `cryptography` package](https://beeware.org/news/buzz/november-2025-status-update/) (Rust-based, using maturin)
- [Mobile wheel tracking](https://beeware.org/mobile-wheels/) covers the top 360 binary packages

### Kivy / python-for-ios (Alternative)

[kivy-ios](https://github.com/kivy/kivy-ios) (latest: 2025.5.17) provides a recipe-based toolchain. No pycryptodome recipe exists ([issue #701](https://github.com/kivy/kivy-ios/issues/701), [issue #755](https://github.com/kivy/kivy-ios/issues/755)). The cross-compilation environment sets the C compiler to `/bin/false`, causing C extension builds to fail. Less suitable than BeeWare for a non-Kivy server app.

### Maturin / PyO3 iOS support

[Maturin v1.7.0 added initial iOS support](https://github.com/PyO3/maturin/issues/1742). Subsequent releases added PEP 730-compliant wheel naming and iOS cross-platform venv support. This means Rust-based Python packages (like pydantic-core) can theoretically be cross-compiled for iOS, though pydantic-core itself hasn't done this yet.

### AltStore Distribution

AltStore installs IPAs via sideloading. Key facts:
- App must be a standard IPA file
- Standard AltStore requires re-signing every 7 days (free developer account)
- AltStore PAL (EU only under Digital Markets Act) allows permanent installs
- TrollStore (specific iOS versions, e.g., 14.0-16.6.1) allows permanent installs without re-signing
- No App Store review guidelines apply — embedded interpreters are fine

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

5. **Build native iOS UI** (~2-3 weeks)
   - Swift/SwiftUI wrapper app with:
     - Server start/stop controls
     - Status indicator (server running/stopped)
     - Server URL display (for manual client configuration)
     - Database management (import/export/reset)
     - Configuration editor (server settings)
   - Integrate with Python via PythonKit or direct C-level embedding

### Phase 3: Client Integration & Distribution (2-3 weeks)

6. **Game client connectivity** (~1 week)
   - Test patched iOS client connecting to embedded server on localhost
   - Handle the "two apps" problem:
     - Option A: Use a URL scheme to launch the game client from the server app
     - Option B: Provide clear instructions for configuring the patched client
   - Verify game functionality end-to-end

7. **AltStore/TrollStore packaging** (~1 week)
   - Build release IPA from Xcode project
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
