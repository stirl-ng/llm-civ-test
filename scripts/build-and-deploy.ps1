<#
.SYNOPSIS
    Builds the Community Patch DLL and deploys it to the Civ V MODS folder.

.PARAMETER Configuration
    Build configuration: Debug or Release (default: Release)

.PARAMETER DeployOnly
    Skip build, just deploy existing files

.PARAMETER NoClear
    Don't clear log files

.EXAMPLE
    .\scripts\build-and-deploy.ps1
    .\scripts\build-and-deploy.ps1 -Configuration Debug
    .\scripts\build-and-deploy.ps1 -DeployOnly
#>

param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Release",
    [switch]$DeployOnly,
    [switch]$NoClear
)

$ErrorActionPreference = "Stop"

# Paths (dynamic, no hardcoded username)
$RepoRoot = Split-Path -Parent $PSScriptRoot
$CppDll = Join-Path $RepoRoot "Community-Patch-DLL"
$Solution = Join-Path $CppDll "VoxPopuli_vs2013.sln"
$ModSource = Join-Path $CppDll "(1) Community Patch"
$ModDest = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "My Games\Sid Meier's Civilization 5\MODS\(1) Community Patch"
$LogDir = Join-Path $RepoRoot "python\logs"

# Possible DLL output locations (MSBuild may vary)
$PossibleDllPaths = @(
    (Join-Path $CppDll "BuildOutput\$Configuration\CvGameCore_Expansion2.dll"),
    (Join-Path $CppDll "$Configuration\CvGameCore_Expansion2.dll"),
    (Join-Path $CppDll "Mod\CvGameCore_Expansion2.dll")
)

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Community Patch Build & Deploy" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Configuration: $Configuration"
Write-Host "Mod source:    $ModSource"
Write-Host "Mod dest:      $ModDest"
Write-Host ""

# Find MSBuild
function Find-MSBuild {
    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path $vswhere) {
        $msbuild = & $vswhere -latest -requires Microsoft.Component.MSBuild -find MSBuild\**\Bin\MSBuild.exe | Select-Object -First 1
        if ($msbuild) { return $msbuild }
    }
    # Fallback to common locations
    $fallbacks = @(
        "${env:ProgramFiles}\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe",
        "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2019\Community\MSBuild\Current\Bin\MSBuild.exe"
    )
    foreach ($fb in $fallbacks) {
        if (Test-Path $fb) { return $fb }
    }
    throw "MSBuild not found. Install Visual Studio with C++ workload."
}

# Find the built DLL
function Find-BuiltDll {
    foreach ($path in $PossibleDllPaths) {
        if (Test-Path $path) {
            return $path
        }
    }
    return $null
}

# Build
if (-not $DeployOnly) {
    Write-Host "Building DLL..." -ForegroundColor Yellow
    $msbuild = Find-MSBuild
    Write-Host "  Using MSBuild: $msbuild" -ForegroundColor Gray

    & $msbuild $Solution /t:Build /p:Configuration=$Configuration /p:Platform=Win32 /v:minimal /nologo

    if ($LASTEXITCODE -ne 0) {
        throw "Build failed!"
    }
    Write-Host "  Build OK" -ForegroundColor Green

    # Find and copy DLL to mod source folder
    Write-Host "Locating built DLL..." -ForegroundColor Yellow
    $BuiltDll = Find-BuiltDll
    if ($BuiltDll) {
        Write-Host "  Found: $BuiltDll" -ForegroundColor Gray
        Copy-Item $BuiltDll -Destination $ModSource -Force
        Write-Host "  Copied DLL to mod source" -ForegroundColor Green
    } else {
        Write-Host "  WARNING: DLL not found in expected locations. Searched:" -ForegroundColor Yellow
        foreach ($path in $PossibleDllPaths) {
            Write-Host "    - $path" -ForegroundColor Gray
        }
        Write-Host "  Continuing with existing DLL in mod folder..." -ForegroundColor Yellow
    }
}

# Clear logs
if (-not $NoClear) {
    Write-Host "Clearing logs..." -ForegroundColor Yellow
    $cleared = $false

    # Clear orchestrator logs
    if (Test-Path $LogDir) {
        Get-ChildItem $LogDir -Filter "*.jsonl" | ForEach-Object {
            Remove-Item $_.FullName -Force
            Write-Host "  Cleared: $($_.Name)" -ForegroundColor Green
            $cleared = $true
        }
    }

    # Clear old log location
    $OldLogFile = Join-Path $env:LOCALAPPDATA "LLMCiv\llmbridge.log"
    if (Test-Path $OldLogFile) {
        Remove-Item $OldLogFile -Force
        Write-Host "  Cleared: llmbridge.log" -ForegroundColor Green
        $cleared = $true
    }

    if (-not $cleared) {
        Write-Host "  No log files found" -ForegroundColor Gray
    }
}

# Deploy mod folder
Write-Host "Deploying mod to Civ V..." -ForegroundColor Yellow
if (Test-Path $ModDest) {
    Remove-Item $ModDest -Recurse -Force
    Write-Host "  Removed old mod folder" -ForegroundColor Gray
}
Copy-Item $ModSource -Destination $ModDest -Recurse -Force
Write-Host "  Deployed to: $ModDest" -ForegroundColor Green

# Show DLL info
$DeployedDll = Join-Path $ModDest "CvGameCore_Expansion2.dll"
if (Test-Path $DeployedDll) {
    $dllInfo = Get-Item $DeployedDll
    Write-Host "  DLL size: $([math]::Round($dllInfo.Length / 1MB, 2)) MB" -ForegroundColor Gray
    Write-Host "  DLL date: $($dllInfo.LastWriteTime)" -ForegroundColor Gray
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Done! Launch Civ V and enable the mod." -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
