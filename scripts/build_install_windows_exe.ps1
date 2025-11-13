# build_install_windows_exe.ps1 - helper to compile install_windows.ps1 into an EXE
[CmdletBinding()]
param(
    # Directory that contains install_windows.ps1 and the EDMC-ModernOverlay payload folder.
    [string]$StagingPath = (Get-Location).Path
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Fail {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
    Write-Host "Hint: run this script from the release staging directory (where install_windows.ps1 and the EDMC-ModernOverlay folder live) or pass -StagingPath <path>."
    exit 1
}

function Resolve-StagingPath {
    param([string]$Path)
    try {
        return (Resolve-Path -LiteralPath $Path).ProviderPath
    } catch {
        Fail "Staging path '$Path' was not found."
    }
}

$resolvedStaging = Resolve-StagingPath -Path $StagingPath
$installScript = Join-Path $resolvedStaging 'install_windows.ps1'
if (-not (Test-Path -LiteralPath $installScript)) {
    Fail "install_windows.ps1 was not found at '$installScript'."
}

$payloadDir = Join-Path $resolvedStaging 'EDMC-ModernOverlay'
if (-not (Test-Path -LiteralPath $payloadDir -PathType Container)) {
    Fail "The EDMC-ModernOverlay directory was not found at '$payloadDir'."
}

$versionFile = Join-Path $payloadDir 'version.py'
if (-not (Test-Path -LiteralPath $versionFile)) {
    Fail "Could not find version.py at '$versionFile'. Ensure the EDMC-ModernOverlay payload is present."
}

$version = Get-Content -LiteralPath $versionFile |
    Select-String -Pattern '\d+\.\d+\.\d+(?:-[A-Za-z0-9]+)?' |
    ForEach-Object { $_.Matches.Value } |
    Select-Object -First 1

if (-not $version) {
    Fail "Failed to parse a version number from '$versionFile'."
}

$outputExe = Join-Path $resolvedStaging 'install_windows.exe'
Write-Host "Compiling installer:"
Write-Host "  Source : $installScript"
Write-Host "  Output : $outputExe"
Write-Host "  Version: $version"

Invoke-ps2exe `
    -InputFile $installScript `
    -OutputFile $outputExe `
    -Title "EDMC Modern Overlay Installer" `
    -Description "Installs the EDMC Modern Overlay plugin next to EDMC." `
    -Version $version

Write-Host "install_windows.exe has been generated at '$outputExe'."
