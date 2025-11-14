# Windows Installer Build (Option 2)

This document describes how to wrap `scripts/install_windows.ps1` into a single `.exe`
so Windows users can double-click the installer. The executable simply runs the
PowerShell script that lives beside it and expects the full `EDMC-ModernOverlay/`
payload to sit next to the installer (exactly like the `.ps1`/`.sh` helpers do).

## Prerequisites

- Windows 10/11 machine (or Windows VM/CI runner)
- PowerShell 5.1+ (PowerShell 7 works too)
- [`ps2exe`](https://github.com/MScholtes/PS2EXE) module for packaging scripts
- Repo checkout or release staging folder containing:
  - `scripts/install_windows.ps1`
  - `EDMC-ModernOverlay/` plugin directory (the payload that will be copied into EDMC)

## 1. Install ps2exe

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
Install-Module -Name ps2exe -Scope CurrentUser -Force
```

> `Set-ExecutionPolicy` is optional but helps avoid unsigned-script prompts on fresh environments.

## 2. Stage the release folder

```
release/
├── install_windows.ps1
├── EDMC-ModernOverlay/
│   ├── overlay-client/
│   ├── overlay_plugin/
│   └── …
└── scripts/
    └── install_windows.ps1   (if you keep the repo tree unchanged)
```

When building the `.exe`, run the command from the repository root (or adjust paths) so
`install_windows.ps1` references the payload via `$PSScriptRoot\EDMC-ModernOverlay`.

## 3. Build the executable

```powershell
cd path\to\EDMC-ModernOverlay

Invoke-ps2exe `
    -InputFile scripts\install_windows.ps1 `
    -OutputFile install_windows.exe `
    -NoConsole `
    -Title "EDMC Modern Overlay Installer" `
    -Description "Installs the EDMC Modern Overlay plugin next to EDMC." `
    -Version $(Get-Content .\version.py | Select-String -Pattern '\d+\.\d+\.\d+')
```

Notes:
- `-NoConsole` hides the console window; drop it if you prefer the default console UI.
- Set `-IconFile path\to\icon.ico` if you have branding for the installer.
- `-Version` can be hard-coded or parsed from `version.py`/`git describe`.

## 4. Smoke-test the packaged installer

1. Copy `install_windows.exe`, `install_windows.ps1`, and `EDMC-ModernOverlay/`
   into a fresh folder that mirrors the final release archive.
2. Double-click the `.exe` (or run `.\install_windows.exe -AssumeYes -DryRun -PluginDir C:\Temp\Plugins`
   from PowerShell) to confirm the script runs, sees the adjacent payload, and respects the CLI switches.

If `pwsh`/`powershell` is not on PATH for end users, PS2EXE embeds the required host, so the installer
continues to work without extra dependencies.

## 5. Ship the release

- Zip the staged folder so the archive contains:
  - `install_windows.exe`
  - `install_windows.ps1` (keep the script for transparency/troubleshooting)
  - `install-eurocaps.bat`
  - `EDMC-ModernOverlay/`
- Upload to GitHub Releases. Only rebuild `install_windows.exe` when
  `scripts/install_windows.ps1` changes or you alter the expected payload layout.

Optional: Code-sign `install_windows.exe` before shipping to reduce SmartScreen prompts:

```powershell
signtool sign /fd SHA256 /a /tr http://timestamp.digicert.com install_windows.exe
```
