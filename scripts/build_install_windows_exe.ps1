# build_install_windows_exe.ps1 - helper to compile install_windows.ps1 into an EXE
[CmdletBinding()]
param(
    # Directory that will contain install_windows.ps1 (created if missing).
    [string]$StagingPath = (Get-Location).Path,
    # When provided, copy the plugin payload + installer script from this repo root into the staging directory.
    [string]$SourceRoot,
    # Path to JSON manifest of excludes (directories, root_directories, files, patterns, substrings).
    [string]$ExcludeManifest,
    [string[]]$ExcludeDirectories = @(),
    [string[]]$ExcludeRootDirectories = @(),
    [string[]]$ExcludeFiles = @(),
    [string[]]$ExcludePatterns = @(),
    [string[]]$ExcludeSubstrings = @()
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
        if (-not (Test-Path -LiteralPath $Path)) {
            Write-Host "Creating staging directory '$Path'."
            New-Item -ItemType Directory -Path $Path -Force | Out-Null
        }
        return (Resolve-Path -LiteralPath $Path).ProviderPath
    } catch {
        Fail "Could not prepare staging path '$Path'."
    }
}

function Resolve-SourceRoot {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $null
    }
    try {
        return (Resolve-Path -LiteralPath $Path).ProviderPath
    } catch {
        Fail "Source root '$Path' was not found."
    }
}

