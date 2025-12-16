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

function GetChecksumManifest(): string;
begin
  Result := ExpandConstant('{app}') + '\EDMCModernOverlay\checksums.txt';
end;

function GetBundledPython(): string;
begin
  Result := ExpandConstant('{tmp}') + '\python\python.exe';
end;

function GetBundledWheels(): string;
begin
  Result := ExpandConstant('{tmp}') + '\wheels';
end;

procedure PerformPostInstallTasks;
var
  checksumScriptPath, manifest, appRoot, venvPython, fontPath: string;
  excludesPath, payloadManifest, bundledPython: string;
  pythonCheckCmd: string;
begin
  checksumScriptPath := GetChecksumScriptPath();
  excludesPath := GetExcludesPath();
  payloadManifest := GetPayloadManifestPath();
  manifest := GetChecksumManifest();
  appRoot := ExpandConstant('{app}');
  venvPython := GetVenvPython();
  if not FileExists(venvPython) then
  begin
    MsgBox('Bundled virtual environment python.exe not found.', mbError, MB_OK);
    exit;
  end;

  pythonCheckCmd := '-c "import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)"';
  if not RunAndCheck(venvPython, pythonCheckCmd, '', 'Bundled Python 3.12+ check') then
    exit;

  if FileExists(payloadManifest) then
  begin
    if not RunAndCheck(venvPython, Format('"%s" --verify --root "%s" --manifest "%s" --excludes "%s" --skip "EDMCModernOverlay"', [checksumScriptPath, ExpandConstant('{tmp}'), payloadManifest, excludesPath]), '', 'Payload checksum validation') then
      exit;
  end;

  if not RunAndCheck(venvPython, Format('"%s" --verify --root "%s" --manifest "%s" --excludes "%s" --include-venv', [checksumScriptPath, appRoot, manifest, excludesPath]), '', 'Checksum validation') then
    exit;

  if WizardIsTaskSelected('font') then
  begin
    fontPath := GetFontTempPath();
    if FileExists(fontPath) then
      CopyFile(fontPath, ExpandConstant('{autofonts}') + '\Eurocaps.ttf', False);
  end;
end;
