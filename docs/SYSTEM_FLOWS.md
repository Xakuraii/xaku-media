# XakuMedia — End-to-End System Flows

This document details the critical execution paths and data flows across the three tiers of XakuMedia: the **React Frontend (Renderer)**, the **Electron Main Process**, the **Python 3.12 Engine**, the **Local SQLite Database**, the **Local Filesystem**, and **Remote Media Services**.

---

## 1. Flow 1: URL Scan to Media Discovery & Presentation

Traces the user journey when submitting a URL into the Scan view.

```mermaid
sequenceDiagram
    autonumber
    actor User as User
    participant React as React UI (App.tsx)
    participant Preload as Preload (window.api)
    participant Main as Electron Main
    participant Bridge as PythonBridge
    participant Server as Python Server (dispatcher.py)
    participant Scanner as DirectScanner / Extractors
    participant DB as MediaRepository / SQLite

    User->>React: Types/pastes URL and clicks "Scan URL"
    React->>React: Set isScanning=true, clear previous errors
    React->>Preload: classifyUrl(url)
    Preload->>Main: ipcRenderer.invoke("python:classifyUrl", url)
    Main->>Bridge: sendRequest("classify_url", { url })
    Bridge->>Server: Stdio JSON-RPC: {"method": "classify_url", "params": {"url": "..."}}

    %% Probe Stage
    Server->>Scanner: 1. classify_direct_url(url)
    alt Direct Media Link (HEAD / Range GET)
        Scanner-->>Server: ClassifiedUrl (category=DIRECT_VIDEO|IMAGE) + MediaItem
    else Not a direct link
        Server->>Scanner: 2. gallery_dl.extractor.find(url)
        alt Gallery / Collection recognized
            Scanner-->>Server: extract_gallery_info(url) -> MediaItem[]
        else Single video / platform stream
            Server->>Scanner: 3. extract_video_info(url) (yt-dlp)
            Scanner-->>Server: ClassifiedUrl + MediaItem (with MediaFormatInfo[])
        end
    end

    %% Database Auto-Persist
    Server->>DB: save_scan_result(classified, media_items)
    DB-->>Server: scan_id (UUID)
    Server-->>Bridge: Stdio Response: {"result": {scan_id, classified_url, media_items}}
    Bridge-->>Main: Resolve Promise
    Main-->>Preload: Return payload
    Preload-->>React: ClassifyUrlResult

    React->>React: Update state: scanResult, selectedFormat, isScanning=false
    React-->>User: Renders format chips, preview card / multi-item gallery grid
```

### Key Execution Highlights:
1. **SSRF Pre-Validation (`utils/security.py`):** Before making any network request, `validate_url_security` ensures the URL does not target loopbacks (`127.0.0.1`), private RFC 1918 subnets (`10.0.0.0/8`, `192.168.0.0/16`), mapped IPv6 addresses, or cloud metadata endpoints.
2. **Adaptive Probing:** If an initial HTTP `HEAD` request returns a `403` or `405` (frequent on CDNs), `probe_direct_url` automatically falls back to an HTTP `Range: bytes=0-1024` `GET` request.
3. **Automatic Persistence:** Discovered items are immediately committed to `scan_history` and `media_items` in SQLite, ensuring scan history is preserved even if the user does not immediately download them.

---

## 2. Flow 2: Download Initiation & Worker Slot Scheduling

Traces single-item or selective bulk gallery downloads from user click to thread allocation.

