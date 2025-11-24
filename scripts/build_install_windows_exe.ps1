# build_install_windows_exe.ps1 - helper to compile install_windows.ps1 into an EXE
[CmdletBinding()]
param(
    # Directory that will contain install_windows.ps1 (created if missing).
    [string]$StagingPath = (Get-Location).Path,
    # When provided, copy the plugin payload + installer script from this repo root into the staging directory.
    [string]$SourceRoot,
    [string[]]$ExcludeDirectories = @('.git', '.github', 'scripts', 'dist', 'docs', 'tests', 'schemas', '.codex', '.vscode'),
    [string[]]$ExcludeFiles = @('debug.json', 'EDMC-ModernOverlay.code-workspace'),
    [string[]]$ExcludePatterns = @('*.md')
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
        [string[]]$FileNames,
        [string[]]$Patterns
    )

    $name = $Item.Name
    if ($Item.PSIsContainer -and $DirectoryNames -contains $name) {
        return $true
    }
    if (-not $Item.PSIsContainer -and $FileNames -contains $name) {
        return $true
    }
    foreach ($pattern in $Patterns) {
        if ($name -like $pattern) {
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
        [string[]]$FileExcludes,
        [string[]]$PatternExcludes
    )

    if (-not (Test-Path -LiteralPath $Destination)) {
        New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    }

    foreach ($item in (Get-ChildItem -LiteralPath $Source -Force)) {
        if (Should-ExcludeItem -Item $item -DirectoryNames $DirectoryExcludes -FileNames $FileExcludes -Patterns $PatternExcludes) {
            continue
        }

        $target = Join-Path $Destination $item.Name
        if ($item.PSIsContainer) {
            Copy-PayloadTree -Source $item.FullName -Destination $target -DirectoryExcludes $DirectoryExcludes -FileExcludes $FileExcludes -PatternExcludes $PatternExcludes
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
    Copy-PayloadTree -Source $resolvedSource -Destination $payloadDestination -DirectoryExcludes $ExcludeDirectories -FileExcludes $ExcludeFiles -PatternExcludes $ExcludePatterns

    $sourceInstall = Join-Path $resolvedSource 'scripts/install_windows.ps1'
    if (-not (Test-Path -LiteralPath $sourceInstall)) {
        Fail "Could not locate install_windows.ps1 at '$sourceInstall'."
    }
    $destInstall = Join-Path $resolvedStaging 'install_windows.ps1'
    Copy-Item -LiteralPath $sourceInstall -Destination $destInstall -Force
}

$installScript = Join-Path $resolvedStaging 'install_windows.ps1'
if (-not (Test-Path -LiteralPath $installScript)) {
    Fail "install_windows.ps1 was not found at '$installScript'."
}

$payloadDir = $payloadDestination
if (-not (Test-Path -LiteralPath $payloadDir)) {
    Fail "Payload directory '$payloadDir' was not found. Provide -SourceRoot or pre-stage the payload."
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
