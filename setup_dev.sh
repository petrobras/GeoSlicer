#!/usr/bin/env bash

set -e

echo "🚀 Starting GeoSlicer development environment setup..."

TARGET_UV_VERSION="0.11.11"
INSTALL_UV=true

# Check if 'uv' is installed and verify its version
if command -v uv &> /dev/null; then
    UV_VERSION=$(uv --version 2>/dev/null)
    if [[ "$UV_VERSION" == *"$TARGET_UV_VERSION"* ]]; then
        echo "✅ 'uv' is already installed with the correct version ($TARGET_UV_VERSION)."
        INSTALL_UV=false
    else
        echo "📦 'uv' is installed, but version mismatch detected ($UV_VERSION). Adjusting to version $TARGET_UV_VERSION..."
    fi
else
    echo "📦 'uv' could not be found."
fi

# Install or force-adjust to the specified version if required
if [ "$INSTALL_UV" = true ]; then
    if [[ "$OSTYPE" == "linux-gnu"* ]] || [[ "$OSTYPE" == "darwin"* ]]; then
        echo "📦 Installing 'uv' version $TARGET_UV_VERSION via official script..."
        curl -LsSf "https://astral.sh/uv/$TARGET_UV_VERSION/install.sh" | sh
        export PATH="$HOME/.local/bin:$PATH"
        
        # Source the newly installed paths to make 'uv' instantly available in the current session
        source "$HOME/.cargo/env" 2>/dev/null || source "$HOME/.local/bin/env" 2>/dev/null || true
    else
        echo "❌ Unsupported OS for this bash script. Please install uv manually or use WSL."
        exit 1
    fi
fi

# Install the target Python version
echo "🐍 Ensuring Python 3.12 is installed..."
uv python install 3.12

# Init submodules
git submodule update --init --recursive

# Create the virtual environment and install all dependencies
echo "📥 Syncing project dependencies..."
uv sync --all-extras --all-groups --all-packages

# Remove existing git hooks
rm -rf .git/hooks/*

# Set up Git LFS and pre-commit hooks cleanly
echo "📥 Syncing and layering Git hooks..."

git config --unset core.hooksPath || true
# Force Git LFS to write its hooks locally first
if command -v git-lfs &>/dev/null; then
    git lfs install --local --force || true
else
    echo "❌ Git LFS could not be found. Please install it before running this script."
    exit 2
fi

# Force pre-commit to overwrite the LFS hooks
uv run pre-commit install --overwrite
uv run pre-commit install --hook-type pre-push --overwrite
legacy_hook="$(git rev-parse --git-path hooks)/pre-push.legacy"
if [ -f "$legacy_hook" ]; then
    sed -i.bak '1s|^#!/bin/sh$|#!/usr/bin/env sh|' "$legacy_hook" && rm -f "$legacy_hook.bak"
fi

echo "--------------------------------------------------------"
echo "🎉 Setup complete! Your environment is ready."
echo "👉 To deploy, run:"
echo "   uv run deploy [OPTIONS] <archive>"
echo "👉 To run the test suite, run:"
echo "   uv run pytest"
echo "👉 To run the auto formatter, run:"
echo "   uv run ruff format ."
echo "--------------------------------------------------------"
