$pester = Get-Module -ListAvailable -Name Pester | Where-Object { $_.Version -ge [version]'5.5.0' } | Select-Object -First 1
if (-not $pester) {
    Write-Error "Pester 5.5.0+ is required to run these tests. Install with: Install-Module Pester -MinimumVersion 5.5.0 -Scope CurrentUser"
    return
}

$ErrorActionPreference = 'Stop'

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$env:MODERN_OVERLAY_INSTALLER_IMPORT = '1'
$env:MODERN_OVERLAY_INSTALLER_SKIP_PIP = '1'

Describe 'Create-VenvAndInstall' {
    BeforeAll {
        $env:MODERN_OVERLAY_INSTALLER_IMPORT = '1'
        $env:MODERN_OVERLAY_INSTALLER_SKIP_PIP = '1'
        . (Join-Path $repoRoot 'scripts/install_windows.ps1')
    }

    BeforeEach {
        $script:PythonSpec = [pscustomobject]@{ Command = 'python'; PrefixArgs = @() }
    }

    AfterEach {
        Remove-Item Env:MODERN_OVERLAY_INSTALLER_SKIP_PIP -ErrorAction SilentlyContinue
        $env:MODERN_OVERLAY_INSTALLER_SKIP_PIP = '1'
    }

    It 'keeps existing venv when user declines rebuild' {
        $target = Join-Path $TestDrive 'plugin'
        $venvPath = Join-Path $target 'overlay_client\.venv'
        $scriptsDir = Join-Path $venvPath 'Scripts'
        New-Item -ItemType Directory -Path (Join-Path $target 'overlay_client\requirements') -Force | Out-Null
        New-Item -ItemType File -Path (Join-Path $target 'overlay_client\requirements\base.txt') -Force | Out-Null
        New-Item -ItemType Directory -Path $scriptsDir -Force | Out-Null
        New-Item -ItemType File -Path (Join-Path $scriptsDir 'python.exe') -Force | Out-Null

        Mock -CommandName 'Prompt-YesNo' { $false }
        Mock -CommandName 'Invoke-Python' {}
        Mock -CommandName 'Write-Info' {}

        Create-VenvAndInstall -TargetDir $target

        Test-Path $venvPath | Should -BeTrue
        Should -Invoke 'Prompt-YesNo' -Exactly 1
        Should -Not -Invoke 'Invoke-Python'
    }

    It 'creates venv when missing' {
        $target = Join-Path $TestDrive 'plugin2'
        $venvPath = Join-Path $target 'overlay_client\.venv'
        $scriptsDir = Join-Path $venvPath 'Scripts'
        New-Item -ItemType Directory -Path (Join-Path $target 'overlay_client\requirements') -Force | Out-Null
        New-Item -ItemType File -Path (Join-Path $target 'overlay_client\requirements\base.txt') -Force | Out-Null

        Mock -CommandName 'Prompt-YesNo' { $false }
        Mock -CommandName 'Write-Info' {}
        Mock -CommandName 'Invoke-Python' {
            New-Item -ItemType Directory -Path $scriptsDir -Force | Out-Null
            New-Item -ItemType File -Path (Join-Path $scriptsDir 'python.exe') -Force | Out-Null
        }

        Create-VenvAndInstall -TargetDir $target

        Test-Path (Join-Path $scriptsDir 'python.exe') | Should -BeTrue
        Should -Invoke 'Invoke-Python' -Exactly 1 -ParameterFilter { $Arguments -contains $venvPath }
    }
}
