# Build Instructions

This document describes how to build the Civ V DLL project.

## Windows Build (Recommended)

The DLL must be built on Windows using MSVC (Microsoft Visual C++). This is the primary and recommended build method.

### Prerequisites

- **Visual Studio 2022** (Community, Professional, or Enterprise) with:
  - Desktop development with C++ workload
  - MSBuild tools

### Quick Build

Use the provided PowerShell script:

```powershell
.\tools\build-dll.ps1 -Configuration Release
```

Or build manually with MSBuild:

```powershell
$msbuild = "C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe"
& $msbuild dll\CvGameCoreExpansion2.sln /t:Build /p:Configuration=Release /p:Platform=Win32 /p:PlatformToolset=v143
```

### Output Location

The DLL will be built to:
- `dll\CvGameCoreExpansion2\bin\Win32\Release\CvGameCore_Expansion2.dll`

### Build Configurations

- **Release**: Optimized build for production use
- **Debug**: Debug symbols, no optimization

### Platform Toolset

The project supports multiple Visual Studio toolsets:
- `v143` (VS 2022) - Recommended
- `v142` (VS 2019)
- `v120` (VS 2013) - Legacy fallback

## WSL Build (Not Supported)

**Note**: WSL cannot directly build Windows DLLs. This project requires MSVC and Windows-specific build tools.

WSL build tools (gcc, cmake) are available for other purposes, but cannot compile this Windows DLL project. To build Windows DLLs from WSL, you would need:
- MinGW-w64 cross-compiler (complex setup, not recommended)
- Wine + MSVC (not practical)

## Troubleshooting

### MSBuild Not Found

If MSBuild is not found, install Visual Studio 2022 with the C++ workload, or specify the path manually:

```powershell
$env:Path += ";C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin"
```

### Build Succeeds But No DLL

Check the actual output path. The DLL may be in:
- `dll\CvGameCoreExpansion2\bin\Win32\Release\` (project-specific)
- `dll\bin\Win32\Release\` (solution-level)

### Missing Dependencies

This project requires:
- Civilization V SDK (for game headers - may need to be configured in project settings)
- RapidJSON (header-only, should be included or available)

### Solution File Issues

If Visual Studio reports the solution as corrupt:
1. Close Visual Studio
2. Delete the `.vs` folder in the `dll` directory
3. Open the solution file directly (not via "Open Folder")

