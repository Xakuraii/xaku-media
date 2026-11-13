# XakuMedia — Product Specification Assessment

**Date:** November 12, 2026
**Scope:** Read-only assessment of the existing repository against the bulk-first product specification.
**Status:** Assessment preserved as the pre-implementation baseline. Milestone 29 implemented the provider registry, posts/albums, schema V5, cancellable scan jobs, and the bulk scan UI; see `docs/CURRENT_STATE.md` Milestone 29 for the implemented scope and remaining live-verification limits. The verdict below describes the repository **before** that work.

> **Implementation update (November 13, 2026):** Acceptance items A, B, C, D, and F now have working implementations for the verified yt-dlp source path, and gallery-dl-backed sources use the same job model subject to extractor coverage. Item E remains partial (no separate download-history/filesystem reconciliation table). The original blockers and phased plan are retained below for context.

---

## 1. Method and Evidence

Inspected: repository tree, `AGENTS.md`, `README.md`, `docs/*`, root `package.json`, `frontend/package.json`, `backend/pyproject.toml`, `docs/DEVELOPMENT_ROADMAP.md`, SQLite schema/migrations, backend models, extractors, scanners, saved-source rescan engine, JSON-RPC dispatcher, download manager, Electron main/preload, and the React UI.

Executed:

- `gallery_dl.extractor.find(...)` against representative profile URL shapes (offline registry check, no network extraction).
- A targeted pytest subset (`test_models.py`, `test_naming.py`): **8 passed in 2.38s**.
- A full pytest run was started but had produced no output within the assessment window (process still active); the "140 tests passing" figure in the project docs was **not** re-verified in this session.

Not performed: live profile extraction against authenticated platforms (would require user cookies, consent, and rate-limit-aware testing). No claim is made that any platform's profile bulk discovery currently works end to end.

---

## 2. Verdict on the Central Question

> Can the current application accept one supported user profile URL, discover multiple posts across pagination, extract all supported image and video attachments, display them grouped by post or album, and download the selected items in bulk?

**No.** It cannot satisfy this workflow end to end.

| Acceptance test | Result | Reason |
| :--- | :--- | :--- |
| **A** One profile URL → multi-post discovery with pagination | **Fails** | Scanning is one synchronous request. yt-dlp is configured with `noplaylist=True` and keeps only the first entry; gallery-dl is run to completion in memory and flattened. No pagination state, no progress, no cancellation. |
| **B** Mixed media + albums grouped by post | **Fails** | There is no post/album domain model, no post-media relationship, and no grouping in the database or UI. Everything is a flat `MediaItem` list. |
| **C** Selection (all/videos/images/album/individual) | **Partial** | Whole-result select/invert and per-item selection exist for a single flat gallery result; there is no album selection, no "videos only / images only" bulk selection, and it is per-scan rather than library-wide. |
| **D** Reliable batch download | **Partial** | Streaming, concurrency, pause/resume, retry-on-error and `.part` staging exist; the batch UI always sends `available_formats[0]` (`App.tsx:578-590`), so saved quality preferences and user-chosen variants are not applied. |
| **E** Persistence across restart | **Partial** | Tasks, scans, sources and preferences persist; there is no download-history table separate from the live queue, no library inventory of downloaded files, and no filesystem reconciliation. |
| **F** Honest provider capability reporting | **Fails** | There is no provider registry or capability model. The UI implies profile-style support through generic "gallery" handling while the engine cannot honor the spec's profile-level guarantees. |

Partial capability worth acknowledging: `gallery-dl` recognizes profile-shaped URLs for several sites (verified via its extractor registry: TikTok user, Instagram user, X user, Facebook page, Pinterest board, Reddit subreddit; YouTube channels/playlists are **not** handled by gallery-dl). The current wrapper then materializes the whole result set through one blocking `DataJob.run()` call and discards per-post identity. That is not profile-level discovery as specified, and most of those sites require cookies the current pipeline only partially wires.

---

## 3. Feature-by-Feature Assessment

