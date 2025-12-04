# install_windows.ps1 - helper to deploy EDMC Modern Overlay on Windows.
<#
.SYNOPSIS
Deploys or updates the EDMC Modern Overlay plugin inside the EDMarketConnector plugins directory.

.DESCRIPTION
The script mirrors the workflow used by install_linux.sh:
1. Detect (or prompt for) the EDMC plugins directory.
2. Ensure EDMarketConnector is not running.
3. Disable legacy EDMCOverlay plugins.
4. Disable any existing EDMC-ModernOverlay installation by renaming it to EDMC-ModernOverlay.disabled (or .N.disabled).
5. Copy the EDMCModernOverlay payload alongside this script into the plugins directory.
6. Create overlay_client\.venv (or reuse an existing one) and install requirements.
7. Optionally download the Eurocaps font for the authentic Elite Dangerous HUD look.

.PARAMETER PluginDir
Overrides the detected EDMarketConnector plugins directory.

.PARAMETER AssumeYes
Automatically answer "yes" to prompts.

.PARAMETER DryRun
Print the actions that would be performed without making any changes.
#>

[CmdletBinding()]
param(
    [string]$PluginDir,
    [switch]$AssumeYes,
    [switch]$DryRun
)

$script:MinimumPSVersion = [Version]'3.0'
$script:CurrentPSVersion = $PSVersionTable.PSVersion

if ($script:CurrentPSVersion -lt $script:MinimumPSVersion) {
    Write-Host "[ERROR] This installer requires PowerShell $MinimumPSVersion or newer. Detected version: $CurrentPSVersion" -ForegroundColor Red
    Write-Host "Please install Windows Management Framework 5.1 (or PowerShell 7+) and rerun the installer."
    try {
        Read-Host "Press Enter to exit..." | Out-Null
    } catch {
        Write-Host "No console available; closing automatically in 5 seconds..."
        Start-Sleep -Seconds 5
    }
    exit 1
}

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:EmbeddedPayloadBase64 = $null # EMBEDDED_PAYLOAD_PLACEHOLDER
$script:EmbeddedPayloadTempRoot = $null

function Resolve-ScriptDirectory {
    # Determine script location even when compiled to an EXE (PSCommandPath becomes empty there).
    $candidates = @()
    if (Test-Path variable:PSCommandPath) {
        if (-not [string]::IsNullOrWhiteSpace($PSCommandPath)) {
            $candidates += (Split-Path -Parent $PSCommandPath)
        }
    }
    if ($MyInvocation -and $MyInvocation.MyCommand) {
        $pathProp = $MyInvocation.MyCommand.PSObject.Properties['Path']
        if ($pathProp -and -not [string]::IsNullOrWhiteSpace($pathProp.Value)) {
            $candidates += (Split-Path -Parent $pathProp.Value)
        }
    }
    if (Test-Path variable:PSScriptRoot) {
        if (-not [string]::IsNullOrWhiteSpace($PSScriptRoot)) {
            $candidates += $PSScriptRoot
        }
    }
    $candidates += [System.AppContext]::BaseDirectory

    foreach ($candidate in $candidates) {
        if ([string]::IsNullOrWhiteSpace($candidate)) {
            continue
        }
        try {
            if (Test-Path -LiteralPath $candidate) {
                return (Get-Item -LiteralPath $candidate).FullName
            }
        } catch {
            continue
        }
    }

    return [System.AppContext]::BaseDirectory
}

$ScriptDir = Resolve-ScriptDirectory
$ReleaseRoot = $null
$PayloadDir = $null
$PythonSpec = $null
$FontUrl = 'https://raw.githubusercontent.com/inorton/EDMCOverlay/master/EDMCOverlay/EDMCOverlay/EUROCAPS.TTF'
$FontName = 'Eurocaps.ttf'
$ModernPluginDirName = 'EDMCModernOverlay'
$LegacyPluginDirName = 'EDMC-ModernOverlay'

