#!/bin/bash
# Build the DLL using WSL (requires cross-compilation setup or native Windows build tools)
# This is a placeholder - WSL typically can't build Windows DLLs directly
# You'd need MinGW-w64 or similar cross-compiler

set -e

echo "WSL build script for Civ V DLL"
echo "Note: This project requires Windows-specific build tools (MSVC) to build the DLL."
echo "WSL cannot directly build Windows DLLs without cross-compilation setup."
echo ""
echo "Options:"
echo "1. Use MSBuild from Windows (recommended): .\tools\build-dll.ps1"
echo "2. Install MinGW-w64 in WSL for cross-compilation (complex, not recommended)"
echo ""
echo "For now, checking if build tools are available..."

if command -v cmake &> /dev/null; then
    echo "✓ cmake found"
else
    echo "✗ cmake not found"
    echo "  Install with: sudo apt-get install -y build-essential cmake"
fi

if command -v g++ &> /dev/null; then
    echo "✓ g++ found: $(g++ --version | head -1)"
else
    echo "✗ g++ not found"
    echo "  Install with: sudo apt-get install -y build-essential"
fi

echo ""
echo "To set up passwordless sudo, run from WSL:"
echo "  bash tools/setup-wsl-sudo.sh"

