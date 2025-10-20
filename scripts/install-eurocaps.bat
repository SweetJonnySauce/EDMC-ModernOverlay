@echo off
REM Helper script to download Eurocaps.ttf into the Modern Overlay plugin fonts directory.
REM Usage: install-eurocaps.bat [path-to-EDMC-ModernOverlay]

setlocal enabledelayedexpansion

set "DEFAULT_PLUGIN_DIR=%LOCALAPPDATA%\EDMarketConnector\plugins\EDMC-ModernOverlay"
if "%~1"=="" (
    set "PLUGIN_DIR=%DEFAULT_PLUGIN_DIR%"
) else (
    set "PLUGIN_DIR=%~1"
)

set "FONT_DIR=%PLUGIN_DIR%\overlay-client\fonts"
set "TARGET_FONT=%FONT_DIR%\Eurocaps.ttf"
set "PREFERRED_LIST=%FONT_DIR%\preferred_fonts.txt"
set "FONT_URL=https://raw.githubusercontent.com/inorton/EDMCOverlay/master/EDMCOverlay/EDMCOverlay/EUROCAPS.TTF"
set "TEMP_FONT=%TEMP%\Eurocaps.ttf"

echo Using plugin directory: %PLUGIN_DIR%

if not exist "%FONT_DIR%\" (
    echo Error: %FONT_DIR% not found. Provide the path to your EDMC-ModernOverlay plugin.
    exit /b 1
)

echo Downloading Eurocaps.ttf from %FONT_URL% ...
powershell -NoProfile -Command ^
    "try { Invoke-WebRequest -Uri '%FONT_URL%' -OutFile '%TEMP_FONT%' -UseBasicParsing } catch { exit 1 }"

if not exist "%TEMP_FONT%" (
    echo Error: download failed.
    exit /b 1
)

copy /Y "%TEMP_FONT%" "%TARGET_FONT%" >nul
echo Installed Eurocaps.ttf to %TARGET_FONT%

del "%TEMP_FONT%" >nul 2>&1

if exist "%PREFERRED_LIST%" (
    powershell -NoProfile -Command ^
        "$path = '%PREFERRED_LIST%';" ^
        "if (-not (Test-Path $path)) { exit };" ^
        "$exists = Select-String -Path $path -Pattern '^(?i)Eurocaps\.ttf$' -Quiet;" ^
        "if (-not $exists) { Add-Content -Path $path -Value 'Eurocaps.ttf'; Write-Host 'Added Eurocaps.ttf to preferred_fonts.txt' } else { Write-Host 'Eurocaps.ttf already listed in preferred_fonts.txt' }"
) else (
    echo Warning: preferred_fonts.txt not found. The overlay will still discover the font automatically.
)

echo Done. Restart the overlay client to pick up the new font.

endlocal