function Show-BreakingChangeWarning {
    Write-Warn 'Breaking upgrade notice: Modern Overlay now installs under the EDMCModernOverlay directory.'
    Write-Warn "Any existing $LegacyPluginDirName folder will be renamed to $LegacyPluginDirName.disabled (or .N.disabled) before installation."
    Write-Warn 'Settings are not migrated automatically; re-enable the prior plugin manually if needed.'
}

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message"
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-ErrorLine {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

function Wait-ForShellExtraction {
    param(
        [Parameter(Mandatory=$true)][string]$MonitorPath,
        [int]$TimeoutSeconds = 120
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastCount = -1
    $stableReads = 0
    while ((Get-Date) -lt $deadline) {
        if (-not (Test-Path -LiteralPath $MonitorPath)) {
            Start-Sleep -Milliseconds 250
            continue
        }

        $count = (Get-ChildItem -LiteralPath $MonitorPath -Recurse -Force -ErrorAction SilentlyContinue | Measure-Object).Count
        if ($count -gt 0 -and $count -eq $lastCount) {
            $stableReads++
            if ($stableReads -ge 4) {
                return
            }
        } else {
            $stableReads = 0
            $lastCount = $count
        }

        Start-Sleep -Milliseconds 250
    }

    Write-Warn "Shell.Application extraction did not finish within $TimeoutSeconds seconds for '$MonitorPath'; continuing."
}

function Expand-ArchiveWithFallback {
    param(
        [Parameter(Mandatory=$true)][string]$LiteralPath,
        [Parameter(Mandatory=$true)][string]$DestinationPath,
        [string]$ExpectedRoot
    )

    $expandError = $null
    try {
        if (-not (Get-Command -Name Expand-Archive -ErrorAction SilentlyContinue)) {
            Import-Module -Name Microsoft.PowerShell.Archive -ErrorAction Stop | Out-Null
        }
        Expand-Archive -LiteralPath $LiteralPath -DestinationPath $DestinationPath -Force -ErrorAction Stop
        return
    } catch {
        $expandError = $_
        Write-Warn ("Expand-Archive unavailable or failed ({0}). Attempting Shell.Application fallback." -f $expandError.Exception.Message)
    }

    try {
        $shell = New-Object -ComObject Shell.Application
    } catch {
        Fail-Install ("Unable to extract '{0}'. Expand-Archive failed and Shell.Application could not be created: {1}" -f $LiteralPath, $_.Exception.Message)
    }

    if (-not (Test-Path -LiteralPath $DestinationPath)) {
        New-Item -ItemType Directory -Path $DestinationPath -Force | Out-Null
    }

    $zipNS = $shell.NameSpace($LiteralPath)
    if (-not $zipNS) {
        Fail-Install "Shell.Application could not open archive '$LiteralPath'."
    }
    $destNS = $shell.NameSpace($DestinationPath)
    if (-not $destNS) {
        Fail-Install "Shell.Application could not access destination '$DestinationPath'."
    }

    $copyFlags = 0x10 -bor 0x04 -bor 0x1000
    $destNS.CopyHere($zipNS.Items(), $copyFlags)

    if ($ExpectedRoot) {
        $monitor = Join-Path $DestinationPath $ExpectedRoot
        Wait-ForShellExtraction -MonitorPath $monitor
    } else {
        Start-Sleep -Seconds 2
    }
}

function Initialize-EmbeddedPayload {
    if ([string]::IsNullOrWhiteSpace($EmbeddedPayloadBase64)) {
        return
    }

    $tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("EDMCModernOverlay_{0}" -f ([guid]::NewGuid().ToString('N')))
    if (-not (Test-Path -LiteralPath $tempRoot)) {
        New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
    }

    $archivePath = Join-Path $tempRoot 'payload.zip'
    Write-Info "Extracting embedded payload to '$tempRoot'."
    [IO.File]::WriteAllBytes($archivePath, [Convert]::FromBase64String($EmbeddedPayloadBase64))
    Expand-ArchiveWithFallback -LiteralPath $archivePath -DestinationPath $tempRoot -ExpectedRoot $ModernPluginDirName
    Remove-Item -LiteralPath $archivePath -Force

    $expectedDir = Join-Path $tempRoot $ModernPluginDirName
    if (-not (Test-Path -LiteralPath $expectedDir)) {
        Fail-Install "Embedded payload missing '$ModernPluginDirName' directory."
    }

    $script:EmbeddedPayloadTempRoot = $tempRoot
}

function Cleanup-EmbeddedPayload {
    if (-not $EmbeddedPayloadTempRoot) {
        return
    }

    if (-not (Test-Path -LiteralPath $EmbeddedPayloadTempRoot)) {
        return
    }

    try {
        Remove-Item -LiteralPath $EmbeddedPayloadTempRoot -Recurse -Force -ErrorAction Stop
    } catch {
        Write-Warn "Failed to clean up temporary payload directory '$EmbeddedPayloadTempRoot'."
    }
}

function Fail-Install {
    param([string]$Message)
    throw (New-Object System.Exception($Message))
}

function Wait-ForExitConfirmation {
    param([string]$Prompt)

    $message = $Prompt
    try {
        Read-Host $message | Out-Null
        return
    } catch {
        # Fall through to console-based handling.
    }

    try {
        Write-Host $message
        [void][System.Console]::ReadLine()
        return
    } catch {
        # No console available (e.g., PS2EXE without console). Give the user a moment to read the message.
        Write-Host "$message (auto-closing in 5 seconds...)"
        Start-Sleep -Seconds 5
    }
}

function Prompt-YesNo {
    param(
        [string]$Message = 'Continue?',
        [bool]$Default = $true
    )

    if ($AssumeYes) {
        Write-Info "$Message [auto-yes]"
        return $true
    }

    $suffix = if ($Default) { 'Y/n' } else { 'y/N' }
    while ($true) {
        $response = Read-Host "$Message [$suffix]"
        if ([string]::IsNullOrWhiteSpace($response)) {
            return $Default
        }
        switch -Regex ($response.Trim()) {
            '^(y|yes)$' { return $true }
            '^(n|no)$' { return $false }
            default {
                Write-Warn 'Please answer yes or no.'
            }
        }
    }
}

function Normalize-Path {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $null
    }
    try {
        if (Test-Path -LiteralPath $Path) {
            return (Get-Item -LiteralPath $Path).FullName
        }
        $parent = Split-Path -Parent $Path
        if (-not [string]::IsNullOrWhiteSpace($parent) -and (Test-Path -LiteralPath $parent)) {
            $leaf = Split-Path -Leaf $Path
            return Join-Path (Get-Item -LiteralPath $parent).FullName $leaf
        }
        return [IO.Path]::GetFullPath($Path)
    } catch {
        return $Path
    }
}

function Ensure-Directory {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path) {
        return
    }
    if ($DryRun) {
        Write-Info "[dry-run] Would create directory '$Path'."
        return
    }
    Write-Info "Creating directory '$Path'."
    New-Item -ItemType Directory -Path $Path -Force | Out-Null
}

