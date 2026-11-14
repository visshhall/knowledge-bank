<#
.SYNOPSIS
  One-time setup of the Knowledge Bank app on Windows.

.DESCRIPTION
  WHAT:  Installs and prepares everything the app needs, in order:
           1. Python 3.12   (runs the engine)            - via winget if missing
           2. Node.js LTS   (builds/runs the window)     - via winget if missing
           3. Ollama        (runs the local AI models)   - via winget if missing
           4. Engine libraries into engine\.venv (a private Python environment)
           5. Interface libraries into app\node_modules
           6. Starts Ollama if it isn't running
           7. Downloads the AI models (skip with -SkipModels)
           8. Runs the system check and shows what (if anything) still needs fixing

  WHY:   So the owner never has to install or configure anything by hand.
         Safe to re-run at any time: anything already installed is skipped,
         and it doubles as a "repair" script.

  WHEN:  Once after downloading the project, and again after updates that
         add new libraries or models.

  CONNECTED TO:
         - engine\requirements.txt   (Python libraries installed)
         - app\package.json          (Node libraries installed)
         - engine\kb_engine\config.py (model names - kept in sync below)
         - engine\kb_engine\system_check.py (run at the end)

.EXAMPLE
  Open PowerShell in the project folder and run:
    powershell -ExecutionPolicy Bypass -File setup\setup.ps1
  To skip the large model downloads (e.g. to finish them later):
    powershell -ExecutionPolicy Bypass -File setup\setup.ps1 -SkipModels
#>

param(
    [switch]$SkipModels
)

# Stop on errors from PowerShell commands (external programs are checked manually).
$ErrorActionPreference = "Stop"

# Project root = the folder above this script, so the script works no matter
# which folder PowerShell was opened in.
$Root      = Split-Path -Parent $PSScriptRoot
$EngineDir = Join-Path $Root "engine"
$AppDir    = Join-Path $Root "app"
$VenvPy    = Join-Path $EngineDir ".venv\Scripts\python.exe"

# Models to download. MUST match engine\kb_engine\config.py:
#   FAST_MODEL, DEEP_MODEL, EMBED_MODEL, plus the extra benchmark candidates.
$Models = @("qwen3.5:4b", "qwen3:8b", "nomic-embed-text", "qwen3:4b", "llama3.1:8b")

function Write-Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Write-Ok($text)   { Write-Host "    OK  $text" -ForegroundColor Green }
function Write-Warn($text) { Write-Host "    !!  $text" -ForegroundColor Yellow }

<#
  Reload PATH from the registry. Needed because programs installed by winget
  during this script aren't visible to the already-open PowerShell window
  until PATH is refreshed.
#>
function Update-SessionPath {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user    = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

<# True if a command (e.g. "node") can be found on PATH. #>
function Test-Command($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

<#
  Install a package with winget unless it's already present.
  $check = a script block that returns $true when the tool is installed.
#>
function Install-IfMissing($label, $wingetId, [scriptblock]$check) {
    if (& $check) { Write-Ok "$label already installed"; return }
    if (-not (Test-Command "winget")) {
        throw "winget is not available. Install '$label' manually, then re-run this script."
    }
    Write-Host "    Installing $label (a Windows prompt may appear)..."
    winget install --id $wingetId -e --silent --accept-package-agreements --accept-source-agreements
    Update-SessionPath
    if (-not (& $check)) {
        throw "$label installation could not be verified. Close PowerShell, open a new one, and re-run."
    }
    Write-Ok "$label installed"
}

<#
  Find a real Python 3.11+ (not the Microsoft Store placeholder).
  Tries the official 'py' launcher first, then 'python'.
  Returns the command to use, or $null.
#>
function Find-Python {
    foreach ($candidate in @(@("py", "-3.12"), @("py", "-3.11"), @("python"))) {
        $exe = $candidate[0]
        if (-not (Test-Command $exe)) { continue }
        $extra = @()
        if ($candidate.Length -gt 1) { $extra = $candidate[1..($candidate.Length - 1)] }
        try {
            $version = & $exe @extra -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($version -and [version]$version -ge [version]"3.11") { return ,$candidate }
        } catch { }
    }
    return $null
}

<# True if Ollama answers on its local port. #>
function Test-Ollama {
    try {
        Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/version" -UseBasicParsing -TimeoutSec 3 | Out-Null
        return $true
    } catch { return $false }
}

Write-Host "Knowledge Bank - setup" -ForegroundColor Cyan
Write-Host "Project folder: $Root"

# ---------------------------------------------------------------- 1. Python
Write-Step "Python 3.11+"
Install-IfMissing "Python 3.12" "Python.Python.3.12" { [bool](Find-Python) }
$Py = Find-Python

# ---------------------------------------------------------------- 2. Node.js
Write-Step "Node.js"
Install-IfMissing "Node.js LTS" "OpenJS.NodeJS.LTS" { Test-Command "node" }

# ---------------------------------------------------------------- 3. Ollama
Write-Step "Ollama (local AI runtime)"
Install-IfMissing "Ollama" "Ollama.Ollama" { Test-Command "ollama" }

# ---------------------------------------------------------------- 4. Engine libraries
Write-Step "Engine libraries (Python)"
if (-not (Test-Path $VenvPy)) {
    $pyArgs = @()
    if ($Py.Length -gt 1) { $pyArgs = $Py[1..($Py.Length - 1)] }
    & $Py[0] @pyArgs -m venv (Join-Path $EngineDir ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Could not create the Python environment." }
}
& $VenvPy -m pip install --upgrade pip --quiet
& $VenvPy -m pip install -r (Join-Path $EngineDir "requirements.txt") --quiet
if ($LASTEXITCODE -ne 0) { throw "Installing engine libraries failed (see messages above)." }
Write-Ok "engine libraries installed"

# ---------------------------------------------------------------- 5. App libraries
Write-Step "App libraries (Node.js)"
Push-Location $AppDir
try {
    npm install --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw "npm install failed (see messages above)." }
} finally { Pop-Location }
Write-Ok "app libraries installed"

# ---------------------------------------------------------------- 6. Start Ollama
Write-Step "Starting Ollama"
if (-not (Test-Ollama)) {
    # 'ollama serve' runs the service in the background without a window.
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    for ($i = 0; $i -lt 30 -and -not (Test-Ollama); $i++) { Start-Sleep -Seconds 1 }
}
if (Test-Ollama) { Write-Ok "Ollama is running" } else { Write-Warn "Ollama did not start. Open it from the Start menu, then re-run." }

# ---------------------------------------------------------------- 7. Models
if ($SkipModels) {
    Write-Step "Skipping model downloads (-SkipModels)"
} elseif (Test-Ollama) {
    Write-Step "Downloading AI models (about 15 GB in total; this can take a while)"
    foreach ($m in $Models) {
        Write-Host "    ollama pull $m"
        ollama pull $m
        if ($LASTEXITCODE -ne 0) { Write-Warn "Could not download $m - re-run setup later to retry." }
    }
}

# ---------------------------------------------------------------- 8. Check
Write-Step "System check"
Push-Location $EngineDir
try { & $VenvPy -m kb_engine.system_check } finally { Pop-Location }

Write-Host "`nSetup finished." -ForegroundColor Green
Write-Host "Next: run the benchmark ->  powershell -ExecutionPolicy Bypass -File setup\run-benchmark.ps1 `"C:\path\to\5-10-pdfs`""
Write-Host "Or open the app ->         powershell -ExecutionPolicy Bypass -File setup\start-app.ps1"
