# XakuMedia — Project Overview

## 1. Application Purpose & Vision

**XakuMedia** is a high-performance, local-first Windows 11 desktop bulk media downloader and manager developed under the **XAKURAII** identity.

The application enables users to discover, preview, organize, and download publicly accessible images and videos from direct URLs, multi-item galleries, and media platforms. Built with an uncompromising focus on reliability, user control, source quality preservation, and local data ownership, XakuMedia functions completely standalone without requiring cloud accounts, central databases, or paid third-party scraping APIs.

### Core Operating Principles
- **Local-First & Private:** All metadata, preferences, scan history, credentials, and downloaded assets reside exclusively on the user's local machine in an SQLite database and local directories. No telemetry or user data is transmitted to external servers.
- **Source-Faithful Quality:** The application discovers and exposes only source-supported video resolutions, audio codecs, and image formats. It never invents unavailable resolutions or performs lossy video re-encoding unless explicitly demanded.
- **Non-Destructive Overwrite Protection:** Existing files on disk are never silently overwritten. The engine enforces atomic `.part` staging, disk sequence scanning, and sequential naming (`{user}_{vdo|img}_{001}.{ext}`).
- **Crash-Resistant & Recoverable:** Active download tasks survive application crashes and power outages. At startup, the recovery engine audits on-disk partial files against SQLite state, preserves downloaded bytes, and resumes queue processing.
- **Strict Security Boundaries:** Multi-layer defenses prevent Server-Side Request Forgery (SSRF), NTFS Alternate Data Streams (ADS), Windows DOS reserved device naming exploits, UNC credential leaking, and path traversal.

---

## 2. Main Features

### 2.1 URL Scanning & Multi-Provider Media Extraction
- **Direct Resource Scanner:** Rapid HTTP `HEAD` and Range `GET` probing for direct video (`.mp4`, `.webm`, `.mov`, `.mkv`, etc.) and image (`.jpg`, `.png`, `.webp`, `.gif`, `.avif`, etc.) links with Content-Disposition parsing (`backend/src/xakumedia/scanners/direct.py`).
- **Platform Video Extractor (`yt-dlp`):** Full stream discovery, audio/video stream separation, resolution mapping (2160p 4K down to 360p), FPS, container, and codec extraction (`backend/src/xakumedia/extractors/video.py`).
- **Multi-Item Gallery Extractor (`gallery-dl`):** Zero-stdio-pollution `DataJob` extraction for multi-image albums, social posts, and artist collections with sequential `#index` positioning (`backend/src/xakumedia/extractors/gallery.py`).
- **Unified Classification Pipeline:** Automatically attempts direct probing, then gallery extraction, then video extraction, saving all discovered assets to the local SQLite database (`backend/src/xakumedia/server/dispatcher.py`).

### 2.2 Download Queue & Worker Scheduling
- **Multi-Slot Concurrent Queue:** Configurable active concurrency (1–10 concurrent downloads, default 3) backed by a Python `ThreadPoolExecutor` and FIFO pending queue (`backend/src/xakumedia/downloader/manager.py`).
- **Batch Operations:** 1-click batch actions including **Pause All**, **Resume All**, **Cancel All**, **Clear Completed**, and selective gallery bulk downloading with checkbox selection, Select All, Deselect All, and Invert controls.
- **HTTP Range Resumption:** Seamless continuation of interrupted transfers via `Range: bytes={existing}-` headers (HTTP 206 Partial Content) without redownloading previously transferred bytes.
- **Real-Time Telemetry:** Sub-150ms live progress streaming reporting percentage, bytes downloaded, total file size, transfer speed, and estimated time of arrival (ETA).

### 2.3 Bandwidth Throttling & Network Rate Limits
- **Token-Bucket Throttler:** Thread-safe, micro-sliced rate limiter (`BandwidthThrottler` in `backend/src/xakumedia/downloader/throttler.py`) shared across all active download threads.
- **Dynamic Speed Adjustment:** Global speed limit adjustments (Unlimited, 500 KB/s, 1 MB/s, 2 MB/s, 5 MB/s, 10 MB/s, 20 MB/s, 50 MB/s, or custom) take effect immediately without aborting or restarting active transfers.

