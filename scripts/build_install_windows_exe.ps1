# build_install_windows_exe.ps1 - helper to compile install_windows.ps1 into an EXE
[CmdletBinding()]
param(
    # Directory that contains install_windows.ps1.
    [string]$StagingPath = (Get-Location).Path
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Fail {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
    Write-Host "Hint: run this script from the release staging directory (where install_windows.ps1 lives) or pass -StagingPath <path>."
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

$outputExe = Join-Path $resolvedStaging 'install_windows.exe'
Write-Host "Compiling installer:"
Write-Host "  Source : $installScript"
Write-Host "  Output : $outputExe"

Invoke-ps2exe `
    -InputFile $installScript `
    -OutputFile $outputExe `
    -Title "EDMC Modern Overlay Installer" `
    -Description "Installs the EDMC Modern Overlay plugin next to EDMC."

Write-Host "install_windows.exe has been generated at '$outputExe'."