```mermaid
sequenceDiagram
    autonumber
    actor User as User
    participant React as React UI (App.tsx)
    participant Preload as Preload (window.api)
    participant Main as Electron Main
    participant Bridge as PythonBridge
    participant Server as Python Server (dispatcher.py)
    participant Mgr as DownloadManager (manager.py)
    participant Naming as Naming Engine (naming.py)
    participant DB as SQLite Database
    participant Pool as ThreadPoolExecutor

    User->>React: Clicks "Download" (or "Bulk Download Selected")
    React->>Preload: startDownload(mediaItem, selectedFormat, destPath)
    Preload->>Main: ipcRenderer.invoke("python:startDownload", ...)
    Main->>Bridge: sendRequest("start_download", ...)
    Bridge->>Server: Stdio JSON-RPC: {"method": "start_download", "params": {...}}
    
    Server->>Mgr: start_download(media_item, selected_format, dest)
    
    %% Sequential Naming & Path Allocation
    Mgr->>Naming: get_next_sequence_number(target_dir, username, media_type)
    Naming->>Naming: Scan existing files on disk for highest index
    Naming-->>Mgr: next_sequence (e.g. 1)
    Mgr->>Naming: format_sequential_filename("artist", "vdo", 1, "mp4")
    Naming-->>Mgr: "artist_vdo_001.mp4"
    
    %% Task Creation & Enqueue
    Mgr->>Mgr: Create DownloadTask (status=QUEUED, dest="...001.mp4", temp="...001.mp4.part")
    Mgr->>DB: save_download_task(task)
    Mgr->>Mgr: _enqueue(task, url) -> append to _pending_queue
    
    %% Scheduling Check
    Mgr->>Mgr: _schedule_next()
    alt Active Workers < max_concurrent (e.g. len(_active_tasks) < 3)
        Mgr->>Pool: submit(_run_task, task, url, cancel_event, pause_event)
        Mgr->>Mgr: Move task from _pending_queue to _active_tasks
    else Concurrency Limit Reached
        Mgr->>Mgr: Task remains in _pending_queue waiting for slot
    end

    Mgr-->>Server: DownloadTask record
    Server-->>Bridge: Stdio Response: {"result": {"task": {...}}}
    Bridge-->>Main: Resolve Promise
    Main-->>Preload: Return task
    Preload-->>React: Update queue state & switch to "Downloads" tab
```

---

## 3. Flow 3: Chunked Stream Download, Range Resumption & Live Telemetry

Traces active streaming over the network, bandwidth throttling, `.part` staging, and real-time UI updates.

```mermaid
sequenceDiagram
    autonumber
    participant Worker as Worker Thread (_run_task)
    participant Streamer as download_stream (stream.py)
    participant Throttler as BandwidthThrottler (throttler.py)
    participant Disk as Local Filesystem (.part)
    participant EventLoop as Python Event Loop (loop.py)
    participant Bridge as Electron PythonBridge
    participant React as React UI (App.tsx)
    participant Remote as Remote HTTP Server

    Worker->>Streamer: download_stream(url, dest_path, task_id, progress_cb, ...)
    
    %% Staging & Range Check
    Streamer->>Disk: Check if temp_path (.part) exists
    alt .part file exists on disk (existing_bytes > 0)
        Streamer->>Streamer: Add header "Range: bytes={existing_bytes}-"
    end

    Streamer->>Remote: HTTP GET with Range & Cookies
    Remote-->>Streamer: HTTP 206 Partial Content (or 200 OK)

    %% Chunk Loop
    loop For each 64KB chunk received
        Streamer->>Throttler: consume(64KB)
        alt Bandwidth Limit Set
            Throttler->>Throttler: Check token balance and sleep if needed (<=50ms slices)
        end
        Streamer->>Disk: Append bytes to temp_path (.part)
        
        %% Throttled Telemetry Broadcast (every 150ms)
        alt Now - last_emit >= 0.15s
            Streamer->>Worker: progress_callback(ProgressUpdate)
            Worker->>EventLoop: send_notification("download:progress", update)
            EventLoop->>Bridge: Stdio Line: {"method": "download:progress", "params": {...}}
            Bridge->>React: webContents.send("download:progress", update)
            React->>React: Update progress bar, speed KB/s, ETA in state
        end
    end

    %% Atomic Rename & Completion
    Streamer->>Disk: Atomic rename: temp_path.replace(final_path)
    Streamer-->>Worker: Return final_path
    Worker->>Worker: task.mark_completed(final_path)
    Worker->>EventLoop: send_notification("download:completed", task)
    EventLoop->>Bridge: Stdio Line: {"method": "download:completed", ...}
    Bridge->>React: webContents.send("download:completed", task)
    React->>React: Switch task badge to Completed, play sound / notification
```

