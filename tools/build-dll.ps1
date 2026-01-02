# Build script for the Civ V DLL
# Usage: .\tools\build-dll.ps1 [Debug|Release]

param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Release",
    
    [ValidateSet("v120", "v142", "v143")]
    [string]$PlatformToolset = "v143"
)

$ErrorActionPreference = "Stop"

# Find MSBuild
$msbuildPaths = @(
    "${env:ProgramFiles}\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe",
    "${env:ProgramFiles}\Microsoft Visual Studio\2022\Professional\MSBuild\Current\Bin\MSBuild.exe",
    "${env:ProgramFiles}\Microsoft Visual Studio\2022\Enterprise\MSBuild\Current\Bin\MSBuild.exe",
    "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2019\Community\MSBuild\Current\Bin\MSBuild.exe",
    "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2017\Community\MSBuild\15.0\Bin\MSBuild.exe"
)

$msbuild = $null
foreach ($path in $msbuildPaths) {
    if (Test-Path $path) {
        $msbuild = $path
        break
    }
}

if (-not $msbuild) {
    Write-Error "MSBuild not found. Please install Visual Studio 2017 or later."
    exit 1
}

Write-Host "Using MSBuild: $msbuild" -ForegroundColor Green
Write-Host "Building $Configuration configuration with toolset $PlatformToolset..." -ForegroundColor Cyan

$slnPath = Join-Path $PSScriptRoot "..\dll\CvGameCoreExpansion2.sln"

if (-not (Test-Path $slnPath)) {
    Write-Error "Solution file not found: $slnPath"
    exit 1
}

# Build the solution
& $msbuild $slnPath `
    /t:Build `
    /p:Configuration=$Configuration `
    /p:Platform=Win32 `
    /p:PlatformToolset=$PlatformToolset `
    /v:minimal

if ($LASTEXITCODE -eq 0) {
    # Check both possible output paths (project-specific and solution-level)
    $dllPath1 = Join-Path $PSScriptRoot "..\dll\CvGameCoreExpansion2\bin\Win32\$Configuration\CvGameCore_Expansion2.dll"
    $dllPath2 = Join-Path $PSScriptRoot "..\dll\bin\Win32\$Configuration\CvGameCore_Expansion2.dll"
    $dllPaths = @($dllPath1, $dllPath2)
    
    $dllPath = $null
    foreach ($path in $dllPaths) {
        if (Test-Path $path) {
            $dllPath = $path
            break
        }
    }
    
    if ($dllPath) {
        Write-Host "`nBuild succeeded! DLL output: $dllPath" -ForegroundColor Green
        Get-Item $dllPath | Select-Object FullName, Length, LastWriteTime
    } else {
        Write-Warning "Build reported success but DLL not found. Checked paths:"
        $dllPaths | ForEach-Object { Write-Host "  - $_" }
    }
} else {
    Write-Error "Build failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

