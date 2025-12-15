#ifndef PayloadRoot
  #define PayloadRoot "dist\\inno_payload"
#endif

#ifndef OutputDir
  #define OutputDir "dist\\inno_output"
#endif

#ifndef AppVersion
  #define AppVersion "dev"
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
OutputDir={#OutputDir}
OutputBaseFilename=EDMCModernOverlay-setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
CloseApplications=yes
RestartApplications=no
Uninstallable=no

[Tasks]
Name: "font"; Description: "Install Eurocaps font"; Flags: unchecked

[Files]
; Plugin payload
Source: "{#PayloadRoot}\EDMCModernOverlay\*"; DestDir: "{app}\EDMCModernOverlay"; Flags: ignoreversion recursesubdirs
; Bundled assets staged to temp
Source: "{#PayloadRoot}\wheels\*"; DestDir: "{tmp}\wheels"; Flags: ignoreversion recursesubdirs deleteafterinstall
Source: "{#PayloadRoot}\tools\generate_checksums.py"; DestDir: "{tmp}\tools"; Flags: ignoreversion deleteafterinstall
Source: "{#PayloadRoot}\tools\release_excludes.json"; DestDir: "{tmp}\tools"; Flags: ignoreversion deleteafterinstall
Source: "{#PayloadRoot}\checksums_payload.txt"; DestDir: "{tmp}"; Flags: ignoreversion deleteafterinstall
Source: "{#PayloadRoot}\extras\font\Eurocaps.ttf"; DestDir: "{tmp}\extras\font"; Flags: ignoreversion deleteafterinstall; Tasks: font

[Code]
const
  ChecksumScript = '\tools\generate_checksums.py';
  ExcludesFile = '\tools\release_excludes.json';
  WheelsDir = '\wheels';
  FontFile = '\extras\font\Eurocaps.ttf';

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

function DisableDirIfExists(const DirPath: string): Boolean;
var
  target: string;
  idx: Integer;
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
    Result := RenameFile(DirPath, target);
    if not Result then
      MsgBox(Format('Failed to rename "%s". Please close any programs using it.', [DirPath]), mbError, MB_OK);
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
    legacy2 := pluginRoot + '\EDMCModernOverlay';
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

function GetPythonPath(): string;
begin
  Result := ExpandConstant('{tmp}') + WheelsDir;
end;

function GetChecksumScriptPath(): string;
begin
  Result := ExpandConstant('{tmp}') + ChecksumScript;
end;

function GetExcludesPath(): string;
begin
  Result := ExpandConstant('{tmp}') + ExcludesFile;
end;

function GetWheelsPath(): string;
begin
  Result := ExpandConstant('{tmp}') + WheelsDir;
end;

function GetFontTempPath(): string;
begin
  Result := ExpandConstant('{tmp}') + FontFile;
end;

function GetPayloadManifestPath(): string;
begin
  Result := ExpandConstant('{tmp}') + '\checksums_payload.txt';
end;

function FindPipWheel(): string;
var
  rec: TFindRec;
begin
  Result := '';
  if FindFirst(ExpandConstant('{tmp}') + '\wheels\pip*.whl', rec) then
  begin
    Result := ExpandConstant('{tmp}') + '\wheels\' + rec.Name;
    FindClose(rec);
  end;
end;

function GetVenvPython(): string;
begin
  Result := ExpandConstant('{app}') + '\EDMCModernOverlay\overlay_client\.venv\Scripts\python.exe';
end;

function GetRequirementsFile(): string;
begin
  Result := ExpandConstant('{app}') + '\EDMCModernOverlay\overlay_client\requirements\base.txt';
end;

function GetChecksumManifest(): string;
begin
  Result := ExpandConstant('{app}') + '\EDMCModernOverlay\checksums.txt';
end;

procedure PerformPostInstallTasks;
var
  wheels, checksumScriptPath, manifest, appRoot, venvPython, reqFile, fontPath: string;
  excludesPath, payloadManifest: string;
  pipWheel: string;
  venvCreated: Boolean;
begin
  wheels := GetWheelsPath();
  checksumScriptPath := GetChecksumScriptPath();
  excludesPath := GetExcludesPath();
  payloadManifest := GetPayloadManifestPath();
  manifest := GetChecksumManifest();
  appRoot := ExpandConstant('{app}');
  if not RunAndCheck('python', '-c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"', '', 'Python 3.10+ check (system)') then
    exit;

  if FileExists(payloadManifest) then
  begin
    if not RunAndCheck('python', Format('"%s" --verify --root "%s" --manifest "%s" --excludes "%s" --skip "EDMCModernOverlay"', [checksumScriptPath, ExpandConstant('{tmp}'), payloadManifest, excludesPath]), '', 'Payload checksum validation') then
      exit;
  end;

  if not RunAndCheck('python', Format('"%s" --verify --root "%s" --manifest "%s" --excludes "%s"', [checksumScriptPath, appRoot, manifest, excludesPath]), '', 'Checksum validation') then
    exit;

  venvCreated := RunAndCheck('python', Format('-m venv "%s"', [appRoot + '\EDMCModernOverlay\overlay_client\.venv']), '', 'Virtual environment creation (system Python)');
  if not venvCreated then
    exit;

  venvPython := GetVenvPython();
  reqFile := GetRequirementsFile();
  if not FileExists(venvPython) then
  begin
    MsgBox('Virtual environment python.exe not found after creation.', mbError, MB_OK);
    exit;
  end;

  pipWheel := FindPipWheel();
  if pipWheel <> '' then
  begin
    if not RunAndCheck(venvPython,
      Format('-m pip install --no-index --find-links "%s" "%s"', [wheels, pipWheel]),
      '', 'Pip bootstrap') then
      exit;
  end;

  if not RunAndCheck(venvPython,
     Format('-m pip install --no-index --find-links "%s" -r "%s"', [wheels, reqFile]),
     '', 'Dependency installation') then
    exit;

  if WizardIsTaskSelected('font') then
  begin
    fontPath := GetFontTempPath();
    if FileExists(fontPath) then
      CopyFile(fontPath, ExpandConstant('{autofonts}') + '\Eurocaps.ttf', False);
  end;
end;