Legend: **Implemented** = works as specified and is wired end to end · **Partial** = some behavior exists · **Missing** = not present · **Unwired** = code/setting exists but no production path consumes it.

### 3.1 Source detection and classification

| Requirement | Status | Evidence / gap |
| :--- | :--- | :--- |
| URL validation, scheme checks, SSRF guard | **Implemented** | `utils/security.py` with DNS checks, private/CGNAT/link-local/metadata blocks, IP literal parsing. |
| Recognise profiles, posts, galleries, playlists, direct media | **Partial** | Classification is a side effect of whichever extractor happened to succeed (`scanners/direct.py`, `extractors/gallery.py`, `extractors/video.py`). There is no canonical source-type classifier and no provider capability object. |
| Detect platform / account / collection identity before scanning | **Partial** | `ClassifiedUrl` carries `platform`, `domain`, `author_hint`, `title_hint`, but these come from extractor output, not from URL parsing, and are unavailable until a scan has already run. |
| Explain unsupported or auth-required sources | **Partial** | Domain exceptions exist (`UnsupportedSourceError`, `PrivateMediaError`, `RateLimitError`, `DRMProtectedError`); mapping is per extractor and message text is generic. |
| Multiple URLs, paste action, drag-and-drop | **Missing** | Single `<input>` + submit in `frontend/src/App.tsx:1188-1215`. No paste/drag-drop/multi-URL. |

### 3.2 Bulk discovery and pagination

| Requirement | Status | Evidence / gap |
| :--- | :--- | :--- |
| Profile-level discovery across posts | **Missing** | `extract_video_info` sets `noplaylist: True` and takes `entries[0]` (`extractors/video.py:127,174-178`). Profile/playlist URLs collapse to one item. `gallery-dl` profile URLs are flattened, not modeled as posts. |
| Reusable pagination architecture (cursor/page/offset/token) | **Missing** | No pagination abstraction anywhere; SQLite has no cursor/page/continuation columns. |
| Progressive results, scan status, cancellation | **Missing** | `classify_url` is a single synchronous JSON-RPC request (`server/dispatcher.py:108-180`); Electron uses a 120 s timeout. No scan job IDs, no progress notifications, no cancel RPC. |
| Configurable scan limits | **Missing** | No post/media limits, no "all accessible media" option, no truncation reporting. |
| Provider interface and registry | **Missing** | Three procedural fallbacks duplicated in `server/dispatcher.py` and `sources/rescan.py`; no capability declaration, no per-provider module, no registration. |
| Failure isolation and partial results | **Partial** | Exceptions map to domain errors, but a failure aborts the whole scan and no partial result survives. |
| Resume/retry interrupted scans | **Missing** | Saved-source rescan restarts from scratch. |

### 3.3 Media and post data model

| Requirement | Status | Evidence / gap |
| :--- | :--- | :--- |
| Source → post → attachment hierarchy | **Missing** | `MediaItem` (`models/media.py:48-88`) is flat; `metadata_extra` carries only `gallery_index`, `gallery_total`, `album_title` for gallery items. |
| Stable media identity; post URL; creator; MIME; extension; thumb; variants | **Partial** | Fields like width/height/duration/filesize/author/thumbnail/formats exist. But `id` is a fresh UUID per extraction, there is no `provider_item_id`, no post URL/ID, no MIME/ext column, and no variant table. |
| Multiple attachments per post | **Partial** | gallery-dl returns a flat list of URLs, so multiple files do appear; the post they belong to is lost. |
| Duplicate detection | **Missing (effectively)** | `save_scan_result` inserts new UUID rows on every scan (`db/repository.py:60-141`); no unique key on `original_url`/provider identity. The only URL comparison is in-memory during saved-source rescan. |

### 3.4 UI and workflow

