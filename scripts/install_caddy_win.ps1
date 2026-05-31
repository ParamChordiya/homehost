# HomeHost — Install Caddy on Windows
# Usage: .\install_caddy_win.ps1 [-Force]
#
# Strategy:
#   1. Check for an existing Caddy installation
#   2. Try winget  (Windows Package Manager)
#   3. Try Chocolatey
#   4. Fall back to direct binary download from GitHub Releases
#
# The binary ends up at one of:
#   - Whatever winget/choco manages (usually on PATH after install)
#   - %USERPROFILE%\.homehost\bin\caddy.exe  (direct download)

[CmdletBinding()]
param(
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Configuration ──────────────────────────────────────────────────────────────
$HomehostBin      = Join-Path $env:USERPROFILE ".homehost\bin"
$CaddyGitHubApi   = "https://api.github.com/repos/caddyserver/caddy/releases/latest"
$UserAgent        = "homehost/1.0"

# ── Helpers ────────────────────────────────────────────────────────────────────

function Write-Info    { param([string]$Msg) Write-Host "[homehost] $Msg" -ForegroundColor Cyan }
function Write-Success { param([string]$Msg) Write-Host "[homehost] $Msg" -ForegroundColor Green }
function Write-Warn    { param([string]$Msg) Write-Host "[homehost] WARNING: $Msg" -ForegroundColor Yellow }
function Write-Fail    { param([string]$Msg) Write-Error "[homehost] ERROR: $Msg" }

function Test-CommandExists {
    param([string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Invoke-VerifyCaddy {
    param([string]$Path)
    try {
        $output = & $Path version 2>&1 | Select-Object -First 1
        if ($LASTEXITCODE -eq 0 -and $output) { return $output.Trim() }
    } catch { }
    return $null
}

function New-HomehostBinDir {
    if (-not (Test-Path $HomehostBin)) {
        New-Item -ItemType Directory -Path $HomehostBin -Force | Out-Null
    }
}

function Get-LatestGitHubTag {
    try {
        $headers = @{ "Accept" = "application/vnd.github+json"; "User-Agent" = $UserAgent }
        $response = Invoke-RestMethod -Uri $CaddyGitHubApi -Headers $headers -TimeoutSec 15
        return $response.tag_name
    } catch {
        return $null
    }
}

function Invoke-FileDownload {
    param(
        [string]$Url,
        [string]$Destination
    )
    Write-Info "Downloading $Url"
    $wc = New-Object System.Net.WebClient
    $wc.Headers.Add("User-Agent", $UserAgent)

    $progressHandler = Register-ObjectEvent -InputObject $wc -EventName DownloadProgressChanged -Action {
        $pct = $Event.SourceEventArgs.ProgressPercentage
        Write-Progress -Activity "Downloading Caddy" -Status "$pct% complete" -PercentComplete $pct
    }

    try {
        $wc.DownloadFile($Url, $Destination)
    } finally {
        Unregister-Event -SourceIdentifier $progressHandler.Name -ErrorAction SilentlyContinue
        Remove-Job $progressHandler -ErrorAction SilentlyContinue
        Write-Progress -Activity "Downloading Caddy" -Completed
        $wc.Dispose()
    }
}

function Add-ToUserPath {
    param([string]$Dir)
    $currentPath = [System.Environment]::GetEnvironmentVariable("PATH", "User")
    if ($currentPath -split ";" | Where-Object { $_ -eq $Dir }) {
        return  # already present
    }
    $newPath = "$Dir;$currentPath"
    [System.Environment]::SetEnvironmentVariable("PATH", $newPath, "User")
    # Update current session PATH too
    $env:PATH = "$Dir;$env:PATH"
    Write-Warn "$Dir added to your user PATH. Restart your terminal for all sessions to see it."
}

# ── Step 1: Check existing installation ───────────────────────────────────────

function Test-ExistingInstallation {
    if ($Force) {
        Write-Info "-Force flag set; skipping existing installation check."
        return $false
    }

    # Check ~/.homehost/bin first
    $localCaddy = Join-Path $HomehostBin "caddy.exe"
    if (Test-Path $localCaddy) {
        $ver = Invoke-VerifyCaddy -Path $localCaddy
        if ($ver) {
            Write-Success "Caddy already installed at $localCaddy ($ver)"
            return $true
        }
    }

    if (Test-CommandExists "caddy") {
        $caddyPath = (Get-Command caddy).Source
        $ver = Invoke-VerifyCaddy -Path $caddyPath
        if ($ver) {
            Write-Success "Caddy already installed at $caddyPath ($ver)"
            return $true
        }
    }

    return $false
}

# ── Step 2: winget ────────────────────────────────────────────────────────────

function Install-ViaWinget {
    if (-not (Test-CommandExists "winget")) {
        Write-Warn "winget not available."
        return $false
    }

    Write-Info "Installing Caddy via winget…"
    try {
        winget install --id Caddy.Caddy --silent --accept-source-agreements --accept-package-agreements
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "winget install failed (exit code $LASTEXITCODE)."
            return $false
        }
    } catch {
        Write-Warn "winget install threw an exception: $_"
        return $false
    }

    # Refresh PATH so we can find caddy
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("PATH", "User")

    if (Test-CommandExists "caddy") {
        $caddyPath = (Get-Command caddy).Source
        $ver = Invoke-VerifyCaddy -Path $caddyPath
        if ($ver) {
            Write-Success "Caddy $ver installed via winget at $caddyPath"
            return $true
        }
    }

    Write-Warn "winget reported success but caddy is not on PATH."
    return $false
}

# ── Step 3: Chocolatey ────────────────────────────────────────────────────────

function Install-ViaChoco {
    if (-not (Test-CommandExists "choco")) {
        Write-Warn "Chocolatey (choco) not installed."
        return $false
    }

    Write-Info "Installing Caddy via Chocolatey…"
    try {
        choco install caddy -y --no-progress
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "choco install failed (exit code $LASTEXITCODE)."
            return $false
        }
    } catch {
        Write-Warn "choco install threw an exception: $_"
        return $false
    }

    # Refresh PATH
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("PATH", "User")

    if (Test-CommandExists "caddy") {
        $caddyPath = (Get-Command caddy).Source
        $ver = Invoke-VerifyCaddy -Path $caddyPath
        if ($ver) {
            Write-Success "Caddy $ver installed via Chocolatey at $caddyPath"
            return $true
        }
    }

    Write-Warn "Chocolatey reported success but caddy is not on PATH."
    return $false
}

# ── Step 4: Direct binary download ────────────────────────────────────────────

function Install-Direct {
    New-HomehostBinDir

    Write-Info "Fetching latest Caddy release info from GitHub…"
    $tag = Get-LatestGitHubTag
    if (-not $tag) {
        Write-Fail "Could not determine latest Caddy version from GitHub API."
        return $false
    }

    $version      = $tag.TrimStart("v")
    $archiveName  = "caddy_${version}_windows_amd64.zip"
    $downloadUrl  = "https://github.com/caddyserver/caddy/releases/download/${tag}/${archiveName}"

    $tmpDir       = New-TemporaryFile | ForEach-Object { Remove-Item $_; New-Item -ItemType Directory -Path $_.FullName }
    $archivePath  = Join-Path $tmpDir.FullName $archiveName

    try {
        Invoke-FileDownload -Url $downloadUrl -Destination $archivePath

        Write-Info "Extracting $archiveName…"
        Expand-Archive -Path $archivePath -DestinationPath $tmpDir.FullName -Force

        $extractedBinary = Join-Path $tmpDir.FullName "caddy.exe"
        if (-not (Test-Path $extractedBinary)) {
            # Sometimes the exe has a different name; search for it
            $extractedBinary = Get-ChildItem $tmpDir.FullName -Filter "caddy*.exe" | Select-Object -First 1 -ExpandProperty FullName
        }
        if (-not $extractedBinary -or -not (Test-Path $extractedBinary)) {
            Write-Fail "caddy.exe not found after extraction. Contents: $(Get-ChildItem $tmpDir.FullName | Select-Object -ExpandProperty Name)"
            return $false
        }

        $dest = Join-Path $HomehostBin "caddy.exe"
        Copy-Item -Path $extractedBinary -Destination $dest -Force

        $ver = Invoke-VerifyCaddy -Path $dest
        if (-not $ver) {
            Write-Fail "Installed caddy.exe at $dest failed to execute."
            return $false
        }

        Write-Success "Caddy $ver installed at $dest"
        Add-ToUserPath -Dir $HomehostBin
        return $true

    } finally {
        Remove-Item -Recurse -Force $tmpDir.FullName -ErrorAction SilentlyContinue
    }
}

# ── Main ───────────────────────────────────────────────────────────────────────

function Main {
    Write-Info "HomeHost — Caddy installer (Windows)"
    Write-Info "======================================"

    # Require Windows
    if ($env:OS -ne "Windows_NT") {
        Write-Fail "This script is for Windows only. For macOS, use install_caddy_mac.sh."
    }

    if (Test-ExistingInstallation) { return }

    Write-Info "Caddy not found$(if ($Force) { ' (--Force)' }). Proceeding with installation…"

    if (Install-ViaWinget)  { return }
    if (Install-ViaChoco)   { return }

    Write-Info "Falling back to direct binary download…"
    if (-not (Install-Direct)) {
        Write-Fail "All installation methods failed. Please install Caddy manually from https://caddyserver.com/docs/install"
    }
}

Main
