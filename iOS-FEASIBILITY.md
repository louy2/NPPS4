# iOS Self-Contained Experience: Feasibility Analysis

## Executive Summary

Providing a self-contained NPPS4 experience on iOS (server + patched client on one device) is **significantly harder than on Android** but not impossible. The Android approach uses Chaquopy (Python embedded in a native Android app) which has no iOS equivalent. iOS alternatives exist but each involves substantial trade-offs in complexity, App Store compliance, and user experience.

**Feasibility rating: Moderate-to-Hard. Estimated effort: 3-6 person-months** depending on the chosen approach.

---

## How Android Works Today

The Android self-contained experience uses:

1. **Chaquopy** — a Gradle plugin that embeds CPython into an Android app. The native Android (Java/Kotlin) app starts the Python server via `android_main.py`.
2. **Server binds to `127.0.0.1:51376`** — only accessible on-device (loopback).
3. **Patched game client** — a modified APK that points to the local server instead of the official one. The client patcher at `ethanaobrien.github.io/sif-patcher/` supports both iOS and Android clients.
4. **SQLite database** — the server's default storage, requiring no external database server.
5. The Android app provides lifecycle management: `setup_server()`, `start_server()`, `stop_server()`, and database import/export.

This is clean and self-contained because Android allows:
- Embedding arbitrary interpreters (Python via Chaquopy)
- Running background services with network sockets
- Sideloading APKs without a store
- Apps binding to localhost ports

---

## iOS Constraints

### Platform Restrictions
| Constraint | Impact |
|---|---|
| **No embedded interpreters** (App Store policy) | Cannot ship CPython in an App Store app. JIT/interpreters are restricted under App Review Guideline 2.5.2 |
| **No sideloading** (without jailbreak or AltStore) | Must use TestFlight, AltStore, TrollStore, or jailbreak to install non-store apps |
| **Background execution limits** | iOS aggressively suspends background apps. A server process will be killed within ~30 seconds of backgrounding |
| **No Chaquopy equivalent** | There is no production-ready "embed Python in iOS app" SDK comparable to Chaquopy |
| **App Sandbox** | Each app is sandboxed; two separate apps (server + game client) cannot communicate over localhost without Network Extension entitlements |

### What Still Works
- **SQLite**: Works natively on iOS, no issue
- **Localhost networking**: An app *can* listen on `127.0.0.1` while in the foreground
- **The game client patcher**: Already supports iOS (IPA patching) per the README

---

## Approach Options

### Option A: Single App with Embedded Python (Recommended)

**Concept**: Build a single iOS app that embeds both the Python server and the patched game client (via WKWebView or an embedded game engine).

**Technical approach**:
- Use **Python-Apple-support** (BeeWare project) or **Kivy's python-for-ios** to cross-compile CPython and all dependencies for iOS/ARM64
- Compile the pure-Python NPPS4 server and its dependencies into a framework
- The native iOS app starts the Python server on `127.0.0.1:51376` in-process
- The game client would need to be embedded or launched alongside

**NPPS4 dependency analysis for iOS compilation**:

| Dependency | iOS Compilable? | Notes |
|---|---|---|
| `aiosqlite` | Yes | Pure Python, wraps built-in sqlite3 |
| `alembic` | Yes | Pure Python |
| `fastapi` | Yes | Pure Python |
| `honkypy` | Yes | Pure Python wheel (`py3-none-any`) |
| `httpx` | Yes | Pure Python |
| `itsdangerous` | Yes | Pure Python |
| `jinja2` | Yes | Pure Python |
| `pycryptodomex` | **Needs cross-compile** | Contains C extensions for AES, RSA, SHA. Must be cross-compiled for ARM64. This is the hardest dependency |
| `pydantic` / `pydantic-core` | **Needs cross-compile** | pydantic-core is written in Rust. Requires Rust cross-compilation for iOS ARM64 |
| `python-multipart` | Yes | Pure Python |
| `sqlalchemy` | Yes (mostly) | Core is pure Python; optional C extensions can be skipped |
| `uvicorn` | Yes | Pure Python |
| `httptools` | **Needs cross-compile** | C extension (optional, can fall back to pure Python parser) |
| `uvloop` | **Skip** | Not needed; fall back to default asyncio event loop (already handled in `evloop.py`) |

**Key challenge**: Cross-compiling `pycryptodomex` and `pydantic-core` for iOS ARM64. Both have significant native code.

**Effort: 4-6 months**

**Pros**:
- True self-contained experience
- No jailbreak required (for sideloading via AltStore/TrollStore)
- Follows the same architectural pattern as Android

**Cons**:
- Cannot go on the App Store (interpreter policy)
- Cross-compiling native Python extensions for iOS is fragile
- Must be sideloaded (AltStore refreshes every 7 days, TrollStore requires specific iOS versions)
- Background execution remains a problem—server dies when app is backgrounded

---

### Option B: On-Device Container / Linux VM

**Concept**: Run NPPS4 in a lightweight Linux environment on iOS via iSH, a-Shell, or UTM.

**Technical approach**:
- **iSH** (Alpine Linux userspace emulator, available on App Store) can run Python
- **a-Shell** (App Store app with Python support) could potentially run the server
- **UTM** (QEMU-based VM for iOS) can run full Linux with Python

**Effort: 1-2 months** (mostly documentation and testing)

**Pros**:
- No custom iOS app development needed
- Reuses the server as-is
- Some options (iSH, a-Shell) are on the App Store

**Cons**:
- **Very slow**: iSH uses x86 emulation, not native ARM. Server would be 10-100x slower
- **a-Shell** has limited Python package support (may not support pycryptodomex)
- **UTM** requires sideloading and significant RAM/storage
- User experience is poor (terminal-based setup)
- Background execution still limited—iSH/a-Shell get suspended
- Game client must run as a separate app, and cross-app localhost communication is unreliable on iOS

