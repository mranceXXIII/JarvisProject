# JARVIS release packaging script (Phase 12).
# Creates a distributable zip of the project without dev/runtime artifacts.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\package_release.ps1
#
# The output zip lands in releases\jarvis-<timestamp>.zip. Recipients run:
#   py -3.14 -m venv .venv
#   .\.venv\Scripts\Activate.ps1
#   python -m pip install -r requirements.txt
#   python main.py

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$releaseDir = Join-Path $projectRoot "releases"
$stagingDir = Join-Path $releaseDir "jarvis-$timestamp"
$zipPath = "$stagingDir.zip"

if (Test-Path $stagingDir) { Remove-Item $stagingDir -Recurse -Force }
New-Item -ItemType Directory -Path $stagingDir -Force | Out-Null

Get-ChildItem -Path $projectRoot -Force | Where-Object {
    $_.Name -notin @('.venv', '.git', 'releases')
} | ForEach-Object {
    Copy-Item -Path $_.FullName -Destination $stagingDir -Recurse -Force
}

# Copy everything, then strip dev/runtime artifacts.

$excludeDirs = @(".venv", ".git", "__pycache__", ".pytest_cache", ".ruff_cache",
                 "data", "logs", "releases", "node_modules")
foreach ($dir in $excludeDirs) {
    Get-ChildItem -Path $stagingDir -Recurse -Directory -Filter $dir -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}
Get-ChildItem -Path $stagingDir -Recurse -Include "*.pyc", "*.log", ".env" -File -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue

# Never ship secrets or tokens.
Get-ChildItem -Path $stagingDir -Recurse -Include "google_client_secret*.json", "*token*.json" -File -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue

# Sanity: the release must contain the entry point and requirements.
if (-not (Test-Path (Join-Path $stagingDir "main.py"))) {
    throw "main.py missing from staging - aborting"
}
if (-not (Test-Path (Join-Path $stagingDir "requirements.txt"))) {
    throw "requirements.txt missing from staging - aborting"
}

Compress-Archive -Path $stagingDir -DestinationPath $zipPath -Force
Remove-Item $stagingDir -Recurse -Force

Write-Host "Release created: $zipPath"