| Requirement | Status | Evidence / gap |
| :--- | :--- | :--- |
| Sidebar navigation incl. **Overview** | **Partial** | Sidebar exists with Scan, Library, Downloads, Saved Sources, Scan History, Settings (`App.tsx:973-993`). **Overview/dashboard is absent.** |
| Scan page: one profile → progressive results, filters, album view | **Partial** | Single-result scan card; flat 48-item grid (`App.tsx:1429-1441`); no post/album view, no separate media-row view, no images/videos/albums filters. |
| Horizontal row layout for main media lists | **Partial** | Downloads and library use rows; scan gallery uses a card grid. |
| Selection controls (all/videos/images/albums/individual) | **Partial** | All/invert/individual for a flat result set; no media-type or album selection. |
| Video/image preview without full download | **Partial** | Local lightbox/player via `media-loader://` is solid. Remote item preview relies on remote thumbnails and direct/remote URLs; no cached remote preview pipeline; no resolution/format picker per item. |
| Dark/light theming, tokens | **Implemented** | Semantic tokens and persisted theme (Milestone 28). |
| Frontend maintainability | **Poor** | `frontend/src/App.tsx` is **174 KB / ~3,100 lines**, containing scan, library, queue, modals and previews. Manual pagination instead of virtualization. |

### 3.5 Download engine and file organization

| Requirement | Status | Evidence / gap |
| :--- | :--- | :--- |
| Persistent queue, concurrency, pause/resume/cancel | **Implemented** | `downloader/manager.py`, `stream.py`, `recovery.py`; states in `models/queue.py`. |
| HTTP Range resume, `.part` staging, atomic rename | **Implemented** | `downloader/stream.py` (range header, 206 handling, atomic finalize). |
| Retry/backoff | **Partial** | Retry count persisted; no explicit bounded backoff scheduler for transient failures. |
| No duplicate active tasks | **Missing** | No enqueue de-duplication by media/item. |
| Batch quality/format controls | **Unwired** | `start_batch_download` accepts a per-item `selected_format`, but the UI always sends `available_formats[0]` (`App.tsx:578-590`). `default_video_resolution`, `default_video_container`, `default_image_format` are persisted and applied to config but **never read by the downloader** (grep confirms only config/repository references). `MediaItem.find_best_format` is dead code. |
| Image format/compression/resize | **Missing** | No Pillow conversion path; only thumbnail generation (`processor/thumbnail.py`). |
| Extension preservation | **Partial** | Container/first-format/URL suffix is used, but falls back to `jpg`/`mp4` when unknown (`manager.py:113,211`). |
| Safe naming, collision avoidance, DB reservation | **Partial** | Sequential naming and disk scan exist; no DB-level reservation or unique constraint, so concurrent restarts can race. |
| `ChosenFolder/{videos,images}` structure | **Implemented** | `AppConfig.video_download_dir` / `image_download_dir`. |

### 3.6 Library, saved sources, history, recovery

| Requirement | Status | Evidence / gap |
| :--- | :--- | :--- |
| Library of downloaded files with metadata, search, filter, sort | **Partial** | "Library" is a bookmark table (`media_items.is_saved`), not an inventory of downloaded files; no file path column in `media_items`; no missing-file detection or reconcile. |
| Open file / reveal folder / copy path / favorite / delete with confirmation | **Partial** | Open/reveal and delete exist; favorites/copy path are partial or absent; removal semantics are record-scoped. |
| Saved sources, last scan, rescan, differential discovery | **Partial** | `saved_sources` + rescan engine exist, but rescan re-runs the same non-paginated scan and relies on URL string comparison. No stored cursor/watermark. |
| Scan history | **Partial** | `scan_history` records raw/normalized URL, category, platform, counts. No post/media type breakdown, pagination info, or scan status. |
| Download history | **Partial** | Only the live `download_tasks` table. `clear_completed_downloads` deletes history. No archive table. |
| Restart recovery | **Partial** | Recovery audits tasks and `.part` files; does not reconcile library/inventory or prevent duplicate re-download. |

### 3.7 Settings, security, performance, packaging, tests

