<#
.SYNOPSIS
  Runs the Phase 0 model benchmark on a folder of the owner's PDFs.

.DESCRIPTION
  WHAT:  Calls engine\kb_engine\benchmark.py, which tests every candidate AI
         model on the same excerpts from your PDFs and writes a report.
  WHY:   The report decides which models the Knowledge Bank uses on your
         RTX 3060 (speed AND writing quality, measured on your own documents).
  WHEN:  Once, after setup\setup.ps1 has finished. Takes roughly 10-40
         minutes depending on how many models are downloaded.
  CONNECTED TO: engine\kb_engine\benchmark.py (does the work),
         engine\.venv (created by setup.ps1).

.PARAMETER PdfFolder
  A folder containing 5-10 representative PDFs (copy them into a new folder
  first; the originals are only read, never changed).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File setup\run-benchmark.ps1 "C:\Users\me\Desktop\bench-pdfs"
#>
param(
    [Parameter(Mandatory = $true)][string]$PdfFolder
)
$ErrorActionPreference = "Stop"

$Root      = Split-Path -Parent $PSScriptRoot
$EngineDir = Join-Path $Root "engine"
$VenvPy    = Join-Path $EngineDir ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPy)) { throw "Engine not installed. Run setup\setup.ps1 first." }
if (-not (Test-Path $PdfFolder -PathType Container)) { throw "Folder not found: $PdfFolder" }

Push-Location $EngineDir
try {
    & $VenvPy -m kb_engine.benchmark --pdfs $PdfFolder
} finally { Pop-Location }

# Open the reports folder so the owner can find the file to send.
$reports = Join-Path $env:LOCALAPPDATA "KnowledgeBank\reports"
if (Test-Path $reports) { Invoke-Item $reports }