function Find-ReleaseRoot {
    if ($EmbeddedPayloadTempRoot) {
        $payloadPath = Join-Path $EmbeddedPayloadTempRoot $ModernPluginDirName
        if (Test-Path -LiteralPath $payloadPath) {
            return (Get-Item -LiteralPath $EmbeddedPayloadTempRoot).FullName
        }
        Write-Warn "Embedded payload directory missing expected content, falling back to disk-based payload."
    }

    if (Test-Path -LiteralPath (Join-Path $ScriptDir $ModernPluginDirName)) {
        return (Get-Item -LiteralPath $ScriptDir).FullName
    }

    $parent = Split-Path -Parent $ScriptDir
    if (-not [string]::IsNullOrWhiteSpace($parent) -and
        (Test-Path -LiteralPath (Join-Path $parent $ModernPluginDirName))) {
        return (Get-Item -LiteralPath $parent).FullName
    }

    Fail-Install "Could not find '$ModernPluginDirName' directory alongside install_windows.ps1."
}

function Get-DefaultPluginRoot {
    if ($env:LOCALAPPDATA) {
        return Join-Path $env:LOCALAPPDATA 'EDMarketConnector\plugins'
    }
    return Join-Path $env:USERPROFILE 'AppData\Local\EDMarketConnector\plugins'
}