| Requirement | Status | Evidence / gap |
| :--- | :--- | :--- |
| Settings persistence | **Implemented** | `app_preferences` + `default_config` synchronization. |
| Settings that actually affect behavior | **Partial** | Theme, concurrency, speed, timeouts, destination apply. Video/image quality do not. No scan limits, cache maintenance, diagnostics/reset of specific scopes. |
| Electron isolation (context isolation, no node integration, restricted preload) | **Implemented** | `desktop/main/index.ts`, `desktop/preload/index.ts`; per-method IPC rather than a generic bridge. |
| IPC schema validation | **Partial** | Type checks on primitives per handler; no shared schema/validation framework, no size/range validation of nested media payloads. |
| SSRF, including redirects | **Gap** | Only the initial URL is validated; `httpx` runs with `follow_redirects=True` (`scanners/direct.py:89`, `downloader/stream.py:147`) and redirect destinations are not re-validated. |
| Path safety | **Implemented** | `utils/paths.py` + `download_stream` root validation, ADS/UNC/reserved-name handling. |
| Performance for large collections | **Partial** | Streaming I/O and batching are good; UI uses manual pagination; gallery extraction materializes everything in memory; no virtualized list. |
| Packaging | **Implemented (per docs)** | NSIS + portable builds with bundled Python/FFmpeg; not re-verified in this session. |
| Unit/integration tests | **Partial** | Backend tests are mostly mocks (e.g. `DataJob` and `scan_source_url` are patched). No frontend unit tests, no provider contract fixtures, no HTTP cassette/mock server, no E2E workflow test. |
| Smoke test | **Partial** | `--smoke-test` verifies window paint, Python handshake, SSRF rejection and read-only RPCs; it never exercises a scan → select → download workflow. |

---

## 4. Architectural Problems Blocking the Central Workflow

1. **Synchronous scan RPC is the root blocker.**
   Discovery is a blocking request with a 120 s timeout. Profile scans are long-running, paginated, cancellable jobs. Without a scan-job/event model (job id, progress events, partial results, cancel, limits), progressive discovery and long pagination are impossible.

2. **No provider abstraction.**
   Provider selection is a hardcoded three-step fallback duplicated in `dispatcher.classify_url_handler` and `sources/rescan.scan_source_url`. There is no capability contract, no URL→provider resolution, and no honest per-platform support matrix. Adding a real provider today would require editing the dispatcher, the bridge, the preload, the UI, and rescan.

3. **yt-dlp is intentionally single-item.**
   `noplaylist=True` plus `entries[0]` discards every channel/playlist item. Channel discovery must be a first-class provider mode (`extract_flat` enumeration + per-entry hydration), not a flag tweak.

4. **gallery-dl is used as a bulk downloader of URLs, not a discovery engine.**
   `DataJob.run()` pulls the entire result set before returning and only exposes flat URL lists. To support progressive, limited, cancellable profile scans, the wrapper must consume the extractor's lazy `items()` iterator and preserve grouping metadata (post id/group/username), not wait for a fully materialized job.

5. **The data model cannot represent the product.**
   There is no `source`, `scan`, `post`, `media_variant`, `downloaded_file`, or pagination-state model. `media_items.id` is random per extraction, so the same asset is duplicated on every scan and cannot be reconciled with files on disk.

6. **Download quality settings are decorative.**
   Persisted resolution/container/format preferences never reach the download path; the bulk UI always picks the first available format. This is a spec violation and an honesty issue with the current UI.

7. **UI state is single-result and flat.**
   `scanResult` holds one flat list; there is no album grouping, filter set, or selection model. The 174 KB `App.tsx` makes the required scan-results redesign risky without a structural split.

---

## 5. Additional Correctness and Honesty Findings