---

## 4. Flow 4: Dual-Stream Video/Audio Download & FFmpeg Multiplexing

Traces the execution path when a video format requires separate video and audio stream merging.

```mermaid
sequenceDiagram
    autonumber
    participant Worker as Worker Thread (_run_task)
    participant Streamer as Stream Downloader
    participant FFmpeg as FFmpeg Processor (ffmpeg.py)
    participant Disk as Local Filesystem
    participant EventLoop as Python Event Loop
    participant React as React UI

    Note over Worker: task.selected_format.requires_merge == true

    %% Step 1: Download Video Track
    Worker->>Disk: Set video_part = "{name}.video.part"
    Worker->>Streamer: download_stream(video_url, video_part)
    Streamer-->>Worker: Video stream complete (80% overall progress)

    %% Step 2: Download Audio Track
    Worker->>Disk: Set audio_part = "{name}.audio.part"
    Worker->>Streamer: download_stream(audio_url, audio_part)
    Streamer-->>Worker: Audio stream complete (95% overall progress)

    %% Step 3: Transition to Merging
    Worker->>Worker: task.status = TaskStatus.MERGING (96%)
    Worker->>EventLoop: send_notification("download:progress", {status: "merging"})
    EventLoop->>React: UI shows purple "Merging streams with FFmpeg..." badge

    %% Step 4: FFmpeg Multiplexing
    Worker->>FFmpeg: merge_video_audio(video_part, audio_part, temp_merged, container)
    FFmpeg->>FFmpeg: Execute: ffmpeg -y -i video.part -i audio.part -c:v copy -c:a copy temp.mp4.part
    alt Incompatible Audio Codec in MP4 (e.g. Opus in MP4)
        FFmpeg->>FFmpeg: Fallback: ffmpeg ... -c:v copy -c:a aac -b:a 192k temp.mp4.part
    end
    FFmpeg-->>Worker: Success (temp.mp4.part generated)

    %% Step 5: Cleanup & Commit
    Worker->>Disk: Delete video_part and audio_part intermediate files
    Worker->>Disk: Atomic rename: temp_merged.replace(destination_path)
    Worker->>Worker: task.mark_completed(destination_path)
    Worker->>EventLoop: send_notification("download:completed", task)
    EventLoop->>React: UI marks task Completed (100%)
```

---

## 5. Flow 5: Task Queue Crash Recovery & Auto-Resumption

Traces how XakuMedia recovers from unexpected power outages, crashes, or forced termination.

```mermaid
sequenceDiagram
    autonumber
    participant User as User / OS
    participant Main as Electron Main Process
    participant Bridge as PythonBridge
    participant Server as Python Server
    participant Recovery as TaskRecoveryService (recovery.py)
    participant DB as SQLite Database
    participant Disk as Local Filesystem
    participant React as React UI

    User->>Main: Launches application
    Main->>Bridge: pythonBridge.start()
    Bridge->>Server: Spawns Python process & ping handshake
    Server-->>Bridge: pong (Python online)

    %% Automatic Startup Recovery
    Main->>Bridge: sendRequest("recover_interrupted_tasks", { auto_resume: true })
    Bridge->>Server: Stdio JSON-RPC: "recover_interrupted_tasks"
    Server->>Recovery: recover_interrupted_tasks(auto_resume=true)

    Recovery->>DB: Query tasks where status IN (downloading, merging, scanning, queued)
    DB-->>Recovery: Unfinished task list

    loop For each uncompleted task
        Recovery->>Disk: Check if destination_path exists on disk
        alt Destination file exists and non-empty
            Recovery->>DB: Update task.status = COMPLETED (recovered_count++)
        else Check if temp_path (.part) exists on disk
            Recovery->>Disk: Inspect .part file size (stat.st_size)
            Recovery->>DB: Update bytes_downloaded = size, status = PAUSED (paused_count++)
            alt Corrupted Intermediate Merge Files Exist (.video.part / .audio.part)
                Recovery->>Disk: Remove orphan merge files
            end
            alt auto_resume == true
                Recovery->>Recovery: Re-enqueue task in DownloadManager (resumed_count++)
            end
        else No file on disk
            Recovery->>DB: Update task.status = PAUSED (0 bytes)
        end
    end

    Recovery-->>Server: RecoverySummary (recovered_count, paused_count, resumed_count)
    Server-->>Bridge: Stdio Response: { recovered_count, resumed_count, paused_count }
    Bridge-->>Main: Log recovery statistics
    Main->>React: Mounts window & sends initial queue state
    React-->>User: Shows recovery alert banner if paused tasks require attention
```

