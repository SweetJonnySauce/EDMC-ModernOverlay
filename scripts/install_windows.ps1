# install_windows.ps1 - helper to deploy EDMC Modern Overlay on Windows.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ScriptPath = $PSCommandPath
$ScriptDir = Split-Path -Parent $ScriptPath

function Prompt-YesNo {
    param(
        [string]$Message = 'Continue?',
        [bool]$Default = $false
    )

    $suffix = if ($Default) { 'Y/n' } else { 'y/N' }
    while ($true) {
        $response = Read-Host "$Message [$suffix]"
        if ([string]::IsNullOrWhiteSpace($response)) {
            return $Default
        }

        switch -Regex ($response.Trim()) {
            '^(y|yes)$' { return $true }
            '^(n|no)$' { return $false }
            default { Write-Host 'Please answer yes or no.' }
        }
    }
}

function Find-ReleaseRoot {
    $candidate = Join-Path $ScriptDir 'EDMC-ModernOverlay'
    if (Test-Path $candidate) {
        return (Get-Item $ScriptDir).FullName
    }

    $parent = Split-Path -Parent $ScriptDir
    $candidate = Join-Path $parent 'EDMC-ModernOverlay'
    if (Test-Path $candidate) {
        return (Get-Item $parent).FullName
    }

    throw "Could not find 'EDMC-ModernOverlay' directory alongside the install script."
}

function Resolve-Python {
    $candidates = @(
        @('py', '-3'),
        @('py'),
        @('python3'),
        @('python')
    )

    foreach ($entry in $candidates) {
        $command = $entry[0]
        if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
            continue
        }
        $prefixArgs = @()
        if ($entry.Count -gt 1) {
            $prefixArgs = $entry[1..($entry.Count - 1)]
        }

        $checkArgs = @()
        if ($prefixArgs.Count -gt 0) {
            $checkArgs += $prefixArgs
        }
        $checkArgs += @('-c', 'import sys; sys.exit(0) if sys.version_info >= (3, 0) else sys.exit(1)')

        try {
            & $command @checkArgs *> $null
            return [pscustomobject]@{
                Command    = $command
                PrefixArgs = $prefixArgs
            }
        } catch {
            continue
        }
    }

    throw 'Python 3 is required but could not be found on PATH.'
}

function Detect-PluginDir {
    $base = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $env:USERPROFILE 'AppData\Local' }
    $default = Join-Path $base 'EDMarketConnector\plugins'

    if (Test-Path $default) {
        Write-Host "Detected EDMarketConnector plugins directory at '$default'."
        if (Prompt-YesNo -Message 'Use this directory?') {
            return (Get-Item $default).FullName
        }
    } else {
        Write-Host "EDMarketConnector plugin directory not found at '$default'."
    }

    while ($true) {
        $inputPath = Read-Host 'Enter the path to your EDMarketConnector plugins directory'
        if ([string]::IsNullOrWhiteSpace($inputPath)) {
            Write-Host 'Path cannot be empty.'
            continue
        }
        $inputPath = [IO.Path]::GetFullPath($inputPath)
        if (Test-Path $inputPath) {
            return (Get-Item $inputPath).FullName
        }
        Write-Host "Directory '$inputPath' does not exist."
        if (Prompt-YesNo -Message 'Create this directory?') {
            New-Item -Path $inputPath -ItemType Directory -Force | Out-Null
            return (Get-Item $inputPath).FullName
        }
        Write-Host 'Please provide a valid directory.'
    }
}

function Ensure-EdmcNotRunning {
    $process = Get-Process -Name 'EDMarketConnector' -ErrorAction SilentlyContinue
    if (-not $process) {
        return
    }

    Write-Host 'EDMarketConnector appears to be running.'
    if (-not (Prompt-YesNo -Message 'Close EDMarketConnector and continue installation?')) {
        throw 'Installation requires EDMarketConnector to be closed.'
    }

    while (Get-Process -Name 'EDMarketConnector' -ErrorAction SilentlyContinue) {
        Write-Host 'Waiting for EDMarketConnector to exit...'
        Start-Sleep -Seconds 2
    }
}

function Disable-ConflictingPlugins {
    param(
        [string]$PluginDir
    )

    $conflicts = Get-ChildItem -Path $PluginDir -Directory -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -like 'EDMCOverlay*' -and $_.Name -notlike '*.disabled'
    }

    if (-not $conflicts) {
        return
    }

    Write-Host 'Found legacy overlay plugins that conflict with Modern Overlay:'
    foreach ($item in $conflicts) {
        Write-Host " - $($item.Name)"
    }

    if (-not (Prompt-YesNo -Message 'Disable the legacy overlay plugin(s)?')) {
        throw 'Cannot proceed while legacy overlay is enabled.'
    }

    foreach ($item in $conflicts) {
        $target = Join-Path $PluginDir "$($item.Name).disabled"
        if (Test-Path $target) {
            Write-Host " - $($item.Name) is already disabled."
            continue
        }
        Rename-Item -Path $item.FullName -NewName "$($item.Name).disabled"
        Write-Host " - Disabled $($item.Name)."
    }
}