- **Redirects bypass the SSRF guard** (`follow_redirects=True` after only validating the initial URL). This also affects final file downloads, not just scanning.
- **Stale UI claim:** the scan page still renders "Supported in M8: Direct Files / Video Platforms / Image Galleries" (`App.tsx:1270`), which does not reflect current capabilities.
- **Settings that do nothing:** Video resolution/container and image format selectors persist but are not applied. This should be fixed or clearly marked as not yet active.
- **Duplicate rows:** every rescan inserts a new `media_items` row per asset (new UUID); library and history grow without bound.
- **History loss:** clearing completed downloads erases the only download history.
- **No scan limits or abort:** one hostile or enormous profile can occupy the engine for minutes with no user control.
- **Docs drift:** `docs/DEVELOPMENT_ROADMAP.md` lists Milestone 9 as "Scanning Service & Pagination" and 15/16 as quality controls, but `docs/CURRENT_STATE.md` reports different milestone content. Profile bulk discovery and scan coordination were never delivered.

---

## 6. Existing Strengths to Preserve

- Secure 3-tier separation: context isolation, no renderer Node access, per-method preload API, stdio JSON-RPC (no local HTTP server).
- Robust streaming downloader: 64 KB chunks, `.part` staging, Range resume, atomic rename, bounded concurrency, token-bucket throttling.
- Crash recovery for interrupted tasks and partial files.
- Strong Windows path safety (ADS, UNC, reserved names, traversal) and initial-URL SSRF defense.
- Working SQLite migration runner with WAL and batch inserts.
- Real FFmpeg integration (merge without re-encoding) and local thumbnail cache/streaming protocol.
- Packaging pipeline that bundles Python + FFmpeg.

These subsystems should be extended, not rewritten.

---

## 7. Prioritized Implementation Plan

The ordering follows the spec's milestone logic but groups work into verifiable releases. Each phase must leave the app runnable and the existing flows intact.

### Phase 1 — Scan jobs and provider foundation (P0)

- Introduce `Provider` capability model: URL match, source type, profile support, post support, media kinds, auth requirement, pagination style, limitations.
- Provider registry with `direct`, `ytdlp`, `gallerydl` adapters; remove duplicated fallback chains from dispatcher/rescan.
- Introduce `ScanJob` runner: job id, background execution, progressive batched events (`scan:started`, `scan:posts`, `scan:media`, `scan:progress`, `scan:warning`, `scan:completed`, `scan:failed`), cancellation, limits, partial-result preservation.
- New RPCs: `start_scan`, `cancel_scan`, `get_scan_status`; keep `classify_url` working for compatibility.
- **Acceptance:** one profile URL yields progressive results without blocking the renderer; cancel works mid-pagination; existing direct/video/gallery flows still work.

### Phase 2 — Data model migration (P0, can start alongside Phase 1)

- Migration V5: `sources`, `source_scans`, `scan_pages`/pagination state, `posts`, `media_assets`, `media_post_links` (or post_id FK), `media_variants`, `downloaded_files`, `download_history`.
- Stable identity: `(provider, provider_media_id)` unique; fallback fingerprint from canonical post URL + attachment index + media URL; `UNIQUE` constraints to make dedupe structural.
- Keep a compatibility read path for existing `media_items`/`scan_history` data.
- **Acceptance:** repeated scans of the same source produce zero duplicate assets; posts group attachments correctly.

### Phase 3 — Verified profile bulk discovery (P0, the critical milestone)

- **First verified provider: yt-dlp channel/playlist** (public content, no auth). Enumerate flat entries, hydrate entries in batches, map each video to a post with one video attachment plus thumbnail variant; respect limits and cancellation.
- **Second: gallery-dl profile provider**, consuming the lazy `items()` iterator, preserving per-post grouping metadata, mapping images/videos/slideshows; capability report must state auth requirements per site.
- Implement pagination adapter per provider (cursor/token/page/next URL), loop protection, retry/backoff, expired-cursor handling.
- **Acceptance:** Acceptance Test A passes for at least the yt-dlp provider end to end, with an honest capability matrix for gallery-dl sites; single-post and direct URLs still work.

### Phase 4 — Scan UI and album grouping (P1)