---

## 6. Flow 6: Saved Sources Bookmark & Incremental Rescan

Traces bookmarking a channel/gallery and periodically discovering only new media items.

```mermaid
sequenceDiagram
    autonumber
    actor User as User
    participant React as React UI (SavedSourcesView)
    participant Preload as Preload (window.api)
    participant Main as Electron Main
    participant Server as Python Server (dispatcher.py)
    participant Rescan as Rescan Engine (rescan.py)
    participant Extractor as Extraction Adapters
    participant DB as MediaRepository / SQLite

    %% Bookmark Action
    User->>React: Clicks "Bookmark Source" on scan result
    React->>Preload: saveSource({ url, title, platform, tags })
    Preload->>Main: ipcRenderer.invoke("python:saveSource", ...)
    Main->>Server: JSON-RPC "save_source"
    Server->>DB: save_source(SavedSource)
    DB-->>Server: SavedSource record
    Server-->>React: Source bookmarked notification

    %% Incremental Rescan
    User->>React: Clicks "Rescan" (or "Rescan All")
    React->>Preload: rescanSource(sourceId)
    Preload->>Main: ipcRenderer.invoke("python:rescanSource", sourceId)
    Main->>Server: JSON-RPC "rescan_source"
    Server->>Rescan: incremental_rescan_source(source_id)

    %% Differential Resolution
    Rescan->>DB: get_known_item_urls_for_source(source.url)
    DB-->>Rescan: Set of already known item URLs: Set(url1, url2, ...)
    Rescan->>Extractor: scan_source_url(source.url)
    Extractor-->>Rescan: Currently discovered items: [itemA, itemB, itemC]

    loop For each discovered item
        alt item.original_url in known_urls
            Rescan->>Rescan: Append to existing_items
        else item.original_url NOT in known_urls
            Rescan->>Rescan: Append to new_items (delta)
        end
    end

    Rescan->>DB: save_scan_result(discovered_items)
    Rescan->>DB: update_source_scan_stats(source.id, total, timestamp)
    Rescan-->>Server: IncrementalScanResult (new_items, existing_items, new_item_count)
    Server-->>React: Return IncrementalScanResult

    React-->>User: Opens Incremental Rescan Modal with diff breakdown (e.g., "5 New / 20 Total")
    User->>React: Clicks "Download All New Items"
    React->>Preload: startBatchDownload(new_items)
```

---

## 7. Flow 7: Session Cookie Import & Subdomain Header Injection

Traces importing browser cookies and automatically attaching them to restricted download requests.

