<#
.SYNOPSIS
    Builds the LLM Bridge DLL and deploys it to the Civ V mod folder.

.PARAMETER Configuration
    Build configuration: Debug or Release (default: Release)

.PARAMETER SkipHarness
    Skip building the test harness

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
    [switch]$SkipHarness,
    [switch]$DeployOnly
)

$ErrorActionPreference = "Stop"

# Paths
$RepoRoot = Split-Path -Parent $PSScriptRoot
$DllProject = Join-Path $RepoRoot "dll\CvGameCoreExpansion2\CvGameCoreExpansion2.vcxproj"
$HarnessProject = Join-Path $RepoRoot "dll\LLMBridgeHarness\LLMBridgeHarness.vcxproj"
$DllOutput = Join-Path $RepoRoot "dll\CvGameCoreExpansion2\bin\Win32\$Configuration\CvGameCore_Expansion2.dll"
$HarnessOutput = Join-Path $RepoRoot "dll\LLMBridgeHarness\bin\Win32\$Configuration\LLMBridgeHarness.exe"
$LogFile = Join-Path $env:LOCALAPPDATA "LLMCiv\llmbridge.log"

# Civ V mod folder - adjust this path as needed
# Option 1: MODS folder (for packaged mods)
# $ModFolder = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "My Games\Sid Meier's Civilization 5\MODS\LLMBridge"
# Option 2: Direct DLL replacement (requires backup of original)
# $ModFolder = "C:\Program Files (x86)\Steam\steamapps\common\Sid Meier's Civilization V\Assets\DLC\Expansion2\Gameplay"

# For now, deploy to a local 'deploy' folder - update this to your actual mod location
$ModFolder = Join-Path $RepoRoot "deploy"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "LLM Bridge Build & Deploy Script" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Configuration: $Configuration"
Write-Host "Deploy folder: $ModFolder"
Write-Host ""

# Find MSBuild
function Find-MSBuild {
    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path $vswhere) {
        $msbuild = & $vswhere -latest -requires Microsoft.Component.MSBuild -find MSBuild\**\Bin\MSBuild.exe | Select-Object -First 1
        if ($msbuild) { return $msbuild }
    }

    # Fallback paths
    $fallbacks = @(
        "C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe",
        "C:\Program Files\Microsoft Visual Studio\2022\Professional\MSBuild\Current\Bin\MSBuild.exe",
        "C:\Program Files\Microsoft Visual Studio\2022\Enterprise\MSBuild\Current\Bin\MSBuild.exe"
    )
    foreach ($fb in $fallbacks) {
        if (Test-Path $fb) { return $fb }
    }

    throw "MSBuild not found. Install Visual Studio 2022 with C++ workload."
}

# Build function
function Build-Project {
    param([string]$ProjectPath, [string]$Name)

    Write-Host "Building $Name..." -ForegroundColor Yellow
    $msbuild = Find-MSBuild

    & $msbuild $ProjectPath /t:Rebuild /p:Configuration=$Configuration /p:Platform=Win32 /v:minimal /nologo

    if ($LASTEXITCODE -ne 0) {
        throw "Build failed for $Name"
    }
    Write-Host "  OK" -ForegroundColor Green
}

# Clear logs
function Clear-Logs {
    Write-Host "Clearing logs..." -ForegroundColor Yellow

    if (Test-Path $LogFile) {
        Remove-Item $LogFile -Force
        Write-Host "  Cleared: $LogFile" -ForegroundColor Green
    } else {
        Write-Host "  No log file found" -ForegroundColor Gray
    }
}

# Deploy files
function Deploy-Files {
    Write-Host "Deploying files..." -ForegroundColor Yellow

    # Create mod folder if needed
    if (-not (Test-Path $ModFolder)) {
        New-Item -ItemType Directory -Path $ModFolder -Force | Out-Null
        Write-Host "  Created: $ModFolder" -ForegroundColor Green
    }

    # Copy DLL
    if (Test-Path $DllOutput) {
        Copy-Item $DllOutput -Destination $ModFolder -Force
        Write-Host "  Copied: CvGameCore_Expansion2.dll" -ForegroundColor Green
    } else {
        Write-Host "  WARNING: DLL not found at $DllOutput" -ForegroundColor Red
    }

    # Copy harness (optional, for testing)
    if (Test-Path $HarnessOutput) {
        Copy-Item $HarnessOutput -Destination $ModFolder -Force
        Write-Host "  Copied: LLMBridgeHarness.exe" -ForegroundColor Green
    }

    # Copy PDB for debugging (optional)
    $PdbOutput = $DllOutput -replace '\.dll$', '.pdb'
    if (Test-Path $PdbOutput) {
        Copy-Item $PdbOutput -Destination $ModFolder -Force
        Write-Host "  Copied: CvGameCore_Expansion2.pdb" -ForegroundColor Green
    }
}

# Main
try {
    if (-not $DeployOnly) {
        Build-Project $DllProject "CvGameCore_Expansion2.dll"

        if (-not $SkipHarness) {
            Build-Project $HarnessProject "LLMBridgeHarness.exe"
        }
    }

    Clear-Logs
    Deploy-Files

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Build & Deploy Complete!" -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Deployed to: $ModFolder"
    Write-Host ""
    Write-Host "To test:"
    Write-Host "  .\deploy\LLMBridgeHarness.exe --state"
    Write-Host ""

} catch {
    Write-Host ""
    Write-Host "ERROR: $_" -ForegroundColor Red
    exit 1
}
