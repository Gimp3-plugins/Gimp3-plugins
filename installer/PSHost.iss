; PSHost - Inno Setup script. Per-user installer (no administrator rights), Polish / English.
;   ISCC.exe /DAppVersion=0.8.0 /DBuildDir=..\build PSHost.iss      ->  installer\output\PSHost-Setup-0.8.0.exe
; Command line switches of the installer (besides the standard Inno ones):
;   /GIMPDATA="C:\...\GIMP\3.2"   install for this GIMP user-data directory (skips GIMP detection; used by tests)
; /NOGIMPDETECT                  (tests) ignore installed GIMP versions
;   /PURGE                        silent uninstall also removes the PSHost configuration (config.json, logs, parameters)

#ifndef AppVersion
  #define AppVersion "0.8.0"
#endif
#ifndef BuildDir
  #define BuildDir "..\build"
#endif

[Setup]
AppId={{D65CF174-798E-4A08-9E8C-B837FE95990B}
AppName=PSHost
AppVersion={#AppVersion}
AppVerName=PSHost {#AppVersion}
AppPublisher=PSHost
AppComments=Host for 64-bit Photoshop (.8bf) filter plug-ins in GIMP 3
VersionInfoVersion={#AppVersion}.0
VersionInfoProductName=PSHost
VersionInfoDescription=PSHost installer
VersionInfoCompany=PSHost
DefaultDirName={code:GetPluginDir}
UsePreviousAppDir=no
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=output
OutputBaseFilename=PSHost-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallFilesDir={localappdata}\PSHost
UninstallDisplayName=PSHost {#AppVersion}
CloseApplications=no
ShowLanguageDialog=auto

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"; InfoAfterFile: "info_en.txt"
Name: "polish"; MessagesFile: "compiler:Languages\Polish.isl"; InfoAfterFile: "info_pl.txt"

[Files]
Source: "{#BuildDir}\pshost.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#BuildDir}\pshost_runner.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#BuildDir}\locale\*"; DestDir: "{app}\locale"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; clean leftovers of older versions before copying
Type: filesandordirs; Name: "{app}\locale"

[Registry]
Root: HKCU; Subkey: "Software\PSHost"; ValueType: string; ValueName: "DataDir"; ValueData: "{code:GetDataDir}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\PSHost"; ValueType: string; ValueName: "Version"; ValueData: "{#AppVersion}"; Flags: uninsdeletekey

[UninstallDelete]
Type: dirifempty; Name: "{app}"

[CustomMessages]
english.GimpFolder=GIMP 3 folder:
english.GimpPageTitle=GIMP 3 not found
english.GimpPageDesc=Choose the folder where GIMP 3 is installed.
english.GimpPageSub=Setup could not find GIMP 3 automatically. PSHost works only with GIMP 3 (not with GIMP 2). Select the GIMP 3 installation folder (the one that contains the "bin" folder), or cancel and install GIMP 3 first.
english.GimpPageSubGimp2=Setup found GIMP 2, but this plug-in works only with GIMP 3. Install GIMP 3, or select its folder below if it is installed in an unusual place.
english.GimpInvalid=This folder does not look like a GIMP 3 installation (bin\gimp-3.x.exe was not found).
english.NoGimpSilent=GIMP 3 was not found. Install GIMP 3 first or use /GIMPDATA="path\to\GIMP\3.x".
english.OldGimp=GIMP %1 was found. PSHost was built and tested with GIMP 3.2, so it may not work with this version. Install anyway?
english.CloseGimp=GIMP is running. Close GIMP, then click Retry. (Cancel stops the setup.)
english.CloseGimpAbort=Setup was cancelled because GIMP is running.
english.ReadyGimp=GIMP %1 in: %2
english.ReadyData=The plug-in will be installed in:
english.PurgeConfig=Also delete the PSHost settings and scan results (config.json, logs, saved filter parameters)?
polish.GimpFolder=Folder GIMP-a 3:
polish.GimpPageTitle=Nie znaleziono GIMP-a 3
polish.GimpPageDesc=Wskaż folder, w którym zainstalowano GIMP-a 3.
polish.GimpPageSub=Instalator nie znalazł GIMP-a 3 automatycznie. PSHost działa tylko z GIMP-em 3 (nie z GIMP-em 2). Wybierz folder instalacji GIMP-a 3 (ten, który zawiera folder „bin”) albo anuluj i najpierw zainstaluj GIMP-a 3.
polish.GimpPageSubGimp2=Instalator znalazł GIMP-a 2, ale ta wtyczka działa tylko z GIMP-em 3. Zainstaluj GIMP-a 3 albo wskaż poniżej jego folder, jeśli jest w nietypowym miejscu.
polish.GimpInvalid=Ten folder nie wygląda na instalację GIMP-a 3 (nie znaleziono bin\gimp-3.x.exe).
polish.NoGimpSilent=Nie znaleziono GIMP-a 3. Zainstaluj najpierw GIMP-a 3 lub użyj /GIMPDATA="ścieżka\do\GIMP\3.x".
polish.OldGimp=Znaleziono GIMP-a %1. PSHost został zbudowany i przetestowany z GIMP-em 3.2, więc z tą wersją może nie działać. Zainstalować mimo to?
polish.CloseGimp=GIMP jest uruchomiony. Zamknij GIMP-a i kliknij Ponów. (Anuluj przerywa instalację.)
polish.CloseGimpAbort=Instalację przerwano, ponieważ GIMP jest uruchomiony.
polish.ReadyGimp=GIMP %1 w: %2
polish.ReadyData=Wtyczka zostanie zainstalowana w:
polish.PurgeConfig=Usunąć też ustawienia PSHost i wyniki skanowania (config.json, logi, zapisane parametry filtrów)?

[Code]
var
  GimpDir, GimpVer, DataDir: String;
  Gimp3Found, Gimp2Found, DataDirForced: Boolean;
  GimpPage: TInputDirWizardPage;

{ ---------- helpers ---------- }
function CmdSwitch(const Name: String): Boolean;
var I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), Name) = 0 then Result := True;
end;

function FirstGimp3Exe(const Dir: String): String;      { returns e.g. "gimp-3.2.exe" or '' }
var R: TFindRec;
begin
  Result := '';
  if FindFirst(AddBackslash(Dir) + 'bin\gimp-3.*.exe', R) then
  try
    Result := R.Name;
  finally
    FindClose(R);
  end;
end;

function VersionFromExeName(const Name: String): String; { "gimp-3.2.exe" -> "3.2" }
begin
  Result := Copy(Name, 6, Length(Name) - 5 - 4);
end;

function IsGimp3Dir(const Dir: String): Boolean;
begin
  Result := (Dir <> '') and (FirstGimp3Exe(Dir) <> '');
end;

procedure SetGimp(const Dir: String);
begin
  GimpDir := RemoveBackslash(Dir);
  GimpVer := VersionFromExeName(FirstGimp3Exe(Dir));
  DataDir := ExpandConstant('{userappdata}\GIMP\') + GimpVer;
  Gimp3Found := True;
end;

procedure ScanUninstall(Root: Integer);
var
  Keys: TArrayOfString;
  I: Integer;
  Base, Name, Loc: String;
begin
  Base := 'Software\Microsoft\Windows\CurrentVersion\Uninstall';
  if not RegGetSubkeyNames(Root, Base, Keys) then Exit;
  for I := 0 to GetArrayLength(Keys) - 1 do
    if RegQueryStringValue(Root, Base + '\' + Keys[I], 'DisplayName', Name) then
    begin
      if (Pos('GIMP 3', Name) = 1) and (not Gimp3Found) then
      begin
        if RegQueryStringValue(Root, Base + '\' + Keys[I], 'InstallLocation', Loc) and IsGimp3Dir(Loc) then
          SetGimp(Loc);
      end
      else if Pos('GIMP 2', Name) = 1 then
        Gimp2Found := True;
    end;
end;

procedure DetectGimp;
begin
  if CmdSwitch('/NOGIMPDETECT') then Exit;      { test switch: behave as if GIMP 3 were not installed }
  ScanUninstall(HKCU);
  if not Gimp3Found then ScanUninstall(HKLM64);
  if not Gimp3Found then ScanUninstall(HKLM32);
  { typical locations, used when the uninstall entry is missing }
  if (not Gimp3Found) and IsGimp3Dir(ExpandConstant('{localappdata}\Programs\GIMP 3')) then SetGimp(ExpandConstant('{localappdata}\Programs\GIMP 3'));
  if (not Gimp3Found) and IsGimp3Dir(ExpandConstant('{commonpf64}\GIMP 3')) then SetGimp(ExpandConstant('{commonpf64}\GIMP 3'));
  if (not Gimp2Found) and (DirExists(ExpandConstant('{commonpf64}\GIMP 2')) or DirExists(ExpandConstant('{commonpf32}\GIMP 2')) or DirExists(ExpandConstant('{localappdata}\Programs\GIMP 2'))) then
    Gimp2Found := True;
end;

function MajorMinorNumber(const V: String): Integer;    { "3.2" -> 302 }
var P: Integer;
begin
  P := Pos('.', V);
  if P = 0 then Result := StrToIntDef(V, 0) * 100
  else Result := StrToIntDef(Copy(V, 1, P - 1), 0) * 100 + StrToIntDef(Copy(V, P + 1, 3), 0);
end;

function GimpProcessFilter: String;                       { default "gimp-*"; tests override it with PSHOST_GIMP_PROCESS }
begin
  Result := GetEnv('PSHOST_GIMP_PROCESS');
  if Result = '' then Result := 'gimp-*';
end;

function GimpRunning: Boolean;
var
  Tmp, S: AnsiString;
  Filter, Prefix: String;
  RC: Integer;
begin
  Result := False;
  Filter := GimpProcessFilter;
  Prefix := LowerCase(Filter);
  if (Length(Prefix) > 0) and (Prefix[Length(Prefix)] = '*') then Delete(Prefix, Length(Prefix), 1);
  Tmp := ExpandConstant('{tmp}\gimp_ps.txt');
  if Exec(ExpandConstant('{cmd}'), '/C tasklist /FI "IMAGENAME eq ' + Filter + '" /NH > "' + Tmp + '"', '', SW_HIDE, ewWaitUntilTerminated, RC) then
    if LoadStringFromFile(Tmp, S) then
      Result := Pos(Prefix, LowerCase(S)) > 0;
end;

function EnsureGimpClosed: Boolean;
begin
  Result := True;
  while GimpRunning do
    if SuppressibleMsgBox(CustomMessage('CloseGimp'), mbError, MB_RETRYCANCEL, IDCANCEL) = IDCANCEL then
    begin
      Result := False;
      Exit;
    end;
end;

{ ---------- values used by [Setup] / [Registry] ---------- }
function GetDataDir(Param: String): String;
begin
  Result := DataDir;
end;

function GetPluginDir(Param: String): String;
begin
  if DataDir = '' then Result := ExpandConstant('{userappdata}\GIMP\3.2\plug-ins\pshost')
  else Result := AddBackslash(DataDir) + 'plug-ins\pshost';
end;

{ ---------- wizard ---------- }
function InitializeSetup: Boolean;
var Forced: String;
begin
  Result := True;
  Forced := ExpandConstant('{param:GIMPDATA|}');
  if Forced <> '' then
  begin
    DataDir := RemoveBackslash(Forced);
    DataDirForced := True;
    Gimp3Found := True;
    GimpVer := ExtractFileName(DataDir);
    Exit;
  end;
  DetectGimp;
  if Gimp3Found then Log('PSHost: GIMP 3 detected: dir=' + GimpDir + ' version=' + GimpVer + ' userdata=' + DataDir)
  else Log('PSHost: GIMP 3 not detected; GIMP 2 present=' + IntToStr(Ord(Gimp2Found)));
  if (not Gimp3Found) and WizardSilent then
  begin
    SuppressibleMsgBox(CustomMessage('NoGimpSilent'), mbError, MB_OK, IDOK);
    Result := False;
  end;
end;

procedure InitializeWizard;
begin
  if not Gimp3Found then
  begin
    GimpPage := CreateInputDirPage(wpWelcome, CustomMessage('GimpPageTitle'), CustomMessage('GimpPageDesc'),
      CustomMessage('GimpPageSub'), False, '');
    if Gimp2Found then GimpPage.SubCaptionLabel.Caption := CustomMessage('GimpPageSubGimp2');
    GimpPage.Add(CustomMessage('GimpFolder'));
    GimpPage.Values[0] := ExpandConstant('{localappdata}\Programs\GIMP 3');
  end;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (GimpPage <> nil) and (PageID = GimpPage.ID) and Gimp3Found;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (GimpPage <> nil) and (CurPageID = GimpPage.ID) and (not Gimp3Found) then
  begin
    if not IsGimp3Dir(GimpPage.Values[0]) then
    begin
      MsgBox(CustomMessage('GimpInvalid'), mbError, MB_OK);
      Result := False;
      Exit;
    end;
    SetGimp(GimpPage.Values[0]);
  end;
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo, MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := '';
  if not DataDirForced then
    Result := FmtMessage(CustomMessage('ReadyGimp'), [GimpVer, GimpDir]) + NewLine + NewLine;
  Result := Result + CustomMessage('ReadyData') + NewLine + Space + GetPluginDir('');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  WizardForm.DirEdit.Text := GetPluginDir('');
  if (not DataDirForced) and (MajorMinorNumber(GimpVer) < 302) then
    if SuppressibleMsgBox(FmtMessage(CustomMessage('OldGimp'), [GimpVer]), mbConfirmation, MB_YESNO, IDYES) = IDNO then
    begin
      Result := CustomMessage('CloseGimpAbort');
      Exit;
    end;
  if not EnsureGimpClosed then
    Result := CustomMessage('CloseGimpAbort');
end;

{ ---------- uninstall ---------- }
var
  UninstDataDir: String;

function InitializeUninstall: Boolean;
begin
  Result := EnsureGimpClosed;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var Dir: String;
begin
  { the registry key is deleted during usUninstall, so read the data directory first }
  if CurUninstallStep = usUninstall then
  begin
    if not RegQueryStringValue(HKCU, 'Software\PSHost', 'DataDir', UninstDataDir) then UninstDataDir := '';
  end
  else if CurUninstallStep = usPostUninstall then
  begin
    if UninstDataDir = '' then Exit;
    Dir := AddBackslash(UninstDataDir) + 'pshost';           { config.json, logs, params }
    if DirExists(Dir) then
    begin
      if UninstallSilent then
      begin
        if CmdSwitch('/PURGE') then DelTree(Dir, True, True, True);     { silent: keep settings unless /PURGE }
      end
      else if MsgBox(CustomMessage('PurgeConfig'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(Dir, True, True, True);
    end;
  end;
end;
