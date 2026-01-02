# Build script for the Civ V DLL using MSBuild
# Usage: .\tools\build.ps1 [Debug|Release]

param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Release",
    
    [ValidateSet("Win32", "x64")]
    [string]$Platform = "Win32",
    
    [string]$PlatformToolset = "v143"
)

$ErrorActionPreference = "Stop"

# Find MSBuild
$msbuildPaths = @(
    "${env:ProgramFiles}\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe",
    "${env:ProgramFiles}\Microsoft Visual Studio\2022\Professional\MSBuild\Current\Bin\MSBuild.exe",
    "${env:ProgramFiles}\Microsoft Visual Studio\2022\Enterprise\MSBuild\Current\Bin\MSBuild.exe",
    "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2019\Community\MSBuild\Current\Bin\MSBuild.exe",
    "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2019\Professional\MSBuild\Current\Bin\MSBuild.exe",
    "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2019\Enterprise\MSBuild\Current\Bin\MSBuild.exe"
)

$msbuild = $null
foreach ($path in $msbuildPaths) {
    if (Test-Path $path) {
        $msbuild = $path
        break
    }
}

if (-not $msbuild) {
    Write-Error "MSBuild not found. Please install Visual Studio 2019 or 2022."
    exit 1
}

Write-Host "Using MSBuild: $msbuild" -ForegroundColor Green
Write-Host "Building: $Configuration | $Platform" -ForegroundColor Cyan

$solutionPath = Join-Path $PSScriptRoot "..\dll\CvGameCoreExpansion2.sln"

if (-not (Test-Path $solutionPath)) {
    Write-Error "Solution file not found: $solutionPath"
    exit 1
}

# Build
& $msbuild $solutionPath `
    /t:Build `
    /p:Configuration=$Configuration `
    /p:Platform=$Platform `
    /p:PlatformToolset=$PlatformToolset `
    /v:minimal

if ($LASTEXITCODE -ne 0) {
    Write-Error "Build failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

$dllPath = Join-Path $PSScriptRoot "..\dll\bin\$Platform\$Configuration\CvGameCore_Expansion2.dll"
if (Test-Path $dllPath) {
    Write-Host "`nBuild succeeded! DLL: $dllPath" -ForegroundColor Green
    $dllInfo = Get-Item $dllPath
    Write-Host "Size: $($dllInfo.Length) bytes" -ForegroundColor Gray
    Write-Host "Modified: $($dllInfo.LastWriteTime)" -ForegroundColor Gray
} else {
    Write-Warning "Build reported success but DLL not found at expected path: $dllPath"
}

