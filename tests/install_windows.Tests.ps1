$pester = Get-Module -ListAvailable -Name Pester | Where-Object { $_.Version -ge [version]'5.5.0' } | Select-Object -First 1
if (-not $pester) {
    Write-Error "Pester 5.5.0+ is required to run these tests. Install with: Install-Module Pester -MinimumVersion 5.5.0 -Scope CurrentUser"
    return
}
$pesterVersion = $pester.Version.ToString()
Write-Host "Using Pester $pesterVersion"

$ErrorActionPreference = 'Stop'

$testPath = $null
if ($PSCommandPath) { $testPath = $PSCommandPath }
elseif ($MyInvocation.MyCommand.Path) { $testPath = $MyInvocation.MyCommand.Path }
elseif ($PSScriptRoot) { $testPath = Join-Path $PSScriptRoot (Split-Path -Leaf $MyInvocation.MyCommand.Path) }

if (-not $testPath) {
    try {
        $gitRoot = (git rev-parse --show-toplevel 2>$null)
        if ($gitRoot) {
            $testPath = Join-Path $gitRoot 'tests\install_windows.Tests.ps1'
        }
    } catch { }
}
if (-not $testPath -and $env:GITHUB_WORKSPACE) {
    $testPath = Join-Path $env:GITHUB_WORKSPACE 'tests\install_windows.Tests.ps1'
}

if (-not $testPath) {
    throw "Unable to determine test file path (PSCommandPath/MyInvocation/PSScriptRoot unavailable)."
}
$here = Split-Path -Parent $testPath
$repoRoot = Split-Path -Parent $here
$script:ResolvedTestPath = $testPath
$script:ResolvedRepoRoot = $repoRoot
$env:TEST_RESOLVED_PATH = $testPath
$env:TEST_RESOLVED_ROOT = $repoRoot
Write-Host "Test path: $testPath"
Write-Host "Repo root: $repoRoot"
$env:MODERN_OVERLAY_INSTALLER_IMPORT = '1'
$env:MODERN_OVERLAY_INSTALLER_SKIP_PIP = '1'

Describe 'Create-VenvAndInstall' {
    BeforeAll {
        $env:MODERN_OVERLAY_INSTALLER_IMPORT = '1'
        $env:MODERN_OVERLAY_INSTALLER_SKIP_PIP = '1'
        $repoRootLocal = $script:ResolvedRepoRoot
        if (-not $repoRootLocal -and $env:TEST_RESOLVED_ROOT) {
            $repoRootLocal = $env:TEST_RESOLVED_ROOT
        }
        if (-not $repoRootLocal -and (git rev-parse --show-toplevel 2>$null)) {
            $repoRootLocal = (git rev-parse --show-toplevel 2>$null)
        }
        if (-not $repoRootLocal -and $env:GITHUB_WORKSPACE) {
            $repoRootLocal = $env:GITHUB_WORKSPACE
        }
        if (-not $repoRootLocal) {
            throw "Unable to resolve repo root in BeforeAll."
        }
        $installerPath = Join-Path $repoRootLocal 'scripts/install_windows.ps1'
        if (-not (Test-Path -LiteralPath $installerPath)) {
            throw "Installer not found at '$installerPath'."
        }
        Write-Host "Installer path: $installerPath"
        . $installerPath
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
