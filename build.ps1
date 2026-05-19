# Bolo Windows App Builder
# Usage: powershell -ExecutionPolicy Bypass -File build.ps1
#
# Single source of truth for build config is Bolo.spec — edit hidden imports
# and excludes there, NOT here.

$ErrorActionPreference = "Stop"
$AppName = "Bolo"

# Read version from src/config.py — single source of truth for VERSION
$VersionLine = (Select-String -Path "src/config.py" -Pattern '^VERSION\s*=' | Select-Object -First 1).Line
$Version = ($VersionLine -split '"')[1]
if (-not $Version) { throw "Could not parse VERSION from src/config.py" }

Write-Host "=== Bolo v$Version - Build Script ===" -ForegroundColor Cyan

# Recommend venv usage
if (-not $env:VIRTUAL_ENV) {
    Write-Host "WARNING: No virtualenv detected." -ForegroundColor Yellow
    Write-Host "         Run inside a venv to avoid polluting global Python." -ForegroundColor Yellow
}

# Clean previous builds
if (Test-Path "dist")  { Remove-Item -Recurse -Force "dist" }
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }

# Ensure dependencies (skip pyinstaller — it's already a build dep)
Write-Host "[1/3] Verifying dependencies..." -ForegroundColor Yellow
pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) { throw "Dependency install failed" }

# Build via spec file (NOT inline flags — keeps config in one place).
# `python -m PyInstaller` instead of `pyinstaller` so it works without the
# Scripts dir being on PATH.
Write-Host "[2/3] Building executable from Bolo.spec..." -ForegroundColor Yellow
python -m PyInstaller --clean --noconfirm Bolo.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

# Report result
Write-Host "[3/3] Build complete." -ForegroundColor Green
$exe = "dist\$AppName.exe"
if (Test-Path $exe) {
    $sizeMB = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    Write-Host "  Output: $exe" -ForegroundColor Green
    Write-Host "  Size  : $sizeMB MB" -ForegroundColor Green
} else {
    Write-Host "  WARNING: $exe not found." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "NOTE: The zero-stt-hinglish model is auto-downloaded on first" -ForegroundColor Yellow
Write-Host "      Hinglish transcription. No manual model setup required." -ForegroundColor Yellow
