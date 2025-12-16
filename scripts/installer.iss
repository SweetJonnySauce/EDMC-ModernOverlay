#ifndef PayloadRoot
  #define PayloadRoot "dist\\inno_payload"
#endif

#ifndef OutputDir
  #define OutputDir "dist\\inno_output"
#endif

#ifndef AppVersion
  #define AppVersion "dev"
#endif

#ifndef OutputBaseFilename
  #define OutputBaseFilename "EDMCModernOverlay-setup"
#endif

#ifndef InstallVenvMode
  #define InstallVenvMode "embedded"
#endif

[Setup]
AppId=EDMCModernOverlay
AppName=EDMC Modern Overlay
AppVersion={#AppVersion}
AppPublisher=EDMC Modern Overlay
DefaultDirName={code:GetDefaultPluginDir}
DisableDirPage=no
UsePreviousAppDir=yes
DisableReadyMemo=yes
DisableProgramGroupPage=yes
DirExistsWarning=no
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseFilename}
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
CloseApplications=yes
RestartApplications=no
Uninstallable=no

[Tasks]
Name: "font"; Description: "Install Eurocaps font (you confirm you have a license to use this font)"; Flags: unchecked

[Files]
; Plugin payload
Source: "{#PayloadRoot}\EDMCModernOverlay\*"; DestDir: "{app}\EDMCModernOverlay"; Flags: ignoreversion recursesubdirs
; Preserve user settings and fonts if they already exist
Source: "{#PayloadRoot}\EDMCModernOverlay\overlay_groupings.user.json"; DestDir: "{app}\EDMCModernOverlay"; Flags: ignoreversion external skipifsourcedoesntexist
Source: "{#PayloadRoot}\EDMCModernOverlay\overlay_settings.json"; DestDir: "{app}\EDMCModernOverlay"; Flags: ignoreversion external skipifsourcedoesntexist
Source: "{#PayloadRoot}\EDMCModernOverlay\overlay_client\fonts\*"; DestDir: "{app}\EDMCModernOverlay\overlay_client\fonts"; Flags: ignoreversion recursesubdirs external skipifsourcedoesntexist
; Bundled assets staged to temp
Source: "{#PayloadRoot}\tools\generate_checksums.py"; DestDir: "{tmp}\tools"; Flags: ignoreversion deleteafterinstall
Source: "{#PayloadRoot}\tools\release_excludes.json"; DestDir: "{tmp}\tools"; Flags: ignoreversion deleteafterinstall
Source: "{#PayloadRoot}\checksums_payload.txt"; DestDir: "{tmp}"; Flags: ignoreversion deleteafterinstall
Source: "{#PayloadRoot}\extras\font\Eurocaps.ttf"; DestDir: "{tmp}\extras\font"; Flags: ignoreversion deleteafterinstall; Tasks: font

[Code]
const
  ChecksumScript = '\tools\generate_checksums.py';
  ExcludesFile = '\tools\release_excludes.json';
  FontFile = '\extras\font\Eurocaps.ttf';
  InstallVenvMode = '{#InstallVenvMode}';

procedure PerformPostInstallTasks; forward;

function GetDefaultPluginDir(Param: string): string;
begin
  if DirExists(ExpandConstant('{localappdata}\EDMarketConnector\plugins')) then
    Result := ExpandConstant('{localappdata}\EDMarketConnector\plugins')
  else
    Result := ExpandConstant('{userprofile}\AppData\Local\EDMarketConnector\plugins');
end;

function IsProcessRunning(const Name: string): Boolean;
var
  WbemLocator, WbemServices, WbemObjectSet: Variant;
begin
  Result := False;
  try
    WbemLocator := CreateOleObject('WbemScripting.SWbemLocator');
    WbemServices := WbemLocator.ConnectServer('.', 'root\cimv2');
    WbemObjectSet := WbemServices.ExecQuery(Format('Select * from Win32_Process where Name="%s"', [Name]));
    Result := (WbemObjectSet.Count > 0);
  except
    Result := False;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): string;