function Detect-PluginRoot {
    if ($PluginDir) {
        $normalized = Normalize-Path $PluginDir
        Write-Info "Using plugin directory override: $normalized"
        if (-not (Test-Path -LiteralPath $normalized)) {
            if (Prompt-YesNo -Message "Directory '$normalized' does not exist. Create it?" -Default:$true) {
                Ensure-Directory $normalized
            } else {
                Fail-Install 'Installation requires a valid plugin directory.'
            }
        }
        return $normalized
    }

    $defaultPath = Normalize-Path (Get-DefaultPluginRoot)
    if (Test-Path -LiteralPath $defaultPath) {
        if (Prompt-YesNo -Message "Detected EDMC plugins directory at '$defaultPath'. Use it?" -Default:$true) {
            return $defaultPath
        }
    } else {
        Write-Warn "EDMC plugins directory not found at '$defaultPath'."
        if (Prompt-YesNo -Message "Create '$defaultPath'?" -Default:$true) {
            Ensure-Directory $defaultPath
            return $defaultPath
        }
    }

    while ($true) {
        $input = Read-Host 'Enter the path to your EDMC plugins directory'
        $normalized = Normalize-Path $input
        if ([string]::IsNullOrWhiteSpace($normalized)) {
            Write-Warn 'Path cannot be empty.'
            continue
        }
        if (Test-Path -LiteralPath $normalized) {
            return $normalized
        }
        if (Prompt-YesNo -Message "Directory '$normalized' does not exist. Create it?" -Default:$true) {
            Ensure-Directory $normalized
            return $normalized
        }
        Write-Warn 'Please provide a valid directory.'
    }
}

function Resolve-Python {
    $candidates = @(
        @{ Command = 'py'; Args = @('-3') },
        @{ Command = 'py'; Args = @() },
        @{ Command = 'python3'; Args = @() },
        @{ Command = 'python'; Args = @() }
    )

    foreach ($candidate in $candidates) {
        $cmd = Get-Command -Name $candidate.Command -ErrorAction SilentlyContinue
        if (-not $cmd) {
            continue
        }
        $checkArgs = @()
        if ($candidate.Args.Count -gt 0) {
            $checkArgs += $candidate.Args
        }
        $checkArgs += @('-c', 'import sys; sys.exit(0) if sys.version_info >= (3, 8) else sys.exit(1)')

        try {
            & $candidate.Command @checkArgs *> $null
            return [pscustomobject]@{
                Command    = $candidate.Command
                PrefixArgs = $candidate.Args
            }
        } catch {
            continue
        }
    }

    Fail-Install 'Python 3.8+ is required but was not found on PATH.'
}

function Ensure-EdmcNotRunning {
    $process = Get-Process -Name 'EDMarketConnector' -ErrorAction SilentlyContinue
    if (-not $process) {
        return
    }

    Write-Warn 'EDMarketConnector appears to be running.'
    if (-not (Prompt-YesNo -Message 'Close EDMarketConnector and continue?')) {
        Fail-Install 'Installation requires EDMarketConnector to be closed.'
    }

    Write-Info 'Waiting for EDMarketConnector to exit...'
    while (Get-Process -Name 'EDMarketConnector' -ErrorAction SilentlyContinue) {
        Start-Sleep -Seconds 2
    }
}

function Disable-ConflictingPlugins {
    param([string]$PluginRoot)

    $conflicts = Get-ChildItem -Path $PluginRoot -Directory -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -like 'EDMCOverlay*' -and $_.Name -notmatch '\.disabled$' -and $_.Name -notlike ("$ModernPluginDirName*")
    }

    if (-not $conflicts) {
        return
    }

    Write-Warn 'Found legacy overlay plugins that conflict with Modern Overlay:'
    $conflicts | ForEach-Object { Write-Warn " - $($_.FullName)" }

    if (-not (Prompt-YesNo -Message 'Disable the legacy overlay plugin(s)?')) {
        Fail-Install 'Cannot proceed while legacy overlay plugins are enabled.'
    }

    foreach ($item in $conflicts) {
        $target = "$($item.FullName).disabled"
        if (Test-Path -LiteralPath $target) {
            Write-Info "Legacy plugin '$($item.Name)' already disabled."
            continue
        }
        if ($DryRun) {
            Write-Info "[dry-run] Would rename '$($item.FullName)' to '$target'."
            continue
        }
        Rename-Item -LiteralPath $item.FullName -NewName ("$($item.Name).disabled")
        Write-Info "Disabled legacy plugin '$($item.Name)'."
    }
}