```mermaid
sequenceDiagram
    autonumber
    actor User as User
    participant React as React UI (SettingsView)
    participant Preload as Preload (window.api)
    participant Main as Electron Main
    participant Server as Python Server
    participant Auth as Auth Engine (cookies.py / headers.py)
    participant Downloader as Stream Downloader
    participant DB as SQLite Database
    participant Remote as Remote Media Host

    User->>React: Selects "Chrome" and clicks "Extract Browser Cookies"
    React->>Preload: importBrowserCookies("chrome", "instagram.com")
    Preload->>Main: ipcRenderer.invoke("python:importBrowserCookies", ...)
    Main->>Server: JSON-RPC "import_browser_cookies"
    
    Server->>Auth: extract_browser_cookies("chrome", domain="instagram.com")
    Auth->>Auth: Query local Chrome DPAPI cookie database via yt-dlp cookiejar
    Auth->>Auth: Format valid cookies into Netscape tab-delimited text
    Auth->>Auth: Save sanitized file to %LOCALAPPDATA%/XakuMedia/auth/cookies/
    Auth-->>Server: CookieProfileRecord (cookie_count: 42)
    Server->>DB: save_cookie_profile(profile)
    Server-->>React: Active profile displayed in table

    %% Subsequent Download Request
    User->>React: Initiates download for restricted media URL
    React->>Server: start_download(item)
    Server->>Downloader: download_stream(url, ...)
    
    Downloader->>DB: get_cookie_profile_for_domain(url)
    DB-->>Downloader: CookieProfileRecord
    Downloader->>Auth: get_cookies_dict_from_file(profile.cookie_file_path)
    Auth-->>Downloader: req_cookies dict
    
    Downloader->>DB: list_all_domain_headers()
    DB-->>Downloader: domain_headers map
    Downloader->>Auth: build_request_headers_for_url(url, domain_headers)
    Auth->>Auth: Subdomain hierarchy match: e.g. "cdn.instagram.com" -> inherits "instagram.com"
    Auth-->>Downloader: req_headers (User-Agent, Authorization, Referer)
    
    Downloader->>Remote: httpx.get(url, cookies=req_cookies, headers=req_headers)
    Remote-->>Downloader: HTTP 200 OK (Authenticated media stream transferred)
```

---

## 8. Flow 8: Media Library Search, Thumbnail Caching & `media-loader://` Playback

Traces searching saved media items, generating cached thumbnails, and streaming local video inside the renderer.

```mermaid
sequenceDiagram
    autonumber
    actor User as User
    participant React as React UI (App.tsx)
    participant Preload as Preload (window.api)
    participant Main as Electron Main
    participant Server as Python Server
    participant Thumb as Thumbnail Engine (thumbnail.py)
    participant MediaLoader as media-loader:// Protocol Handler
    participant Disk as Local Filesystem

    %% Library Search & Query
    User->>React: Switches to "Media Library" tab & enters search query
    React->>Preload: querySavedMedia({ query: "nature", media_type: "video", sort_by: "newest" })
    Preload->>Main: ipcRenderer.invoke("python:querySavedMedia", ...)
    Main->>Server: JSON-RPC "query_saved_media"
    Server->>Server: Execute repository SQL with parameter binding & LIKE search
    Server-->>React: DiscoveredMediaItem[]

    %% Thumbnail On-Demand Caching
    React->>Preload: generateThumbnail(source_path, item_id, "video")
    Preload->>Main: ipcRenderer.invoke("python:generateThumbnail", ...)
    Main->>Server: JSON-RPC "generate_thumbnail"
    Server->>Thumb: generate_media_thumbnail(source_path, item_id)
    alt Cached WebP exists in %LOCALAPPDATA%/cache/thumbnails/
        Thumb-->>Server: Return cached path
    else Thumbnail does not exist
        Thumb->>Thumb: Execute FFmpeg: ffmpeg -ss 1.00 -i video.mp4 -vframes 1 -vf scale='min(480,iw)':-1 thumb.tmp.webp
        Thumb->>Disk: Atomic rename: thumb.tmp.webp -> {item_id}.webp
        Thumb-->>Server: Return new thumbnail path
    end
    Server-->>React: ThumbnailResult

    %% Playback Initiation
    User->>React: Clicks "Play" on media card
    React->>React: Open in-app video modal: set <video src="media-loader://video?path=C%3A%5C...%5Cvideo.mp4">
    React->>MediaLoader: Chromium requests media-loader://...
    MediaLoader->>MediaLoader: Validate path (reject UNC, reject NTFS ADS ':', check extension whitelist)
    MediaLoader->>Disk: net.fetch(pathToFileURL(normalizedPath))
    Disk-->>MediaLoader: HTTP 206 Partial Content (streaming chunks with Range support)
    MediaLoader-->>React: Video streams directly to HTML5 <video> element with hardware acceleration
```