begin
  if IsProcessRunning('EDMarketConnector.exe') then
  begin
    Result := 'Please close EDMarketConnector before installing the overlay.';
    exit;
  end;
  Result := '';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  pluginTarget: string;
  response: Integer;
begin
  Result := True;
  if CurPageID = wpSelectDir then
  begin
    pluginTarget := ExpandConstant('{app}') + '\EDMCModernOverlay';
    if DirExists(pluginTarget) then
    begin
      response := MsgBox(
        'An existing EDMCModernOverlay installation was found at:' + #13#10 +
        pluginTarget + #13#10#13#10 +
        'The installer will perform an upgrade. User settings and fonts will be preserved.' + #13#10 +
        'Continue?',
        mbConfirmation, MB_YESNO or MB_DEFBUTTON2);
      if response <> IDYES then
        Result := False;
    end;
  end;
end;

function DisableDirIfExists(const DirPath: string): Boolean;
var
  target: string;
  idx: Integer;
  renamed: Boolean;
begin
  Result := True;
  if DirExists(DirPath) then
  begin
    target := DirPath + '.disabled';
    idx := 1;
    while DirExists(target) do
    begin
      target := DirPath + '.' + IntToStr(idx) + '.disabled';
      idx := idx + 1;
    end;
    renamed := RenameFile(DirPath, target);
    if renamed then
      MsgBox(Format('Legacy plugin folder "%s" was renamed to "%s" to avoid conflicts.', [DirPath, target]), mbInformation, MB_OK)
    else
    begin
      Result := False;
      MsgBox(Format('Failed to rename "%s". Please close any programs using it.', [DirPath]), mbError, MB_OK);
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  pluginRoot, legacy1, legacy2: string;
begin
  if CurStep = ssInstall then
  begin
    pluginRoot := ExpandConstant('{app}');
    legacy1 := pluginRoot + '\EDMC-ModernOverlay';
    legacy2 := pluginRoot + '\EDMCOverlay';
    if not DisableDirIfExists(legacy1) then
      WizardForm.Close;
    if not DisableDirIfExists(legacy2) then
      WizardForm.Close;
  end
  else if CurStep = ssPostInstall then
  begin
    PerformPostInstallTasks;
  end;
end;

function RunAndCheck(const FileName, Params, WorkDir, Friendly: string): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec(FileName, Params, WorkDir, SW_HIDE, ewWaitUntilTerminated, ResultCode);
  if (not Result) or (ResultCode <> 0) then
  begin
    MsgBox(Format('%s failed (code %d).', [Friendly, ResultCode]), mbError, MB_OK);
    Result := False;
  end;
end;

function GetChecksumScriptPath(): string;
begin
  Result := ExpandConstant('{tmp}') + ChecksumScript;
end;

function GetExcludesPath(): string;
begin
  Result := ExpandConstant('{tmp}') + ExcludesFile;
end;

function GetFontTempPath(): string;
begin
  Result := ExpandConstant('{tmp}') + FontFile;
end;

function GetPayloadManifestPath(): string;
begin
  Result := ExpandConstant('{tmp}') + '\checksums_payload.txt';
end;

function GetVenvPython(): string;
begin
  Result := ExpandConstant('{app}') + '\EDMCModernOverlay\overlay_client\.venv\Scripts\python.exe';
end;

function IsEmbeddedMode(): Boolean;
begin
  Result := CompareText(InstallVenvMode, 'embedded') = 0;
end;

function IsBuildMode(): Boolean;
begin
  Result := CompareText(InstallVenvMode, 'build') = 0;
end;

function VenvMeetsRequirements(const PythonExe: string): Boolean;
var
  checkScript, logPath, scriptContent, logContent: string;
  logContentAnsi: AnsiString;
  resultCode: Integer;
