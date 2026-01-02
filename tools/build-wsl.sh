#!/bin/bash
# Build script for WSL (if you want to cross-compile or use WSL tools)
# Note: The DLL is Windows-specific, so WSL build would require cross-compilation setup

echo "WSL build setup for Civ V DLL"
echo "Note: This project uses Visual Studio/MSBuild on Windows."
echo "WSL can be used for Python development, but the DLL must be built with MSVC."
echo ""
echo "To install build tools in WSL (for Python/C++ development):"
echo "  sudo apt-get update"
echo "  sudo apt-get install -y build-essential cmake python3-dev"
echo ""
echo "For the DLL, use MSBuild on Windows (see tools/build.ps1)"