---

### Option C: Rewrite Server in Swift/Native iOS

**Concept**: Port NPPS4 to Swift using native iOS frameworks (Vapor or SwiftNIO for the HTTP server, GRDB or Core Data for SQLite).

**Technical approach**:
- Rewrite the FastAPI server in **Vapor** (Swift web framework)
- Use **CryptoKit** / **Security.framework** for RSA/AES/HMAC (all required crypto is available natively)
- Use **GRDB.swift** or raw SQLite3 C API for database access
- Embed in a single app alongside the game client

**Effort: 6+ months** (full rewrite of ~15k+ lines of Python)

**Pros**:
- Truly native, best performance
- Could potentially go on TestFlight
- No background execution issues (server runs in-process)
- No interpreter policy violations

**Cons**:
- Enormous effort—full server rewrite
- Must maintain two codebases going forward (Python + Swift)
- Feature parity would lag behind the Python version

---

### Option D: Proxy-Only (Server Runs Elsewhere)

**Concept**: Don't run the server on iOS at all. Instead, provide a companion Mac/PC app or remote server, and only patch the iOS game client to connect to it.

**Technical approach**:
- Distribute a macOS/Windows/Linux server binary (already supported via PyInstaller in `npps4.spec`)
- Patch the iOS game client (IPA) to point to `<LAN IP>:51376`
- Sideload the patched IPA via AltStore/Sideloadly

**Effort: 1-2 weeks** (documentation only; infrastructure already exists)

**Pros**:
- Already works today with existing tooling
- No iOS server development needed
- Best user experience for the game itself

**Cons**:
- **Not self-contained**: requires a separate computer running the server
- Only works on local network (or requires VPN/port forwarding for remote)

---

### Option E: Local Network with macOS (Hybrid Self-Contained)

**Concept**: Ship a polished macOS app (for Mac or Apple Silicon) that runs the server, paired with a patched iOS client. Use Bonjour/mDNS for zero-configuration discovery.

**Technical approach**:
- Package NPPS4 as a macOS app using PyInstaller (spec already exists) or py2app
- Add Bonjour service advertisement so the iOS client can auto-discover the server
- Patch iOS client to scan for local servers

**Effort: 1-2 months**

**Pros**:
- Leverages existing PyInstaller infrastructure
- Good UX with auto-discovery
- macOS has no interpreter restrictions

**Cons**:
- Requires a Mac (not truly self-contained on iOS alone)

---

## Specific Code Changes Needed

Regardless of approach, these server-side changes would help iOS support:

### 1. Background Keep-Alive (Options A/B)
The server needs to handle being suspended and resumed. iOS sends `applicationWillResignActive` / `applicationDidBecomeActive` signals. The server should:
- Gracefully pause when backgrounded
- Resume quickly when foregrounded
- Use iOS background task API for brief extensions

### 2. Foreground-Only Server Mode
Add a configuration option for "foreground-only" mode where the server:
- Doesn't rely on persistent background execution
- Checkpoints database state aggressively (SQLite WAL mode already helps)
- Handles abrupt termination gracefully

### 3. Reduced Memory Footprint
iOS devices have tighter memory limits (especially with two "apps" running). Consider:
- Lazy-loading game data modules (already partially done)
- Reducing default worker count to 1 (already the case in `android_main.py`)
- Connection pooling limits for SQLite

### 4. `evloop.py` Already Handles Missing uvloop
The event loop fallback (`evloop.py:28-30`) already gracefully falls back to the default asyncio loop when uvloop is unavailable, which is good for iOS where uvloop won't compile.

### 5. Platform Detection
Add `sys.platform == "ios"` handling alongside the existing `sys.platform == "android"` checks:
- `config.py:106` — module loading behavior
- `requirements.txt` — conditional dependencies
- `evloop.py` — event loop selection

---

## Storage and Resource Requirements

The server has modest resource needs, well within iOS device capabilities:

| Resource | Requirement | iOS Feasible? |
|---|---|---|
| **CPU** | Light (async I/O, single worker) | Yes |
| **RAM** | ~50-100 MB typical | Yes |
| **Storage (server code)** | ~10-20 MB | Yes |
| **Storage (game database)** | ~50-500 MB depending on content | Yes |
| **Storage (game assets)** | Can use `n4dlapi` backend to download on-demand | Yes |
| **Network** | Localhost only (loopback) | Yes (while foregrounded) |

---

## Recommendation

**For immediate impact** (weeks, not months):
- **Option D** — Document and streamline the existing "server on PC + patched iOS client" workflow. This already works.

**For a true self-contained experience** (months):
- **Option A** — Embedded Python in a single iOS app, distributed via AltStore/TrollStore. This mirrors the Android architecture most closely. The main work is:
  1. Cross-compiling `pycryptodomex` and `pydantic-core` for iOS ARM64
  2. Building an iOS app shell that manages the Python server lifecycle
  3. Handling iOS background execution limits
  4. Packaging and distribution via AltStore/TrollStore

**For long-term sustainability** (if iOS is a primary target):
- **Option C** — Native Swift rewrite, but only if there's a team willing to maintain dual codebases.

---

## Summary Table

| Approach | Self-Contained? | Effort | UX Quality | App Store? |
|---|---|---|---|---|
| **A: Embedded Python** | Yes | 4-6 months | Good | No (sideload) |
| **B: iSH / a-Shell** | Partially | 1-2 months | Poor | Partially |
| **C: Swift Rewrite** | Yes | 6+ months | Excellent | Possible |
| **D: Server on PC** | No | 1-2 weeks | Good | N/A |
| **E: macOS + iOS** | Paired | 1-2 months | Good | N/A |
