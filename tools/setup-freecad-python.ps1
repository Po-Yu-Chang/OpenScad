# FreeCAD Python Package Setup Script
# This script installs required packages for cad-worker using FreeCAD's bundled Python

# Define paths
$FreeCADPath = "FreeCAD\FreeCAD_1.1.1-Windows-x86_64-py311\bin\python.exe"
$PythonExe = Resolve-Path -Path $FreeCADPath -ErrorAction Stop

# Required packages
$Packages = @(
    "build123d",
    "fastapi",
    "uvicorn",
    "pydantic",
    "trimesh",
    "numpy",
    "pytest",
    "httpx",
    "cadquery-ocp-novtk"
)

Write-Host "Using FreeCAD Python: $PythonExe" -ForegroundColor Green
Write-Host "Required packages: $($Packages -join ', ')" -ForegroundColor Green

# Function to check if a package is installed
function Test-PackageInstalled {
    param (
        [string]$PackageName
    )
    
    $result = & $PythonExe -m pip show $PackageName 2>$null
    return ($null -ne $result -and $result.Length -gt 0)
}

# Function to get package version
function Get-PackageVersion {
    param (
        [string]$PackageName
    )
    
    $result = & $PythonExe -m pip show $PackageName 2>$null
    if ($null -ne $result -and $result.Length -gt 0) {
        $versionLine = $result | Select-String "^Version:"
        if ($versionLine) {
            return $versionLine.ToString().Replace("Version: ", "").Trim()
        }
    }
    return "Unknown"
}

# Install packages
$InstalledPackages = @()
$AlreadyInstalledPackages = @()

foreach ($package in $Packages) {
    if (Test-PackageInstalled -PackageName $package) {
        $version = Get-PackageVersion -PackageName $package
        $AlreadyInstalledPackages += "$package ($version)"
        Write-Host "$package is already installed (version: $version)" -ForegroundColor Yellow
    } else {
        Write-Host "Installing $package..." -ForegroundColor Cyan
        & $PythonExe -m pip install $package --quiet
        if ($LASTEXITCODE -eq 0) {
            $version = Get-PackageVersion -PackageName $package
            $InstalledPackages += "$package ($version)"
            Write-Host "$package installed successfully (version: $version)" -ForegroundColor Green
        } else {
            Write-Host "Failed to install $package" -ForegroundColor Red
        }
    }
}

# Output installed packages
Write-Host "`n=== Package Installation Summary ===" -ForegroundColor Green
if ($InstalledPackages.Count -gt 0) {
    Write-Host "Newly installed packages:" -ForegroundColor Green
    $InstalledPackages | ForEach-Object { Write-Host "  $_" -ForegroundColor Green }
} else {
    Write-Host "No new packages were installed." -ForegroundColor Yellow
}

if ($AlreadyInstalledPackages.Count -gt 0) {
    Write-Host "Already installed packages:" -ForegroundColor Yellow
    $AlreadyInstalledPackages | ForEach-Object { Write-Host "  $_" -ForegroundColor Yellow }
}

# Get all package versions for documentation
Write-Host "`n=== All Package Versions ===" -ForegroundColor Green
$AllPackages = @()
$Packages | ForEach-Object {
    if (Test-PackageInstalled -PackageName $_) {
        $version = Get-PackageVersion -PackageName $_
        $AllPackages += "$_==$version"
        Write-Host "$_==$version" -ForegroundColor White
    } else {
        $AllPackages += "$_==Not Installed"
        Write-Host "$_==Not Installed" -ForegroundColor Red
    }
}

# Get disk usage
$DiskUsage = (Get-ChildItem -Path "FreeCAD" -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB
$DiskUsageFormatted = "{0:N2} MB" -f $DiskUsage

# Create/update packaging notes
$NotesPath = "FreeCAD_Packaging_Notes.md"
$Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

$NotesContent = @"
# FreeCAD Packaging Notes

## Package Versions
Last updated: $Timestamp

$($AllPackages | ForEach-Object { "- $_" } | Out-String)

## Disk Usage
- Total size: $DiskUsageFormatted

## Installation Log
- Script executed on: $Timestamp
- Packages newly installed: $($InstalledPackages.Count)
- Packages already present: $($AlreadyInstalledPackages.Count)
"@

Set-Content -Path $NotesPath -Value $NotesContent

Write-Host "`nPackaging notes saved to: $NotesPath" -ForegroundColor Green
Write-Host "Total disk usage: $DiskUsageFormatted" -ForegroundColor Green