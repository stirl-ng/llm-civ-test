<#
.SYNOPSIS
    Builds the Community Patch DLL and deploys it to the Civ V MODS folder.

.PARAMETER Configuration
    Build configuration: Debug or Release (default: Release)

.PARAMETER DeployOnly
    Skip build, just deploy existing files

.EXAMPLE
    .\tools\build-and-deploy.ps1
    .\tools\build-and-deploy.ps1 -Configuration Debug
    .\tools\build-and-deploy.ps1 -DeployOnly
#>

param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Release",
    [switch]$DeployOnly
)

$ErrorActionPreference = "Stop"

# Paths (dynamic, no hardcoded username)
$RepoRoot = Split-Path -Parent $PSScriptRoot
$CppDll = Join-Path $RepoRoot "Community-Patch-DLL"
$Solution = Join-Path $CppDll "VoxPopuli_vs2013.sln"
$BuildOutput = Join-Path $CppDll "BuildOutput\$Configuration\CvGameCore_Expansion2.dll"
$ModSource = Join-Path $CppDll "(1) Community Patch"
$ModDest = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "My Games\Sid Meier's Civilization 5\MODS\(1) Community Patch"
$LogFile = Join-Path $env:LOCALAPPDATA "LLMCiv\llmbridge.log"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Community Patch Build & Deploy" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Configuration: $Configuration"
Write-Host "Mod destination: $ModDest"
Write-Host ""

# Find MSBuild
function Find-MSBuild {
    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path $vswhere) {
        $msbuild = & $vswhere -latest -requires Microsoft.Component.MSBuild -find MSBuild\**\Bin\MSBuild.exe | Select-Object -First 1
        if ($msbuild) { return $msbuild }
    }
    throw "MSBuild not found. Install Visual Studio with C++ workload."
}

# Build
if (-not $DeployOnly) {
    Write-Host "Building DLL..." -ForegroundColor Yellow
    $msbuild = Find-MSBuild

    & $msbuild $Solution /t:Build /p:Configuration=$Configuration /p:Platform=Win32 /v:minimal /nologo

    if ($LASTEXITCODE -ne 0) {
        throw "Build failed!"
    }
    Write-Host "  Build OK" -ForegroundColor Green
}

# Clear logs
Write-Host "Clearing logs..." -ForegroundColor Yellow
if (Test-Path $LogFile) {
    Remove-Item $LogFile -Force
    Write-Host "  Cleared: $LogFile" -ForegroundColor Green
} else {
    Write-Host "  No log file found" -ForegroundColor Gray
}

# Copy DLL to mod source folder
Write-Host "Updating DLL in mod folder..." -ForegroundColor Yellow
if (Test-Path $BuildOutput) {
    Copy-Item $BuildOutput -Destination $ModSource -Force
    Write-Host "  Copied DLL to mod source" -ForegroundColor Green
} else {
    throw "DLL not found at: $BuildOutput"
}

# Deploy mod folder
Write-Host "Deploying mod to Civ V..." -ForegroundColor Yellow
if (Test-Path $ModDest) {
    Remove-Item $ModDest -Recurse -Force
}
Copy-Item $ModSource -Destination $ModDest -Recurse -Force
Write-Host "  Deployed to: $ModDest" -ForegroundColor Green

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Done! Launch Civ V and enable the mod." -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