### 2.4 Local SQLite Persistence & Media Library
- **Relational Storage:** SQLite 3 in Write-Ahead Logging (WAL) mode with foreign keys enabled, busy timeouts, and automated schema migration tracking (`CURRENT_SCHEMA_VERSION = 4` in `backend/src/xakumedia/db/schema.py`).
- **Media Library Management:** Real-time search, category filtering (Image, Video, Audio), container filtering (`.mp4`, `.webm`, `.jpg`, `.png`, etc.), and 5-way sorting (`newest`, `oldest`, `title`, `size_desc`, `size_asc`).
- **Metadata Export:** Instant export of comprehensive JSON metadata for any discovered or downloaded item (`backend/src/xakumedia/db/repository.py`).
- **Safe Disk Deletion:** Confirmation modal allowing removal from SQLite library with optional simultaneous permanent file deletion from disk.

### 2.5 Media Processing & Inspection
- **FFmpeg Stream Multiplexing:** Lossless `-c copy` multiplexing for video-only and audio-only streams with automatic AAC transcoding fallback when MP4 container requirements dictate (`backend/src/xakumedia/processor/ffmpeg.py`).
- **Technical Media Inspection:** Deep probing via `ffprobe` extracting streams, durations, bitrates, dimensions, pixel formats, and codecs.
- **Thumbnail Caching:** Deterministic thumbnail generation and disk caching (`%LOCALAPPDATA%\XakuMedia\cache\thumbnails\`) using Pillow for images and FFmpeg frame grabbing for videos (`backend/src/xakumedia/processor/thumbnail.py`).

### 2.6 In-App Preview & Privileged Streaming
- **Video/Audio Player Modal:** Built-in playback supporting local files and remote streams with variable speed controls (0.5x, 1x, 1.25x, 1.5x, 2x).
- **High-Resolution Image Lightbox:** Smooth pan, zoom (25% to 400%), 90° rotation, reset controls, and keyboard navigation (`Escape`, `+`, `-`, `0`, `R`).
- **Privileged `media-loader://` Protocol:** Custom Electron protocol handler supporting HTTP 206 Partial Content range requests, streaming local files to Chromium `<video>`, `<audio>`, and `<img>` tags while enforcing file extension whitelisting and NTFS ADS defenses (`desktop/main/index.ts`).

### 2.7 Session Credentials & Cookie Management
- **Netscape Cookie Engine:** Fault-tolerant parser and serializer handling standard tab-delimited format and `#HttpOnly_` prefixes (`backend/src/xakumedia/auth/cookies.py`).
- **Local Browser Cookie Extraction:** Direct DPAPI-backed cookie decryption from Edge, Chrome, Firefox, Brave, Opera, and Vivaldi profiles using `yt-dlp`'s cookiejar engine.
- **Subdomain Hierarchy Header Matching:** Domain-specific request headers with automatic parent domain fallback (e.g. `v.redd.it` inherits rules from `redd.it`) injected into HTTPX, yt-dlp, and gallery-dl (`backend/src/xakumedia/auth/headers.py`).

### 2.8 Saved Sources & Differential Discovery
- **Source Bookmarking:** Bookmarking channels, galleries, and user profiles with custom tags, title overrides, and thumbnail previews (`backend/src/xakumedia/models/source.py`).
- **Differential Rescan Engine:** $O(1)$ set reconciliation comparing discovered URLs against SQLite history to isolate new items from already discovered items (`backend/src/xakumedia/sources/rescan.py`).
- **Incremental Review Modal:** Visual diff overview (`X new items / Y total`) with 1-click batch download of new delta items.

### 2.9 Dual-Mode Frontend Architecture
- **Desktop Electron Client:** Full media downloader interface rendered when running inside Electron with `window.api` bridge (`frontend/src/App.tsx`).
- **Marketing & Distribution Landing Page:** Public website with variable typography (Space Grotesk, Inter, JetBrains Mono), dual light/dark theme system, SmartScreen security guidance, animated hero, and direct GitHub release download links (`frontend/src/landing/LandingPage.tsx`).

---

## 3. Technology Stack

| Layer | Technology | Version | Purpose | Evidence |
| :--- | :--- | :--- | :--- | :--- |
| **Desktop Shell** | Electron | `33.4.11` | Application container, window management, native dialogs, process isolation | `package.json`, `desktop/main/index.ts` |
| **Desktop Shell** | Node.js | `v24.14.0` | Build orchestration and main process execution runtime | `scripts/dev.mjs`, `docs/CURRENT_STATE.md` |
| **Frontend Framework** | React | `18.3.1` | User interface component tree | `frontend/package.json`, `frontend/src/App.tsx` |
| **Frontend Language** | TypeScript | `5.6.2` | Type-safe contracts across UI and desktop bridge | `frontend/tsconfig.json`, `desktop/shared/types.ts` |
| **Frontend Bundler** | Vite | `5.4.21` | High-speed ESM development server and production bundler | `frontend/vite.config.ts` |
| **Frontend Styling** | Tailwind CSS | `3.4.14` | Design system, layout, and theme token styling | `frontend/tailwind.config.js`, `frontend/src/index.css` |
| **Frontend Icons** | Lucide React | `0.460.0` | Consistent iconography across views and controls | `frontend/src/App.tsx` |
| **Backend Runtime** | Python | `3.12.10` | Core media engine, I/O streaming, and subprocess worker | `backend/pyproject.toml`, `docs/CURRENT_STATE.md` |
| **Data Validation** | Pydantic | `2.9.2` | Strictly validated domain models and serialization | `backend/src/xakumedia/models/` |
| **HTTP Client** | HTTPX | `0.27.2` | Chunked streaming, Range requests, and security probing | `backend/src/xakumedia/downloader/stream.py` |
| **Database** | SQLite 3 | Built-in | Embedded relational persistence in WAL mode | `backend/src/xakumedia/db/connection.py` |
| **Media Processing** | FFmpeg / FFprobe | `n4.4.2` | Stream inspection, lossless copy multiplexing, format conversion | `backend/src/xakumedia/processor/ffmpeg.py` |
| **Image Processing** | Pillow (PIL) | `10.4.0` | Image thumbnail generation and format conversion | `backend/src/xakumedia/processor/thumbnail.py` |
| **Media Extraction** | yt-dlp | `2024.8.6+` | Video platform extraction, format resolution, DPAPI cookies | `backend/src/xakumedia/extractors/video.py` |
| **Media Extraction** | gallery-dl | `1.27.0+` | Multi-image gallery and artist collection parsing | `backend/src/xakumedia/extractors/gallery.py` |
| **Packaging** | Electron Builder | `25.1.8` | Windows NSIS installer and portable executable generation | `config/electron-builder.yml` |
| **Testing** | Pytest | `8.3.3` | Python automated test suite (140 tests) | `backend/tests/` |
| **Linting** | Ruff | `0.7.4` | Python code analysis and formatting | `backend/pyproject.toml` |

---

## 4. Project Structure

```text
XakuMedia/
├── .agents/                        # Local AI instructions & workflows
│   └── AGENTS.md                   # Project agent guidelines & milestones
├── .archify/                       # Architecture diagrams and specifications
├── backend/                        # Python 3.12 Media Engine
│   ├── pyproject.toml              # PEP 621 package manifest, dependencies & tooling
│   ├── src/
│   │   └── xakumedia/              # Main Python package
│   │       ├── __init__.py         # Package root, version definition
│   │       ├── auth/               # Authentication, cookies & headers
│   │       │   ├── cookies.py      # Netscape parser & browser DPAPI extractor
│   │       │   ├── headers.py      # Subdomain hierarchy header resolver
│   │       │   └── models.py       # CookieEntry & CookieProfileRecord models
│   │       ├── core/               # Configuration & logging infrastructure
│   │       │   ├── config.py       # AppConfig & platformdirs path management
│   │       │   └── logging.py      # Structured console logging
│   │       ├── db/                 # SQLite persistence layer
│   │       │   ├── connection.py   # Connection pool, WAL mode, session context
│   │       │   ├── repository.py   # MediaRepository CRUD & query operations
│   │       │   └── schema.py       # DDL definitions & migrations (V1 to V4)
│   │       ├── downloader/         # Download queue & stream execution
│   │       │   ├── manager.py      # DownloadManager thread pool & queue state
│   │       │   ├── recovery.py     # TaskRecoveryService for crashed transfers
│   │       │   ├── stream.py       # Chunked streaming I/O with Range resumption
│   │       │   └── throttler.py    # BandwidthThrottler token bucket engine
│   │       ├── exceptions/         # Domain exception hierarchy
│   │       │   └── base.py         # XakuMediaError and specialized exceptions
│   │       ├── extractors/         # Extraction adapters
│   │       │   ├── gallery.py      # gallery-dl DataJob integration
│   │       │   └── video.py        # yt-dlp metadata & format extraction
│   │       ├── models/             # Pydantic V2 domain models
│   │       │   ├── media.py        # MediaItem, MediaFormatInfo, MediaType
│   │       │   ├── quality.py      # VideoResolution, Container, ImageFormat
│   │       │   ├── queue.py        # DownloadTask, TaskStatus, ProgressUpdate
│   │       │   ├── source.py       # SavedSource, IncrementalScanResult
│   │       │   └── url.py          # ClassifiedUrl, UrlCategory
│   │       ├── processor/          # Media inspection & transformation
│   │       │   ├── ffmpeg.py       # FFmpeg stream merge & format conversion
│   │       │   └── thumbnail.py    # Pillow & FFmpeg thumbnail caching
│   │       ├── scanners/           # URL probing scanners
│   │       │   └── direct.py       # Direct URL HEAD/GET MIME prober
│   │       ├── server/             # Stdio JSON-RPC 2.0 communication
│   │       │   ├── __main__.py     # Engine CLI entry point
│   │       │   ├── dispatcher.py   # RpcDispatcher method registry
│   │       │   ├── loop.py         # Stdio event loop & notification sender
│   │       │   └── protocol.py     # JSON-RPC 2.0 message models
│   │       ├── sources/            # Source bookmarking & differential scans
│   │       │   └── rescan.py       # Differential discovery & incremental rescan
│   │       └── utils/              # Security and path utilities
│   │           ├── naming.py       # Sequential filename formatting & disk scan
│   │           ├── paths.py        # Windows path validation & ADS defense
│   │           └── security.py     # SSRF defense & IP literal parser
│   └── tests/                      # Pytest automated test suite (140 tests)
├── build/                          # Packaged runtime assets & application icons
│   ├── icon.ico                    # Windows application & installer icon
│   ├── icon.png                    # High-resolution 512x512 branding icon
│   └── bin/                        # Bundled static FFmpeg / FFprobe binaries
├── config/                         # Packaging configuration
│   └── electron-builder.yml        # Windows NSIS & Portable build configuration
├── desktop/                        # Electron Desktop Shell
│   ├── main/                       # Electron main process
│   │   ├── index.ts                # App lifecycle, IPC handlers, CSP, media-loader://
│   │   └── python-bridge.ts        # Child process supervisor & stdio JSON-RPC client
│   ├── preload/                    # Context-isolated secure preload bridge
│   │   └── index.ts                # Typed window.api DesktopApi implementation
│   └── shared/                     # Shared TypeScript interfaces & contracts
│       └── types.ts                # Common data models between main and renderer
├── dist-package/                   # Generated Windows distribution packages
│   ├── XakuMedia-Setup-0.1.0.exe   # Windows NSIS installer (167 MB)
│   ├── XakuMedia-Portable-0.1.0.exe# Windows Portable executable (148 MB)
│   └── win-unpacked/               # Unpacked standalone distribution bundle
├── docs/                           # Architectural, database, and setup documentation
│   ├── ARCHITECTURE.md             # System boundaries, component design & ADRs
│   ├── CURRENT_STATE.md            # Active milestone status & verification records
│   ├── DATABASE.md                 # SQLite database schema, tables & indexing
│   ├── DEPLOYMENT.md               # Landing page Vercel deployment guide
│   ├── DEVELOPMENT_ROADMAP.md      # Detailed milestone roadmap
│   ├── DOMAIN_MODEL.md             # Core business domains, entities & business rules
│   ├── IPC_API.md                  # Comprehensive IPC & JSON-RPC API reference
│   ├── PROJECT_OVERVIEW.md         # Application overview, features & stack
│   ├── RELEASE_NOTES.md            # v0.1.0 production release notes
│   ├── SECURITY.md                 # Security architecture, SSRF & IPC defenses
│   ├── SETUP.md                    # Developer environment setup instructions
│   └── SYSTEM_FLOWS.md             # End-to-end execution workflows & diagrams
├── frontend/                       # React + Vite + Tailwind User Interface
│   ├── index.html                  # HTML entry with theme pre-paint init script
│   ├── package.json                # Frontend package dependencies & scripts
│   ├── tailwind.config.js          # Design system color tokens & typography
│   ├── vite.config.ts              # Vite configuration (relative base: "./")
│   ├── public/                     # Static icons, logos, and og-image.png
│   └── src/
│       ├── App.tsx                 # Main desktop application interface (3,500+ lines)
│       ├── index.css               # Global CSS, theme variables & font bindings
│       ├── main.tsx                # Dual-mode view router (Desktop vs Landing)
│       ├── components/             # Reusable UI views
│       │   ├── SavedSourcesView.tsx# Saved sources management & rescan modal
│       │   └── SettingsView.tsx    # Settings, speed limits, cookies & credentials
│       └── landing/                # Public marketing website components
│           ├── downloadConfig.ts   # GitHub release download URLs & metadata
│           ├── FaqSection.tsx      # Interactive document-style accordion FAQ
│           ├── FeaturesSection.tsx # Feature grid & technical capabilities
│           ├── HeroSection.tsx     # Hero banner with simulated app mock
│           ├── InstallationSection.tsx # Step-by-step setup guide
│           ├── LandingFooter.tsx   # Footer with branding and repository links
│           ├── LandingPage.tsx     # Landing page layout & composition
│           ├── Navbar.tsx          # Sticky navigation bar with theme toggle
│           ├── ReleaseChangelogSection.tsx # v0.1.0 changelog & download CTA
│           ├── RequirementsSection.tsx # System requirements checklist
│           ├── SecurityPrivacySection.tsx # Security principles & SmartScreen info
│           ├── useTheme.ts         # Dual-theme hook (system, light, dark)
│           └── WorkflowSection.tsx # Numbered workflow rail
├── my-learning/                    # Personal educational walkthroughs
├── scripts/                        # Development, packaging & database scripts
│   ├── build-desktop.mjs           # Bundles desktop TypeScript to main.cjs/preload.cjs
│   ├── clean.mjs                   # Workspace cache & build artifact cleanup
│   ├── db-tool.mjs                 # SQLite database query & diagnostic tool
│   ├── dev.mjs                     # Concurrently starts Vite & Electron
│   ├── package-prepare.mjs         # Stages portable Python, dependencies & binaries
│   ├── run.ps1                     # Hardened Windows launcher with port checks
│   └── verify-env.mjs              # System runtime pre-flight verification
├── package.json                    # Root workspace orchestrator
├── README.md                       # Repository overview & quick start guide
└── AGENTS.md                       # Universal repository AI instructions
```

---

## 5. Important Modules & Responsibilities

| Module / Component | Path | Language | Primary Responsibilities |
| :--- | :--- | :--- | :--- |
| **Electron Main** | `desktop/main/index.ts` | TypeScript | Window management, security headers (CSP), IPC handler registration, single-instance lock, custom `media-loader://` streaming protocol, native folder/file dialogs. |
| **Python Bridge** | `desktop/main/python-bridge.ts` | TypeScript | Resolves Python executable, spawns `xakumedia.server` child process, correlates JSON-RPC requests/responses by ID, dispatches asynchronous notifications. |
| **Preload Bridge** | `desktop/preload/index.ts` | TypeScript | Implements context-isolated `window.api` with 38+ typed asynchronous methods, progress listeners, and event subscribers without exposing raw Node.js APIs. |
| **Main UI View** | `frontend/src/App.tsx` | TypeScript (React) | Coordinates all desktop application state, tab navigation (Scan, Queue, Library, Saved, History, Settings), format chips, modals, lightbox, player, batch actions. |
| **Settings View** | `frontend/src/components/SettingsView.tsx` | TypeScript (React) | Application preferences, directory selector, concurrency slider, speed limiter presets, cookie profile table, browser cookie extractor, custom domain headers. |
| **Saved Sources View** | `frontend/src/components/SavedSourcesView.tsx` | TypeScript (React) | Bookmark management, tag filtering, Rescan All orchestration, source card grid, and Incremental Rescan diff review modal. |
| **Dual View Router** | `frontend/src/main.tsx` | TypeScript (React) | Evaluates environment and query parameters: mounts `<App />` inside Electron desktop shell; mounts `<LandingPage />` in standard web browsers. |
| **Landing Page** | `frontend/src/landing/` | TypeScript (React) | Public marketing, feature overview, SmartScreen security notice, release changelog, installer download triggers, and light/dark theme system. |
| **JSON-RPC Server** | `backend/src/xakumedia/server/` | Python | Stdio JSON-RPC 2.0 loop (`loop.py`), message framing (`protocol.py`), and 40+ method handlers (`dispatcher.py`) mapping RPC calls to domain logic. |
| **Download Manager** | `backend/src/xakumedia/downloader/manager.py` | Python | Thread pool execution (`ThreadPoolExecutor`), pending FIFO queue, worker slot scheduling (1–10), batch persistence, cancellation, pause, and resume. |
| **Streaming Downloader** | `backend/src/xakumedia/downloader/stream.py` | Python | 64 KB chunked HTTP streaming via HTTPX, HTTP 206 Range resumption, `.part` staging, atomic rename, and telemetry emissions. |
| **Bandwidth Throttler** | `backend/src/xakumedia/downloader/throttler.py` | Python | Thread-safe token bucket rate limiter providing sub-50ms sleep slicing across all concurrent transfer threads. |
| **Task Recovery** | `backend/src/xakumedia/downloader/recovery.py` | Python | Startup audit service comparing SQLite task states against on-disk `.part` files, updating byte counts, cleaning corrupt merge files, and resuming tasks. |
| **Media Repository** | `backend/src/xakumedia/db/repository.py` | Python | High-performance SQLite CRUD layer, batch `executemany` mutations, scan history tracking, library queries, and preference persistence. |
| **Database Schema** | `backend/src/xakumedia/db/schema.py` | Python | DDL definitions and automated migration runner for schema versions 1 through 4 with performance indexes. |
| **Video Extractor** | `backend/src/xakumedia/extractors/video.py` | Python | `yt-dlp` integration for video metadata extraction, stream format normalization, codec mapping, and domain error translation. |
| **Gallery Extractor** | `backend/src/xakumedia/extractors/gallery.py` | Python | `gallery-dl` integration for multi-image album and collection extraction via non-polluting `DataJob`. |
| **Direct Scanner** | `backend/src/xakumedia/scanners/direct.py` | Python | Network probing for direct media links via HTTP `HEAD` and Range `GET`, MIME type resolution, and Content-Disposition parsing. |
| **FFmpeg Processor** | `backend/src/xakumedia/processor/ffmpeg.py` | Python | Dynamic binary discovery, media inspection (`ffprobe`), non-re-encoding stream multiplexing (`-c copy`), and container conversion. |
| **Thumbnail Engine** | `backend/src/xakumedia/processor/thumbnail.py` | Python | Generates lightweight WebP thumbnails from local images (Pillow) and videos (FFmpeg frame seek) cached deterministically by item ID. |
| **Auth & Cookies** | `backend/src/xakumedia/auth/` | Python | Netscape cookie parser, DPAPI browser cookie extractor, and subdomain-hierarchical header builder. |
| **Rescan Engine** | `backend/src/xakumedia/sources/rescan.py` | Python | Differential discovery engine comparing discovered URLs against SQLite to isolate new delta items. |
| **Security Utilities** | `backend/src/xakumedia/utils/security.py` | Python | Hardened SSRF defense parser checking non-global IP literals, loopbacks, mapped IPv6, and forbidden internal hostnames. |
| **Naming Utilities** | `backend/src/xakumedia/utils/naming.py` | Python | Sequential filename formatter (`{user}_{vdo|img}_{001}.{ext}`) and on-disk sequence scanner. |
| **Path Utilities** | `backend/src/xakumedia/utils/paths.py` | Python | Path traversal prevention, NTFS Alternate Data Stream (`:`) rejection, DOS reserved device name rejection, and UNC path blocking. |

