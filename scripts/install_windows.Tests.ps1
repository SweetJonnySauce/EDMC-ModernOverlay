# Pester tests for install_windows.ps1 installer safeguards.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here 'install_windows.ps1')

Describe 'Update-ExistingInstall' {
    It 'preserves overlay_groupings.user.json when updating an existing install' {
        # Arrange: source payload (fresh package) and destination (existing install with user file).
        $payloadRoot = Join-Path $TestDrive 'payload'
        $sourceDir = Join-Path $payloadRoot 'EDMCModernOverlay'
        New-Item -ItemType Directory -Path $sourceDir -Force | Out-Null
        # Minimal shipped file to mimic payload content.
        Set-Content -LiteralPath (Join-Path $sourceDir 'overlay_groupings.json') -Value '{}' -Encoding UTF8

        $destDir = Join-Path $TestDrive 'EDMCModernOverlay'
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
        $userFile = Join-Path $destDir 'overlay_groupings.user.json'
        $originalUserContent = '{"user":"keep"}'
        Set-Content -LiteralPath $userFile -Value $originalUserContent -Encoding UTF8

        # Act: run update; should backup and restore the user file.
        Update-ExistingInstall -SourceDir $sourceDir -DestDir $destDir

        # Assert: user file still exists with original content.
        Test-Path -LiteralPath $userFile | Should -BeTrue
        Get-Content -LiteralPath $userFile -Raw -Encoding UTF8 | Should -Be $originalUserContent
    }
}
