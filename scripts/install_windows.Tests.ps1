# Pester tests for install_windows.ps1 installer safeguards.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$env:MODERN_OVERLAY_INSTALLER_IMPORT = '1'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here 'install_windows.ps1')

Describe 'Update-ExistingInstall' {
    It 'preserves overlay_groupings.user.json when updating an existing install' {
        # Arrange: use a real temp root to avoid TestDrive quirks.
        $tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("pester-" + [guid]::NewGuid().ToString('N'))
        try {
            # Ensure functions are available in this scope.
            $env:MODERN_OVERLAY_INSTALLER_IMPORT = '1'
            . (Join-Path $here 'install_windows.ps1')

            $payloadRoot = Join-Path $tempRoot 'payload'
            $sourceDir = Join-Path $payloadRoot 'EDMCModernOverlay'
            New-Item -ItemType Directory -Path $sourceDir -Force | Out-Null
            # Minimal shipped file to mimic payload content.
            Set-Content -LiteralPath (Join-Path $sourceDir 'overlay_groupings.json') -Value '{}' -Encoding UTF8

            $destDir = Join-Path $tempRoot 'EDMCModernOverlay'
            New-Item -ItemType Directory -Path $destDir -Force | Out-Null
            $userFile = Join-Path $destDir 'overlay_groupings.user.json'
            $originalUserContent = '{"user":"keep"}'
            Set-Content -LiteralPath $userFile -Value $originalUserContent -Encoding UTF8

            Update-ExistingInstall -SourceDir $sourceDir -DestDir $destDir

            Test-Path -LiteralPath $userFile | Should -BeTrue
            Get-Content -LiteralPath $userFile -Raw -Encoding UTF8 | Should -Be $originalUserContent
        } finally {
            Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
