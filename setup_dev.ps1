$ErrorActionPreference = "Stop"

Write-Host "Starting GeoSlicer development environment setup..." -ForegroundColor Cyan

$TargetUvVersion = "0.11.11"
$InstallUv = $true

# Check if 'uv' is installed and verify its version
if (Get-Command "uv" -ErrorAction SilentlyContinue) {
    $uvVersion = uv --version 2>$null
    if ($uvVersion -like "*$TargetUvVersion*") {
        Write-Host "'uv' is already installed with the correct version ($TargetUvVersion)." -ForegroundColor Green
        $InstallUv = $false
    } else {
        Write-Host "'uv' is installed, but version mismatch detected ($uvVersion). Adjusting to version $TargetUvVersion..." -ForegroundColor Yellow
    }
} else {
    Write-Host "'uv' could not be found." -ForegroundColor Yellow
}

# Install or force-adjust to the specified version if required
if ($InstallUv) {
    Write-Host "Installing 'uv' version $TargetUvVersion via official script..." -ForegroundColor Cyan
    Invoke-RestMethod -Uri "https://astral.sh/uv/$TargetUvVersion/install.ps1" | Invoke-Expression
    
    $uvPath = "$env:USERPROFILE\.local\bin"
    if ($env:PATH -notlike "*$uvPath*") {
        $env:PATH = "$uvPath;$env:PATH"
    }
}

# Install the target Python version
Write-Host "Ensuring Python 3.12 is installed..." -ForegroundColor Cyan
uv -q python install 3.12

# Init submodules
git submodule update --init --recursive
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to update submodules."
    return 1
}

# Create the virtual environment and install all dependencies
Write-Host "Syncing project dependencies..." -ForegroundColor Cyan
uv -q sync --all-extras --all-groups --all-packages

# Set up Git LFS and pre-commit hooks cleanly
Write-Host "Syncing and layering Git hooks..." -ForegroundColor Cyan

git config --unset core.hooksPath 2>$null

# Remove existing hooks
Remove-Item -Path .git\hooks\* -Force -Recurse

# Force Git LFS to write its hooks locally first
if (Get-Command "git-lfs" -ErrorAction SilentlyContinue) {
    git lfs install --local --force
} else {
    Write-Host "Git LFS could not be found. Please install it before running this script." -ForegroundColor Yellow
    return 2
}

# Force pre-commit to overwrite the LFS hooks
uv -q run pre-commit install --overwrite
uv -q run pre-commit install --hook-type pre-push --overwrite
$legacyHook = Join-Path (git rev-parse --git-path hooks) "pre-push.legacy"
if (Test-Path $legacyHook) {
    (Get-Content $legacyHook -Raw) -replace '\A#!/bin/sh', '#!/usr/bin/env sh' | Set-Content $legacyHook -NoNewline
}

Write-Host "--------------------------------------------------------" -ForegroundColor Magenta
Write-Host "Setup complete! Your environment is ready." -ForegroundColor Green
Write-Host "To deploy, run:"
Write-Host "   uv run deploy <archive> [OPTIONS]" 
Write-Host "To run the test suite, run:"
Write-Host "   uv run pytest"
Write-Host "To run the auto formatter, run:"
Write-Host "   uv run ruff format ."
Write-Host "--------------------------------------------------------" -ForegroundColor Magenta