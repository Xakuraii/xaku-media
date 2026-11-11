<#
.SYNOPSIS
    XakuMedia — Unified Application & Server Launcher for Windows PowerShell.

.DESCRIPTION
    Runs the entire XakuMedia application (Frontend, Desktop Shell, and Python Backend)
    or standalone components from a single command, displaying live local view URLs.

.PARAMETER Web
    Run only the web frontend dev server and open http://localhost:5173 in default browser.

.PARAMETER Server
    Run only the standalone Python JSON-RPC backend engine (interactive debug console).

.PARAMETER OpenBrowser
    Open http://localhost:5173 in the default web browser alongside the Electron window.

.PARAMETER Verify
    Run the pre-flight environment and dependency diagnostics.

.PARAMETER Clean
    Run workspace cache cleanup (build artifacts, Python caches, temporary files).

.PARAMETER Port
    Custom port for the Vite development server (default: 5173).

.EXAMPLE
    .\scripts\run.ps1
    Starts the full desktop application (Vite + Electron + Python) with local view URL.

.EXAMPLE
    .\scripts\run.ps1 -OpenBrowser
    Starts the full application and automatically opens the local web view in browser.

.EXAMPLE
    .\scripts\run.ps1 -Web
    Runs only the web frontend with local browser view.

.EXAMPLE
    .\scripts\run.ps1 -Server
    Runs the standalone Python backend debug server.
#>