---

## 9. Flow 9: Application Settings Update & Synchronization

Traces updating user preferences and synchronizing runtime state across Python and Electron.

```mermaid
sequenceDiagram
    autonumber
    actor User as User
    participant React as React UI (SettingsView)
    participant Preload as Preload (window.api)
    participant Main as Electron Main
    participant Server as Python Server
    participant Mgr as DownloadManager
    participant Throttler as BandwidthThrottler
    participant DB as SQLite Database

    %% Directory Picker
    User->>React: Clicks "Browse" download directory
    React->>Preload: selectFolder(currentPath)
    Preload->>Main: ipcRenderer.invoke("dialog:selectFolder", currentPath)
    Main->>Main: dialog.showOpenDialog({ properties: ["openDirectory", "createDirectory"] })
    Main-->>React: Selected folder path (e.g. "D:\Media")

    %% Save Preferences
    User->>React: Adjusts concurrency (5) & speed limit (2 MB/s) and clicks "Save"
    React->>Preload: updatePreferences({ download_dir: "D:\Media", max_concurrent_downloads: 5, max_download_speed_kbps: 2048 })
    Preload->>Main: ipcRenderer.invoke("preferences:update", ...)
    Main->>Server: JSON-RPC "update_preferences"
    
    Server->>DB: update_preferences(dict)
    DB-->>Server: Updated preferences
    
    %% Dynamic Runtime Synchronization
    Server->>Mgr: set_concurrency(5)
    Mgr->>Mgr: Update max_concurrent & schedule next pending tasks
    Server->>Throttler: set_speed_limit(2048)
    Throttler->>Throttler: Update rate limit dynamically (active worker streams throttle immediately)
    
    Server-->>Main: Return updated preferences
    Main-->>React: Updated state confirmed
    React-->>User: Green "Preferences saved successfully" toast
```

---

## 10. Flow 10: Application Lifecycle (Startup & Graceful Shutdown)

Traces the desktop initialization and clean exit lifecycle.

```mermaid
sequenceDiagram
    autonumber
    actor User as User
    participant Main as Electron Main Process
    participant Bridge as PythonBridge
    participant Server as Python Server Process
    participant DB as SQLite Database
    participant React as React Renderer

    %% Startup Sequence
    User->>Main: Launches XakuMedia
    Main->>Main: app.requestSingleInstanceLock()
    alt Lock Acquired
        Main->>Main: protocol.registerSchemesAsPrivileged(["media-loader"])
        Main->>Main: setupSecurityHeaders() (Strict CSP)
        Main->>Main: registerIpcHandlers() (38+ handlers)
        Main->>Bridge: pythonBridge.start()
        Bridge->>Server: Spawn: python.exe -m xakumedia.server
        Bridge->>Server: Initial JSON-RPC "ping" probe
        Server->>DB: init_schema() (Run migrations V1-V4, enable WAL mode)
        Server-->>Bridge: pong (status: "ok", version: "0.1.0")
        Bridge->>Server: recover_interrupted_tasks()
        Main->>Main: createWindow() -> loadFile("frontend/dist/index.html")
        Main->>React: ready-to-show event -> mainWindow.show()
    else Lock Failed (Second Instance Launched)
        Main->>Main: Log warning: "Another instance holds the lock"
        Main->>User: Secondary instance focuses primary window and exits
    end

    %% Graceful Shutdown Sequence
    User->>Main: Closes window / app.quit()
    Main->>Main: app.on("before-quit") intercepted (event.preventDefault())
    Main->>Bridge: pythonBridge.stop()
    Bridge->>Server: Close stdin pipe (EOF signal)
    Server->>Server: Event loop terminates cleanly, flush SQLite WAL checkpoints
    Server-->>Bridge: Process exits (code 0)
    Bridge-->>Main: Shutdown resolved
    Main->>Main: app.quit() executes (Zero zombie processes left)
```