- Split `App.tsx` into feature modules; add a virtualized list primitive.
- Scan workspace: multi-URL, paste, drag-and-drop, detection preview with capabilities, limits, progress, cancel, warnings, discovered counts.
- Results: media view vs post/album view, expand/collapse, filters (all/video/image/album/post), per-post selection state, bulk selection (all/videos/images/albums/invert/clear).
- Add Overview dashboard backed by real aggregates.
- **Acceptance:** Acceptance Tests B and C pass against a real multi-post fixture.

### Phase 5 — Download correctness (P1)

- Wire video resolution/container/codec preferences into variant selection; per-item override; batch override; explain unavailable quality.
- Image output pipeline (original default, format/quality/resize via Pillow, metadata policy).
- Make naming DB-reserved and race-safe; preserve extensions; separate image/video numbering.
- Task de-duplication and retry policy; download history written on finalization.
- **Acceptance:** Acceptance Test D passes: mixed batch, visible progress, failure isolation, no overwrites, correct folders/names.

### Phase 6 — Library, saved sources, recovery (P1/P2)

- Library backed by `downloaded_files` with path, size, hash/validation, favorite, missing-file detection and reconcile.
- Saved sources store provider identity + cursor; rescan uses the new scan engine and reports new vs known correctly.
- Split scan history and download history; recovery reconciles DB with disk.
- **Acceptance:** Acceptance Test E passes after restart.

### Phase 7 — Security, performance, QA, packaging (P2)

- Redirect re-validation for every hop (manual follow with SSRF checks), IPC payload schemas, CSP review for remote previews, cookie handling review.
- Provider contract tests, mock HTTP server/fixtures, pagination/cancel/limit tests, frontend component tests, Playwright CI smoke of the full workflow.
- Benchmarks for large profiles and 1k+ media batches; virtualized rendering verification.
- Capability matrix in docs; release notes and checksums; packaged-app E2E.
- **Acceptance:** Acceptance Test F documented honestly; full regression suite green in this environment; installer/portable tested.

---

## 8. Test Strategy Gaps to Close

1. No test currently proves multi-page discovery; `test_sources.py` patches `scan_source_url`, and `test_gallery_extractor.py` patches `DataJob`.
2. Add provider contract tests: each provider must pass URL recognition, classification, pagination, cancellation, and limit tests against recorded fixtures.
3. Add a local fixture HTTP server (or `httpx.MockTransport` + extractor fakes) for deterministic pagination and media attachment tests.
4. Add frontend tests (Vitest + Testing Library) for selection/album state, plus one Playwright workflow.
5. Add packaged-app workflow verification, not just IPC read checks.
6. Add DB migration tests from V4 data to V5, including idempotent rescan and dedupe.

---

## 9. Decisions Required Before Implementation

1. **First verified profile provider.** Recommendation: YouTube channel via yt-dlp (public, no authentication, deterministic pagination) to prove the architecture; then gallery-dl profiles (TikTok/Instagram/X/Facebook/Pinterest/Reddit) with cookie-based auth where the user is authorized.
2. **Scope of authentication.** Do we implement the spec's "optional browser-session authentication later" now, or restrict the first verified provider to public content?
3. **UI restructuring.** Approve splitting `App.tsx` into `features/scan`, `features/library`, `features/downloads`, `features/settings` with shared primitives; this is required for the album/selection redesign but is a large diff.
4. **Migration strategy.** Approve schema V5 as an additive migration with a compatibility read path; existing local databases must not lose data.
5. **Roadmap reconciliation.** The existing roadmap/current-state documents claim completion of milestones that the code does not implement (scan coordinator/pagination, quality controls). I recommend correcting those documents rather than preserving inaccurate claims.

---

## 10. Explicit Approval Request

I have not modified product code. On approval I will start with **Phase 1 (scan jobs + provider foundation)** and **Phase 2 (schema V5)** in small, verified commits, then deliver the first real profile-level provider as the gate for all further UI work.

Please confirm:

- the first verified provider (recommended: yt-dlp YouTube channel),
- whether authenticated gallery-dl profiles are in scope for the first release,
- approval to split `App.tsx` and add schema V5.