function Normalize-DisabledSuffixes {
    param(
        [Parameter(Mandatory = $true)][string]$PluginRoot,
        [Parameter(Mandatory = $true)][string]$PluginName
    )

    $basePath = Join-Path $PluginRoot $PluginName
    $candidates = Get-ChildItem -Path "$basePath.disabled.*" -Directory -ErrorAction SilentlyContinue
    if (-not $candidates) {
        return
    }

    Write-Info "Normalizing disabled $PluginName directories so they end with '.disabled'."
    foreach ($item in $candidates) {
        $prefixLength = ("$basePath.disabled.").Length
        if ($item.FullName.Length -le $prefixLength) {
            continue
        }
        $suffix = $item.FullName.Substring($prefixLength)
        if ([string]::IsNullOrWhiteSpace($suffix)) {
            continue
        }
        $target = "$basePath.$suffix.disabled"
        $targetLeaf = Split-Path -Path $target -Leaf
        if (Test-Path -LiteralPath $target) {
            Write-Warn "Skipping '$($item.Name)' because '$targetLeaf' already exists."
            continue
        }
        if ($DryRun) {
            Write-Info "[dry-run] Would rename '$($item.Name)' to '$targetLeaf'."
            continue
        }
        Rename-Item -LiteralPath $item.FullName -NewName $targetLeaf
        Write-Info "Renamed '$($item.Name)' to '$targetLeaf'."
    }
}

function Disable-LegacyModernOverlay {
    param([string]$PluginRoot)

    $legacyPath = Join-Path $PluginRoot $LegacyPluginDirName
    if (-not (Test-Path -LiteralPath $legacyPath)) {
        return
    }

    Write-Warn "Existing $LegacyPluginDirName installation detected. It will be disabled before deploying $ModernPluginDirName."
    $suffix = 0
    do {
        if ($suffix -eq 0) {
            $targetPath = "$legacyPath.disabled"
        } else {
            $targetPath = "$legacyPath.$suffix.disabled"
        }
        $suffix++
    } while (Test-Path -LiteralPath $targetPath)

    if ($DryRun) {
        Write-Info "[dry-run] Would rename '$legacyPath' to '$targetPath'."
        return
    }

    $targetName = Split-Path -Path $targetPath -Leaf
    Rename-Item -LiteralPath $legacyPath -NewName $targetName
    Write-Info "Legacy Modern Overlay disabled (moved to '$targetName')."
}

function Invoke-Python {
    param(
        [Parameter(Mandatory = $true)][pscustomobject]$Python,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    $args = @()
    if ($Python.PrefixArgs -and $Python.PrefixArgs.Count -gt 0) {
        $args += $Python.PrefixArgs
    }
    $args += $Arguments
    & $Python.Command @args
}

function Create-VenvAndInstall {
    param(
        [string]$TargetDir
    )

    $venvPath = Join-Path $TargetDir 'overlay_client\.venv'
    $requirements = Join-Path $TargetDir 'overlay_client\requirements.txt'

    if ($DryRun) {
        Write-Info "[dry-run] Would ensure Python virtual environment at '$venvPath' and install requirements from '$requirements'."
        return
    }

    if (-not (Test-Path -LiteralPath (Join-Path $TargetDir 'overlay_client'))) {
        Fail-Install "Missing overlay_client directory in '$TargetDir'."
    }

    $rebuildRequested = $false
    if (Test-Path -LiteralPath $venvPath) {
        Write-Info "Existing Python virtual environment detected at '$venvPath'."
        if (Prompt-YesNo -Message 'Rebuild the overlay_client virtual environment?' -Default:$true) {
            $rebuildRequested = $true
        }
    }

    if ($rebuildRequested) {
        Write-Info 'Removing existing virtual environment before rebuilding...'
        Remove-Item -LiteralPath $venvPath -Recurse -Force
    }

    if (-not (Test-Path -LiteralPath $venvPath)) {
        Write-Info "Creating Python virtual environment at '$venvPath'."
        Invoke-Python -Python $PythonSpec -Arguments @('-m', 'venv', $venvPath)
    }

    $venvPython = Join-Path $venvPath 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython)) {
        Fail-Install "Virtual environment at '$venvPath' is missing python.exe."
    }

    Write-Info 'Installing overlay client requirements (this may take a moment)...'
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -r $requirements
}

function Ensure-ExistingInstall {
    param([string]$InstallDir)
    Create-VenvAndInstall -TargetDir $InstallDir
}

function Copy-InitialInstall {
    param(
        [string]$SourceDir,
        [string]$PluginRoot
    )

    $dest = Join-Path $PluginRoot $ModernPluginDirName
    Write-Info "Copying Modern Overlay into '$PluginRoot'."
    if ($DryRun) {
        Write-Info "[dry-run] Would copy '$SourceDir' to '$dest'."
        return
    }
    Copy-Item -Path $SourceDir -Destination $PluginRoot -Recurse -Force
    Create-VenvAndInstall -TargetDir $dest
}