function Should-ExcludeItem {
    param(
        [System.IO.FileSystemInfo]$Item,
        [string[]]$DirectoryNames,
        [string[]]$RootDirectoryNames,
        [string[]]$FileNames,
        [string[]]$Patterns,
        [string[]]$Substrings,
        [string]$BaseRoot
    )

    $name = $Item.Name
    $relative = $Item.FullName.Substring($BaseRoot.Length).TrimStart('\', '/')
    $relativePosix = $relative -replace '\\', '/'

    if ($Item.PSIsContainer -and $DirectoryNames -contains $name) {
        return $true
    }
    if ($Item.PSIsContainer -and $RootDirectoryNames -contains $name) {
        $firstSegment = $relativePosix.Split('/')[0]
        if ($firstSegment -eq $name) {
            return $true
        }
    }
    if (-not $Item.PSIsContainer -and $FileNames -contains $name) {
        return $true
    }
    foreach ($pattern in $Patterns) {
        if ($name -like $pattern) {
            return $true
        }
    }
    foreach ($substr in $Substrings) {
        if ($relativePosix -like "*$substr*") {
            return $true
        }
    }
    return $false
}

function Copy-PayloadTree {
    param(
        [string]$Source,
        [string]$Destination,
        [string[]]$DirectoryExcludes,
        [string[]]$RootDirectoryExcludes,
        [string[]]$FileExcludes,
        [string[]]$PatternExcludes,
        [string[]]$SubstringExcludes,
        [string]$BaseRoot
    )

    if (-not (Test-Path -LiteralPath $Destination)) {
        New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    }

    foreach ($item in (Get-ChildItem -LiteralPath $Source -Force)) {
        if (Should-ExcludeItem -Item $item -DirectoryNames $DirectoryExcludes -RootDirectoryNames $RootDirectoryExcludes -FileNames $FileExcludes -Patterns $PatternExcludes -Substrings $SubstringExcludes -BaseRoot $BaseRoot) {
            continue
        }

        $target = Join-Path $Destination $item.Name
        if ($item.PSIsContainer) {
            Copy-PayloadTree -Source $item.FullName -Destination $target -DirectoryExcludes $DirectoryExcludes -RootDirectoryExcludes $RootDirectoryExcludes -FileExcludes $FileExcludes -PatternExcludes $PatternExcludes -SubstringExcludes $SubstringExcludes -BaseRoot $BaseRoot
        } else {
            $parent = Split-Path -Parent $target
            if (-not (Test-Path -LiteralPath $parent)) {
                New-Item -ItemType Directory -Path $parent -Force | Out-Null
            }
            Copy-Item -LiteralPath $item.FullName -Destination $target -Force
        }
    }
}

$resolvedStaging = Resolve-StagingPath -Path $StagingPath
$resolvedSource = Resolve-SourceRoot -Path $SourceRoot

# Load excludes from manifest if provided; otherwise fall back to defaults passed in.
if (-not $ExcludeManifest) {
    $ExcludeManifest = Join-Path $resolvedSource 'scripts/release_excludes.json'
}

$excludeDirs = @()
$excludeRootDirs = @()
$excludeFiles = @()
$excludePatterns = @()
$excludeSubstrings = @('overlay_client/.venv')

if (Test-Path -LiteralPath $ExcludeManifest) {
    $excludes = Get-Content -LiteralPath $ExcludeManifest -Raw | ConvertFrom-Json
    if ($excludes.directories) { $excludeDirs = $excludes.directories }
    if ($excludes.root_directories) { $excludeRootDirs = $excludes.root_directories }
    if ($excludes.files) { $excludeFiles = $excludes.files }
    if ($excludes.patterns) { $excludePatterns = $excludes.patterns }
    if ($excludes.substrings) { $excludeSubstrings = $excludes.substrings }
}

# Allow explicit overrides/augments from parameters.
if ($ExcludeDirectories) { $excludeDirs += $ExcludeDirectories }
if ($ExcludeRootDirectories) { $excludeRootDirs += $ExcludeRootDirectories }
if ($ExcludeFiles) { $excludeFiles += $ExcludeFiles }
if ($ExcludePatterns) { $excludePatterns += $ExcludePatterns }
if ($ExcludeSubstrings) { $excludeSubstrings += $ExcludeSubstrings }

function Write-EmbeddedInstaller {
    param(
        [string]$SourceScript,
        [string]$DestinationScript,
        [string]$PayloadBase64
    )

    $placeholder = '$script:EmbeddedPayloadBase64 = $null # EMBEDDED_PAYLOAD_PLACEHOLDER'
    $scriptContent = Get-Content -LiteralPath $SourceScript -Raw
    if (-not $scriptContent.Contains($placeholder)) {
        Fail "Installer script placeholder '$placeholder' not found."
    }

    $template = @"
`$script:EmbeddedPayloadBase64 = @'
{0}
'@
"@

    $replacement = $template -f $PayloadBase64
    $updatedContent = $scriptContent.Replace($placeholder, $replacement.TrimEnd("`r", "`n"))
    Set-Content -LiteralPath $DestinationScript -Value $updatedContent -Encoding UTF8
}

$payloadDestination = Join-Path $resolvedStaging 'EDMCModernOverlay'

if ($resolvedSource) {
    if (Test-Path -LiteralPath $payloadDestination) {
        Write-Host "Clearing existing payload at '$payloadDestination'."
        Remove-Item -LiteralPath $payloadDestination -Recurse -Force
    }
    Write-Host "Copying plugin payload from '$resolvedSource' to '$payloadDestination'."
    Copy-PayloadTree -Source $resolvedSource -Destination $payloadDestination -DirectoryExcludes $excludeDirs -RootDirectoryExcludes $excludeRootDirs -FileExcludes $excludeFiles -PatternExcludes $excludePatterns -SubstringExcludes $excludeSubstrings -BaseRoot $resolvedSource

    $sourceInstall = Join-Path $resolvedSource 'scripts/install_windows.ps1'
    if (-not (Test-Path -LiteralPath $sourceInstall)) {
        Fail "Could not locate install_windows.ps1 at '$sourceInstall'."
    }
    $destInstall = Join-Path $resolvedStaging 'install_windows.ps1'
    Copy-Item -LiteralPath $sourceInstall -Destination $destInstall -Force
}

$checksumScript = Join-Path $resolvedSource 'scripts/generate_checksums.py'
if (-not (Test-Path -LiteralPath $checksumScript)) {
    Fail "Checksum generator not found at '$checksumScript'."
}

$installScript = Join-Path $resolvedStaging 'install_windows.ps1'
if (-not (Test-Path -LiteralPath $installScript)) {
    Fail "install_windows.ps1 was not found at '$installScript'."
}

$payloadDir = $payloadDestination
if (-not (Test-Path -LiteralPath $payloadDir)) {
    Fail "Payload directory '$payloadDir' was not found. Provide -SourceRoot or pre-stage the payload."
}

# Generate checksum manifest inside the payload so the installer can validate it.
Write-Host "Generating checksum manifest for payload at '$payloadDir'."
$checksumPath = Join-Path $payloadDir 'checksums.txt'
& python $checksumScript --root $resolvedStaging --target-dir $payloadDir --output $checksumPath --excludes $ExcludeManifest
if (-not (Test-Path -LiteralPath $checksumPath)) {
    Fail "Checksum manifest was not created at '$checksumPath'."
}

$payloadArchive = Join-Path $resolvedStaging 'embedded_payload.zip'
if (Test-Path -LiteralPath $payloadArchive) {
    Remove-Item -LiteralPath $payloadArchive -Force
}

Write-Host "Creating embedded payload archive from '$payloadDir'."
Compress-Archive -Path $payloadDir -DestinationPath $payloadArchive -Force
$payloadBase64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($payloadArchive))
Remove-Item -LiteralPath $payloadArchive -Force

$embeddedInstallScript = Join-Path $resolvedStaging 'install_windows_embedded.ps1'
Write-EmbeddedInstaller -SourceScript $installScript -DestinationScript $embeddedInstallScript -PayloadBase64 $payloadBase64

$outputExe = Join-Path $resolvedStaging 'install_windows.exe'
Write-Host "Compiling installer:"
Write-Host "  Source : $embeddedInstallScript"
Write-Host "  Output : $outputExe"

Invoke-ps2exe `
    -InputFile $embeddedInstallScript `
    -OutputFile $outputExe `
    -Title "EDMC Modern Overlay Installer" `
    -Description "Installs the EDMC Modern Overlay plugin next to EDMC."

Remove-Item -LiteralPath $embeddedInstallScript -Force

Write-Host "install_windows.exe has been generated at '$outputExe'."