begin
  checkScript := ExpandConstant('{tmp}') + '\venv_check.py';
  logPath := ExpandConstant('{tmp}') + '\venv_check_output.txt';
  scriptContent :=
    'import sys, traceback' + #13#10 +
    'log_path = sys.argv[1]' + #13#10 +
    'lines = []' + #13#10 +
    'lines.append("sys_executable=" + sys.executable)' + #13#10 +
    'lines.append("sys_version=" + sys.version.replace("\\n", " "))' + #13#10 +
    'ok = True' + #13#10 +
    'try:' + #13#10 +
    '    import PyQt6' + #13#10 +
    '    ver = getattr(PyQt6, "__version__", "0.0")' + #13#10 +
    '    lines.append("pyqt6_version=" + ver)' + #13#10 +
    '    try:' + #13#10 +
    '        ver_t = tuple(int(x) for x in ver.split(".")[0:2])' + #13#10 +
    '    except Exception:' + #13#10 +
    '        ver_t = (0, 0)' + #13#10 +
    '    ok = ok and sys.version_info >= (3, 10) and ver_t >= (6, 5)' + #13#10 +
    'except Exception:' + #13#10 +
    '    ok = False' + #13#10 +
    '    lines.append("pyqt6_import_error=" + traceback.format_exc())' + #13#10 +
    'with open(log_path, "w", encoding="utf-8") as fh:' + #13#10 +
    '    fh.write("\\n".join(lines))' + #13#10 +
    'sys.exit(0 if ok else 1)';

  if not SaveStringToFile(checkScript, scriptContent, False) then
  begin
    MsgBox('Failed to write venv check script.', mbError, MB_OK);
    Result := False;
    exit;
  end;

  DeleteFile(logPath);
  Log(Format('Checking existing venv using: %s %s %s', [PythonExe, checkScript, logPath]));

  if not Exec(PythonExe, Format('"%s" "%s"', [checkScript, logPath]), '', SW_HIDE, ewWaitUntilTerminated, resultCode) then
  begin
    Log('Exec failed launching venv check script.');
    MsgBox('Existing venv Python/deps check could not be launched (see log).', mbError, MB_OK);
    Result := False;
    exit;
  end;

  if LoadStringFromFile(logPath, logContentAnsi) then
  begin
    logContent := logContentAnsi;
    Log('Existing venv check details:'#13#10 + logContent)
  end
  else
    Log('Existing venv check produced no log output.');

  Result := (resultCode = 0);
  if not Result then
    MsgBox(Format('Existing venv Python/deps check failed (code %d). See log for details.', [resultCode]), mbError, MB_OK);
end;

function GetChecksumManifest(): string;
begin
  Result := ExpandConstant('{app}') + '\EDMCModernOverlay\checksums.txt';
end;

procedure PerformPostInstallTasks;
var
  checksumScriptPath, manifest, appRoot, venvPython, fontPath: string;
  excludesPath, payloadManifest: string;
  pythonCheckCmd, includeArg, pythonForChecks: string;
  hasExistingVenv, skipRebuild, needsRebuild, venvMatches: Boolean;
  response: Integer;
begin
  checksumScriptPath := GetChecksumScriptPath();
  excludesPath := GetExcludesPath();
  payloadManifest := GetPayloadManifestPath();
  manifest := GetChecksumManifest();
  appRoot := ExpandConstant('{app}');
  venvPython := GetVenvPython();
  includeArg := '';
  pythonForChecks := 'python';
  hasExistingVenv := FileExists(venvPython);
  skipRebuild := False;
  needsRebuild := False;

  if IsEmbeddedMode() then
  begin
    includeArg := ' --include-venv';
    if not hasExistingVenv then
    begin
      MsgBox('Bundled virtual environment was not found. Cannot continue in embedded mode.', mbError, MB_OK);
      exit;
    end;

    venvMatches := VenvMeetsRequirements(venvPython);
    if venvMatches then
    begin
      response := MsgBox(
        'An existing virtual environment was found and appears to meet requirements.' + #13#10 +
        'Skip rebuilding it and reuse as-is?',
        mbConfirmation, MB_YESNO or MB_DEFBUTTON2);
      if response = IDYES then
        skipRebuild := True;
    end
    else
    begin
      response := MsgBox(
        'The bundled virtual environment appears outdated or missing dependencies.' + #13#10 +
        'Rebuild it now using the bundled environment?',
        mbConfirmation, MB_YESNO or MB_DEFBUTTON1);
      if response <> IDYES then
      begin
        MsgBox('Installation cannot continue without a valid virtual environment.', mbError, MB_OK);
        exit;
      end;
    end;

    pythonForChecks := venvPython;
    pythonCheckCmd := '-c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"';
    if not RunAndCheck(venvPython, pythonCheckCmd, '', 'Bundled Python 3.10+ check') then
      exit;
  end
  else if IsBuildMode() then
  begin
    if hasExistingVenv then
    begin
      venvMatches := VenvMeetsRequirements(venvPython);
      if venvMatches then
      begin
        response := MsgBox(
          'An existing virtual environment was found and appears to meet requirements.' + #13#10 +
          'Skip rebuilding it and reuse as-is?',
          mbConfirmation, MB_YESNO or MB_DEFBUTTON2);
        if response = IDYES then
        begin
          skipRebuild := True;
          pythonForChecks := venvPython;
        end;
      end;

      if (not venvMatches) or (not skipRebuild) then
        needsRebuild := True;
    end
    else
      needsRebuild := True;

    if needsRebuild then
    begin
      pythonCheckCmd := '-c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"';
      if not RunAndCheck('python', pythonCheckCmd, '', 'System Python 3.10+ check') then
        exit;

      WizardForm.StatusLabel.Caption := 'Creating virtual environment...';
      WizardForm.ProgressGauge.Max := 3;
      WizardForm.ProgressGauge.Position := 1;
      WizardForm.ProgressGauge.Update;

      if not RunAndCheck('python', Format('-m venv "%s"', [appRoot + '\EDMCModernOverlay\overlay_client\.venv']), '', 'Virtual environment creation (system Python)') then
        exit;

      if not FileExists(venvPython) then
      begin
        MsgBox('Virtual environment python.exe not found after creation.', mbError, MB_OK);
        exit;
      end;

      pythonForChecks := venvPython;

      WizardForm.StatusLabel.Caption := 'Installing dependencies (online)...';
      WizardForm.ProgressGauge.Position := 2;
      WizardForm.ProgressGauge.Update;

      if not RunAndCheck(venvPython, '-m pip install --upgrade pip', '', 'Dependency installation (online)') then
        exit;

      if not RunAndCheck(venvPython, '-m pip install PyQt6>=6.5', '', 'Dependency installation (online)') then
        exit;
    end
    else
      pythonForChecks := venvPython;
  end
  else
  begin
    MsgBox(Format('Unknown InstallVenvMode: %s', [InstallVenvMode]), mbError, MB_OK);
    exit;
  end;

  if FileExists(payloadManifest) then
  begin
    if not RunAndCheck(pythonForChecks, Format('"%s" --verify --root "%s" --manifest "%s" --excludes "%s" --skip "EDMCModernOverlay"', [checksumScriptPath, ExpandConstant('{tmp}'), payloadManifest, excludesPath]), '', 'Payload checksum validation') then
      exit;
  end;

  if not RunAndCheck(pythonForChecks, Format('"%s" --verify --root "%s" --manifest "%s" --excludes "%s"%s', [checksumScriptPath, appRoot, manifest, excludesPath, includeArg]), '', 'Checksum validation') then
    exit;

  if WizardIsTaskSelected('font') then
  begin
    fontPath := GetFontTempPath();
    if FileExists(fontPath) then
      CopyFile(fontPath, ExpandConstant('{autofonts}') + '\Eurocaps.ttf', False);
  end;
end;
