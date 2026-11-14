<#
.SYNOPSIS
  Builds the interface and opens the Knowledge Bank app.

.DESCRIPTION
  WHAT:  Runs `npm run start` in the app folder, which builds the React
         interface (vite build) and launches Electron. Electron then starts
         the Python engine automatically (see app\electron\main.cjs).
  WHY:   Until the Windows installer exists (Phase 7), this is the one-click
         way to open the app.
  WHEN:  Any time the owner wants to use the app, after setup\setup.ps1.
  CONNECTED TO: app\package.json ("start" script), app\electron\main.cjs.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File setup\start-app.ps1
#>
$ErrorActionPreference = "Stop"
$AppDir = Join-Path (Split-Path -Parent $PSScriptRoot) "app"

if (-not (Test-Path (Join-Path $AppDir "node_modules"))) {
    throw "App not installed. Run setup\setup.ps1 first."
}
Push-Location $AppDir
try { npm run start } finally { Pop-Location }