function Update-ExistingInstall {
    param(
        [string]$SourceDir,
        [string]$DestDir
    )

    if ($DryRun) {
        Write-Info "[dry-run] Would replace '$DestDir' with the payload from '$SourceDir' while preserving overlay_client\.venv and Eurocaps.ttf."
        return
    }

    $parent = Split-Path -Parent $DestDir
    if (-not (Test-Path -LiteralPath $parent)) {
        Fail-Install "Parent directory '$parent' not found while updating '$DestDir'."
    }

    $tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("edmc-overlay-backup-" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null

    $venvPath = Join-Path $DestDir 'overlay_client\.venv'
    $fontPath = Join-Path $DestDir 'overlay_client\fonts\Eurocaps.ttf'
    $userGroupingsPath = Join-Path $DestDir 'overlay_groupings.user.json'
    $venvBackup = $null
    $fontBackup = $null
    $userGroupingsBackup = $null

    try {
        if (Test-Path -LiteralPath $venvPath) {
            $venvBackup = Join-Path $tempRoot '.venv'
            Move-Item -LiteralPath $venvPath -Destination $venvBackup
        }
        if (Test-Path -LiteralPath $fontPath) {
            $fontBackup = Join-Path $tempRoot $FontName
            Copy-Item -LiteralPath $fontPath -Destination $fontBackup -Force
        }
        if (Test-Path -LiteralPath $userGroupingsPath) {
            $userGroupingsBackup = Join-Path $tempRoot 'overlay_groupings.user.json'
            Copy-Item -LiteralPath $userGroupingsPath -Destination $userGroupingsBackup -Force
        }

        if (Test-Path -LiteralPath $DestDir) {
            Remove-Item -LiteralPath $DestDir -Recurse -Force
        }

        Copy-Item -Path $SourceDir -Destination $parent -Recurse -Force

        if ($venvBackup) {
            $restoredVenv = Join-Path $DestDir 'overlay_client\.venv'
            Move-Item -LiteralPath $venvBackup -Destination $restoredVenv
        }
        if ($fontBackup) {
            $restoredFont = Join-Path $DestDir 'overlay_client\fonts\Eurocaps.ttf'
            Copy-Item -LiteralPath $fontBackup -Destination $restoredFont -Force
        }
        if ($userGroupingsBackup) {
            $restoredUser = Join-Path $DestDir 'overlay_groupings.user.json'
            Copy-Item -LiteralPath $userGroupingsBackup -Destination $restoredUser -Force
        }
    } finally {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Ensure-FontListEntry {
    param(
        [string]$FontFile,
        [string]$PreferredList
    )

    if (-not (Test-Path -LiteralPath $PreferredList)) {
        Write-Info "preferred_fonts.txt not found at '$PreferredList'. The overlay will still detect $FontFile automatically."
        return
    }

    $existing = Select-String -Path $PreferredList -Pattern "^(?i)$FontFile$" -Quiet -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Info "$FontFile already listed in preferred_fonts.txt."
        return
    }

    if ($DryRun) {
        Write-Info "[dry-run] Would append '$FontFile' to '$PreferredList'."
        return
    }

    Add-Content -Path $PreferredList -Value $FontFile
    Write-Info "Added $FontFile to preferred_fonts.txt."
}

function Download-File {
    param(
        [string]$Url,
        [string]$Destination
    )

    if ($DryRun) {
        Write-Info "[dry-run] Would download '$Url' to '$Destination'."
        return $true
    }

    try {
        Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing
        return $true
    } catch {
        Write-ErrorLine "Failed to download '$Url'. $_"
        return $false
    }
}

function Install-EurocapsFont {
    param([string]$FontsDir)

    $fontPath = Join-Path $FontsDir $FontName
    $preferred = Join-Path $FontsDir 'preferred_fonts.txt'

    Ensure-Directory -Path $FontsDir

    if ($DryRun) {
        Write-Info "[dry-run] Would install $FontName to '$fontPath'."
        Ensure-FontListEntry -FontFile $FontName -PreferredList $preferred
        return
    }

    $tmp = [IO.Path]::GetTempFileName()
    Write-Info "Downloading $FontName..."
    if (-not (Download-File -Url $FontUrl -Destination $tmp)) {
        Remove-Item -LiteralPath $tmp -ErrorAction SilentlyContinue
        return
    }

    if (-not (Test-Path -LiteralPath $tmp) -or ((Get-Item -LiteralPath $tmp).Length -eq 0)) {
        Remove-Item -LiteralPath $tmp -ErrorAction SilentlyContinue
        Fail-Install "Downloaded font file is empty. Aborting."
    }

    Copy-Item -Path $tmp -Destination $fontPath -Force
    Remove-Item -LiteralPath $tmp -ErrorAction SilentlyContinue
    Write-Info "Installed $FontName to '$fontPath'."
    Ensure-FontListEntry -FontFile $FontName -PreferredList $preferred
}

function Maybe-InstallEurocaps {
    param([string]$PluginHome)

    $fontsDir = Join-Path $PluginHome 'overlay_client\fonts'
    $fontPath = Join-Path $fontsDir $FontName

    if (-not (Test-Path -LiteralPath $fontsDir)) {
        Write-Info "Font directory '$fontsDir' not found; skipping Eurocaps installation."
        return
    }

    if (Test-Path -LiteralPath $fontPath) {
        Write-Info "$FontName already present; skipping download."
        return
    }

    Write-Info 'The Eurocaps cockpit font provides the authentic Elite Dangerous HUD look.'
    if (-not (Prompt-YesNo -Message "Download and install $FontName now?" -Default:$true)) {
        Write-Info 'Skipping Eurocaps font download.'
        return
    }
    if (-not (Prompt-YesNo -Message 'Confirm you already have a license to use the Eurocaps font.' -Default:$true)) {
        Write-Info 'Eurocaps installation cancelled because the license confirmation was declined.'
        return
    }

    Install-EurocapsFont -FontsDir $fontsDir
}

function Final-Notes {
    Write-Host ''
    Write-Info 'Installation steps completed.'
    Write-Info 'Re-run install_windows.ps1 any time you want to update the plugin or re-install the optional Eurocaps font.'
    if ($DryRun) {
        Write-Info 'Dry-run mode was enabled; no files were modified.'
    }
    if ($AssumeYes) {
        Write-Info 'Install finished. Exiting automatically because -AssumeYes was provided.'
    } else {
        Wait-ForExitConfirmation -Prompt 'Install finished. Press Enter to exit.'
    }
}

function Main {
    $script:ReleaseRoot = Find-ReleaseRoot
    Show-BreakingChangeWarning
    $script:PayloadDir = Join-Path $ReleaseRoot $ModernPluginDirName
    if (-not (Test-Path -LiteralPath $PayloadDir)) {
        Fail-Install "Source payload '$PayloadDir' not found."
    }

    $script:PythonSpec = Resolve-Python
    $pluginsRoot = Detect-PluginRoot
    Write-Info "Using EDMC plugins directory: $pluginsRoot"
    Ensure-Directory -Path $pluginsRoot

    Ensure-EdmcNotRunning
    Disable-ConflictingPlugins -PluginRoot $pluginsRoot
    Normalize-DisabledSuffixes -PluginRoot $pluginsRoot -PluginName $LegacyPluginDirName
    Normalize-DisabledSuffixes -PluginRoot $pluginsRoot -PluginName $ModernPluginDirName
    Disable-LegacyModernOverlay -PluginRoot $pluginsRoot

    $installDir = Join-Path $pluginsRoot $ModernPluginDirName

    if (-not (Test-Path -LiteralPath $installDir)) {
        Copy-InitialInstall -SourceDir $PayloadDir -PluginRoot $pluginsRoot
    } else {
        Write-Warn "Existing installation detected at '$installDir'."
        Write-Warn "Plugin files will be replaced; you'll be prompted whether to rebuild overlay_client\.venv afterwards."
        if (-not (Prompt-YesNo -Message 'Proceed with updating the installation?' -Default:$true)) {
            Fail-Install 'Installation aborted by user.'
        }
        Update-ExistingInstall -SourceDir $PayloadDir -DestDir $installDir
        Ensure-ExistingInstall -InstallDir $installDir
    }

    Maybe-InstallEurocaps -PluginHome $installDir
    Final-Notes
}

$script:InstallerHadError = $false
try {
    Initialize-EmbeddedPayload
    Main
} catch {
    $script:InstallerHadError = $true
    Write-ErrorLine $_.Exception.Message
} finally {
    Cleanup-EmbeddedPayload
    if ($InstallerHadError) {
        exit 1
    }
}