function Create-VenvAndInstall {
    param(
        [string]$TargetDir,
        [pscustomobject]$Python
    )

    $overlayClient = Join-Path $TargetDir 'overlay-client'
    if (-not (Test-Path $overlayClient)) {
        throw "Missing overlay-client directory in '$TargetDir'."
    }

    $venvPath = Join-Path $overlayClient '.venv'
    if (-not (Test-Path $venvPath)) {
        Write-Host "Creating Python virtual environment at '$venvPath'..."
        $args = @()
        if ($Python.PrefixArgs) {
            $args += $Python.PrefixArgs
        }
        $args += @('-m', 'venv', $venvPath)
        & $Python.Command @args
    }

    $venvPython = Join-Path $venvPath 'Scripts\python.exe'
    if (-not (Test-Path $venvPython)) {
        throw "Virtual environment at '$venvPath' is missing python.exe."
    }

    $requirementsPath = Join-Path $overlayClient 'requirements.txt'
    Write-Host "Installing overlay client requirements from '$requirementsPath' into '$venvPath'..."
    & $venvPython -m pip install --upgrade pip *> $null
    & $venvPython -m pip install -r $requirementsPath
}

function Copy-InitialInstall {
    param(
        [string]$SourceDir,
        [string]$PluginRoot,
        [pscustomobject]$Python
    )

    Write-Host 'Copying Modern Overlay into plugins directory...'
    $target = Join-Path $PluginRoot (Split-Path $SourceDir -Leaf)
    if (Test-Path $target) {
        Remove-Item -Path $target -Recurse -Force
    }
    Copy-Item -Path $SourceDir -Destination $PluginRoot -Recurse -Force
    Create-VenvAndInstall -TargetDir $target -Python $Python
}

function Update-ExistingInstall {
    param(
        [string]$SourceDir,
        [string]$DestDir
    )

    if (-not (Get-Command robocopy -ErrorAction SilentlyContinue)) {
        throw 'robocopy is required to update the plugin without overwriting the virtualenv.'
    }

    Write-Host 'Updating existing Modern Overlay installation...'
    $args = @(
        $SourceDir,
        $DestDir,
        '/MIR',
        '/XD', 'overlay-client\.venv',
        '/XF', 'overlay-client\fonts\EUROCAPS.ttf'
    )

    & robocopy @args | Out-Null
    $code = $LASTEXITCODE
    if ($code -ge 8) {
        throw "robocopy failed with exit code $code."
    }
}

function Ensure-ExistingInstall {
    param(
        [string]$DestDir,
        [pscustomobject]$Python
    )

    $venvPath = Join-Path $DestDir 'overlay-client\.venv'
    if (-not (Test-Path $venvPath)) {
        Write-Host 'Existing installation lacks a virtual environment. Creating one...'
        Create-VenvAndInstall -TargetDir $DestDir -Python $Python
    }
}

function Show-FinalNotes {
    Write-Host ''
    Write-Host 'Installation complete.'
    Write-Host 'install_eurocaps.sh was not run. Execute it separately if you wish to install the Eurocaps font.'
    Write-Host ''
}

function Invoke-Main {
    $releaseRoot = Find-ReleaseRoot
    $python = Resolve-Python
    if (-not $python -or -not ($python.PSObject.Properties["Command"]) -or -not $python.Command) {
        throw 'Python 3 interpreter could not be resolved. Ensure Python 3 is installed and on PATH (try "py -3", "python3", or "python").'
    }

    $prefix = if ($python.PrefixArgs -and $python.PrefixArgs.Count -gt 0) { ' ' + ($python.PrefixArgs -join ' ') } else { '' }
    Write-Host "Using Python interpreter '$($python.Command)$prefix'."

    $pluginDir = Detect-PluginDir
    Ensure-EdmcNotRunning
    Disable-ConflictingPlugins -PluginDir $pluginDir

    $sourceDir = Join-Path $releaseRoot 'EDMC-ModernOverlay'
    if (-not (Test-Path $sourceDir)) {
        throw "Source directory '$sourceDir' not found."
    }

    $destDir = Join-Path $pluginDir 'EDMC-ModernOverlay'
    if (-not (Test-Path $destDir)) {
        Copy-InitialInstall -SourceDir $sourceDir -PluginRoot $pluginDir -Python $python
    } else {
        Write-Host "An existing installation was detected at '$destDir'."
        Write-Host 'Plugin files will be replaced while preserving the existing overlay-client\.venv.'
        if (-not (Prompt-YesNo -Message 'Proceed with updating the installation?')) {
            throw 'Installation aborted by user to protect the existing virtual environment.'
        }
        Ensure-ExistingInstall -DestDir $destDir -Python $python
        Update-ExistingInstall -SourceDir $sourceDir -DestDir $destDir
    }

    Show-FinalNotes
}

try {
    Invoke-Main
    exit 0
} catch {
    Write-Error $_.Exception.Message
    exit 1
}