[CmdletBinding()]
param(
    [switch]$Web,
    [switch]$Server,
    [switch]$OpenBrowser,
    [switch]$Verify,
    [switch]$Clean,
    [string]$Port = "5173"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir
Set-Location $RootDir

function Write-Banner {
    Write-Host ""
    Write-Host "==========================================================================" -ForegroundColor Cyan
    Write-Host "        XAKURAII BULK DOWNLOADER (XAKUMEDIA) - ONE-CLICK LAUNCHER         " -ForegroundColor Cyan
    Write-Host "==========================================================================" -ForegroundColor Cyan
    Write-Host "  Root Directory: " -NoNewline -ForegroundColor DarkGray
    Write-Host "$RootDir" -ForegroundColor White
    Write-Host "  Timestamp:      " -NoNewline -ForegroundColor DarkGray
    Write-Host (Get-Date -Format "yyyy-MM-dd HH:mm:ss") -ForegroundColor DarkGray
    Write-Host ""
}

# Find local IPv4 address for local network view
function Get-LocalIpAddress {
    try {
        $ip = (Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias "Wi-Fi*", "Ethernet*" -ErrorAction SilentlyContinue |
               Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
               Select-Object -First 1).IPAddress
        if ($ip) { return $ip }
    } catch {}
    return "127.0.0.1"
}

# Check if a port is responding to HTTP requests
function Test-HttpServer {
    param([string]$Url, [int]$TimeoutSeconds = 25)
    $startTime = [DateTime]::UtcNow
    while (([DateTime]::UtcNow - $startTime).TotalSeconds -lt $TimeoutSeconds) {
        try {
            $req = [System.Net.WebRequest]::Create($Url)
            $req.Timeout = 1500
            $resp = $req.GetResponse()
            $resp.Close()
            return $true
        } catch {
            Start-Sleep -Milliseconds 400
        }
    }
    return $false
}

# Check whether a TCP port is currently listening
function Test-PortListening {
    param([int]$PortNumber)
    try {
        return ($null -ne (Get-NetTCPConnection -LocalPort $PortNumber -State Listen -ErrorAction SilentlyContinue))
    } catch {
        return $false
    }
}

# Free the Vite port before starting a new dev server. A stale Vite process
# from a previous run makes the new server exit on EADDRINUSE (strictPort),
# while the readiness check below still passes against the OLD server -
# leaving the Electron window blank.
function Clear-VitePort {
    param([int]$PortNumber)
    if (-not (Test-PortListening $PortNumber)) { return }

    $owners = Get-NetTCPConnection -LocalPort $PortNumber -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($ownerPid in $owners) {
        $procInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$ownerPid" -ErrorAction SilentlyContinue
        if ($procInfo -and $procInfo.CommandLine -like "*vite*") {
            Write-Host "[Launcher] Stopping stale Vite process (PID $ownerPid) holding port $PortNumber..." -ForegroundColor Yellow
            Stop-Process -Id $ownerPid -Force -ErrorAction SilentlyContinue
        } else {
            $procName = if ($procInfo) { $procInfo.Name } else { "unknown" }
            Write-Host "[Launcher] ERROR: Port $PortNumber is already used by another program ('$procName', PID $ownerPid)." -ForegroundColor Red
            Write-Host "         Close that program, or pick a different port:" -ForegroundColor Red
            Write-Host "         .\scripts\run.ps1 -Port 5174" -ForegroundColor Red
            exit 1
        }
    }

    # Wait until the port is actually released
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    while ((Test-PortListening $PortNumber) -and ([DateTime]::UtcNow -lt $deadline)) {
        Start-Sleep -Milliseconds 300
    }
}

Write-Banner

# -----------------------------------------------------------------------------
# Mode 1: Preflight Verification
# -----------------------------------------------------------------------------
if ($Verify) {
    Write-Host "[Launcher] Running pre-flight environment check..." -ForegroundColor Yellow
    node scripts/verify-env.mjs
    exit $LASTEXITCODE
}

# -----------------------------------------------------------------------------
# Mode 2: Workspace Clean
# -----------------------------------------------------------------------------
if ($Clean) {
    Write-Host "[Launcher] Running workspace cache cleanup..." -ForegroundColor Yellow
    node scripts/clean.mjs
    exit $LASTEXITCODE
}

# -----------------------------------------------------------------------------
# Mode 3: Standalone Python Backend Server
# -----------------------------------------------------------------------------
if ($Server) {
    Write-Host "[Launcher] Starting standalone Python backend JSON-RPC server..." -ForegroundColor Cyan
    node scripts/run-python-server.mjs
    exit $LASTEXITCODE
}

# -----------------------------------------------------------------------------
# Mode 4: Web-Only Mode (Frontend + Local Browser View)
# -----------------------------------------------------------------------------
if ($Web) {
    $LocalUrl = "http://localhost:" + $Port
    $LocalIp = Get-LocalIpAddress
    $NetworkUrl = "http://" + $LocalIp + ":" + $Port

    Write-Host "  Mode: " -NoNewline -ForegroundColor DarkGray
    Write-Host "Web Only (Browser Dev Mode)" -ForegroundColor Green
    Write-Host ""
    Write-Host "  * Local UI View:    " -NoNewline -ForegroundColor DarkGray
    Write-Host $LocalUrl -ForegroundColor Green
    Write-Host "  * Network UI View:  " -NoNewline -ForegroundColor DarkGray
    Write-Host $NetworkUrl -ForegroundColor Yellow
    Write-Host ""
    Write-Host "[Launcher] Starting Vite frontend server on port $Port..." -ForegroundColor Cyan

    Clear-VitePort -PortNumber ([int]$Port)

    $ViteProcess = Start-Process -FilePath "npm.cmd" -ArgumentList "--prefix", "frontend", "run", "dev" -PassThru -NoNewWindow
    
    # Wait for server to become responsive
    if (Test-HttpServer -Url $LocalUrl -TimeoutSeconds 20) {
        Write-Host "[Launcher] Server is LIVE! Opening local view in default browser..." -ForegroundColor Green
        Start-Process $LocalUrl
    }

    try {
        $ViteProcess.WaitForExit()
    } finally {
        if (-not $ViteProcess.HasExited) {
            Write-Host "[Launcher] Stopping Vite server..." -ForegroundColor Yellow
            Stop-Process -Id $ViteProcess.Id -Force -ErrorAction SilentlyContinue
        }
    }
    exit 0
}

# -----------------------------------------------------------------------------
# Mode 5: Full Application (Vite Dev Server + Desktop Shell + Python Engine)
# -----------------------------------------------------------------------------
$LocalUrl = "http://localhost:" + $Port
$LocalIp = Get-LocalIpAddress
$NetworkUrl = "http://" + $LocalIp + ":" + $Port

Write-Host "  * Local View URL: " -NoNewline -ForegroundColor DarkGray
Write-Host $LocalUrl -ForegroundColor Green
Write-Host "  * Network URL:    " -NoNewline -ForegroundColor DarkGray
Write-Host $NetworkUrl -ForegroundColor Yellow
Write-Host "  * Desktop Shell:  " -NoNewline -ForegroundColor DarkGray
Write-Host "Electron Native Window" -ForegroundColor Cyan
Write-Host "  * Backend Engine: " -NoNewline -ForegroundColor DarkGray
Write-Host "Python 3.12 (JSON-RPC stdio)" -ForegroundColor Magenta
Write-Host ""

# 1. Compile Desktop Electron bundles
Write-Host "[1/3] Compiling desktop Electron main and preload scripts..." -ForegroundColor Cyan
node scripts/build-desktop.mjs
if ($LASTEXITCODE -ne 0) {
    Write-Host "[Launcher] Error: Failed to compile desktop scripts." -ForegroundColor Red
    exit 1
}

# 2. Launch Vite Dev Server
Write-Host "[2/3] Starting Vite frontend server..." -ForegroundColor Cyan
Clear-VitePort -PortNumber ([int]$Port)
$ViteProcess = Start-Process -FilePath "npm.cmd" -ArgumentList "--prefix", "frontend", "run", "dev" -PassThru -NoNewWindow

# 3. Wait for Vite server to become responsive
Write-Host "[3/3] Waiting for local view ($LocalUrl) to be ready..." -ForegroundColor Cyan
$IsReady = Test-HttpServer -Url $LocalUrl -TimeoutSeconds 25

if (-not $IsReady) {
    Write-Host "[Launcher] Error: Vite dev server did not become ready at $LocalUrl within 25 seconds." -ForegroundColor Red
    Write-Host "         The desktop window would stay blank without it, so the launcher is stopping." -ForegroundColor Red
    if ($ViteProcess -and -not $ViteProcess.HasExited) {
        Stop-Process -Id $ViteProcess.Id -Force -ErrorAction SilentlyContinue
    }
    exit 1
} else {
    Write-Host "[Launcher] Local view is LIVE at $LocalUrl" -ForegroundColor Green
}

# Optionally open local view in web browser
if ($OpenBrowser) {
    Write-Host "[Launcher] Opening local view in default web browser..." -ForegroundColor Green
    Start-Process $LocalUrl
}

# 4. Launch Electron Desktop Shell
Write-Host ""
Write-Host "==========================================================================" -ForegroundColor Green
Write-Host "  XAKUMEDIA APP IS RUNNING!" -ForegroundColor Green
Write-Host "  Local View URL: $LocalUrl" -ForegroundColor Green
Write-Host "  Press Ctrl+C in this console to stop all processes and exit" -ForegroundColor Green
Write-Host "==========================================================================" -ForegroundColor Green
Write-Host ""

# The desktop shell is single-instance: if an XakuMedia window is already
# open, the Electron process below exits immediately (the app prints an
# explanation) instead of opening a second window.
$existingApp = Get-Process -Name "XakuMedia", "electron" -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowTitle -like "XakuMedia*" }
if ($existingApp) {
    Write-Host "[Launcher] NOTE: An XakuMedia window appears to already be open (PID $($existingApp[0].Id))." -ForegroundColor Yellow
    Write-Host "        The desktop shell is single-instance; close that window first or this launch will exit." -ForegroundColor Yellow
    Write-Host ""
}

$env:VITE_DEV_SERVER_URL = $LocalUrl

try {
    # Run Electron in the foreground
    & npx.cmd --prefix frontend electron desktop/dist/main.cjs
} finally {
    Write-Host ""
    Write-Host "[Launcher] Shutting down application and background services..." -ForegroundColor Yellow
    if ($ViteProcess -and -not $ViteProcess.HasExited) {
        Stop-Process -Id $ViteProcess.Id -Force -ErrorAction SilentlyContinue
    }
    # Clean up any lingering node vite instances on windows
    try {
        Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*vite*" } | ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
    } catch {}
    Write-Host "[Launcher] Shutdown complete. Goodbye!" -ForegroundColor DarkGray
}
