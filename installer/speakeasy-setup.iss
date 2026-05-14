; ─────────────────────────────────────────────────────────────────────────────
; SpeakEasy AI v3 Inno Setup Installer Script
;
; Produces a single versioned SpeakEasy-AI-Granite-Setup executable that handles:
;   - File extraction (from PyInstaller dist/speakeasy/ output)
;   - IBM Granite Speech model download (public — no token required)
;   - Desktop + Start Menu shortcuts
;   - Data migration from previous installs
;   - Windows Defender process exclusion (exe only — not the whole directory)
;   - Silent / unattended mode
;
; Build:
;   pyinstaller speakeasy.spec
;   iscc installer\speakeasy-setup.iss
;
; Requires Inno Setup 6.x — https://jrsoftware.org/isdl.php
; ─────────────────────────────────────────────────────────────────────────────

#define MyAppName "SpeakEasy AI Granite"
#define MyAppVersion "0.14.0"
#define MyAppPublisher "kwp490"
#define MyAppURL "https://github.com/kwp490/speakeasy-granite"
#define MyAppExeName "speakeasy.exe"

[Setup]
AppId={{7B99C492-7E14-4E3A-A8F2-71F8B23D9A42}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
DefaultDirName={autopf}\SpeakEasy AI Granite
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=Output
OutputBaseFilename=SpeakEasy-AI-Granite-Setup-{#MyAppVersion}
#ifdef FastCompress
Compression=lzma2/fast
SolidCompression=no
LZMANumBlockThreads=8
#else
Compression=lzma2/ultra64
SolidCompression=yes
#endif
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#MyAppName}
MinVersion=10.0
SetupLogging=yes
SetupIconFile=..\speakeasy\assets\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
WelcomeLabel2=SpeakEasy AI Granite delivers local transcription and speech translation on Windows — powered by IBM Granite Speech 4.1 2B.%n%nSetup will install the application, download the Granite speech model (~4.6 GB), and configure everything automatically. This takes several minutes depending on your connection.%n%nRequirements: ~5 GB free disk space, NVIDIA GPU with 6 GB VRAM (8 GB recommended). CPU fallback is available but will be slow.

[Files]
Source: "..\dist\speakeasy\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "granite-model-setup.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{commonappdata}\SpeakEasy AI Granite";              Permissions: users-modify
Name: "{commonappdata}\SpeakEasy AI Granite\models";       Permissions: users-modify
Name: "{commonappdata}\SpeakEasy AI Granite\config";       Permissions: users-modify
Name: "{commonappdata}\SpeakEasy AI Granite\temp";         Permissions: users-modify

[Icons]
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
    WorkingDir: "{app}"; IconFilename: "{app}\{#MyAppExeName}"; Comment: "SpeakEasy AI — Voice to Text"
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
    WorkingDir: "{app}"; IconFilename: "{app}\{#MyAppExeName}"; Comment: "SpeakEasy AI — Voice to Text"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
Filename: "powershell.exe"; \
    Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""Add-MpPreference -ExclusionProcess '{app}\{#MyAppExeName}' -ErrorAction SilentlyContinue"""; \
    Flags: runhidden waituntilterminated; StatusMsg: "Configuring Windows Defender exclusions..."

Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; \
    Flags: nowait postinstall skipifsilent; WorkingDir: "{app}"

[UninstallDelete]
Type: filesandordirs; Name: "{commonappdata}\SpeakEasy AI Granite\temp"
Type: filesandordirs; Name: "{commonappdata}\SpeakEasy AI Granite\config"

[UninstallRun]
Filename: "powershell.exe"; \
    Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""Remove-MpPreference -ExclusionProcess '{app}\{#MyAppExeName}' -ErrorAction SilentlyContinue"""; \
    Flags: runhidden waituntilterminated; RunOnceId: "DefenderExclusions"

[Code]
var
  TokenPage: TWizardPage;
  TokenLblHeader: TNewStaticText;
  TokenLblSteps: TNewStaticText;
  ModelFoundHeader: TNewStaticText;
  ModelFoundNote: TNewStaticText;
  GpuInfoLabel: TNewStaticText;
  DownloadPage: TOutputProgressWizardPage;
  SummaryPage: TWizardPage;
  SummaryMemo: TNewMemo;
  DetectedGPU: String;
  DetectedGPU_Name: String;
  DetectedVRAM_MB: Integer;
  CleanInstall: Boolean;
  ModelExists: Boolean;

function SetEnvironmentVariable(Name, Value: String): Boolean;
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';

{ Called before file extraction.  Detects an existing install and cleans
  config/temp so upgrades always start with fresh settings.
  Silent mode: auto-clean.  Interactive mode: prompt Clean vs Repair.
  Models are always preserved. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  AppDir, ConfigDir, TempDir: String;
  DoClean: Boolean;
  ButtonLabels: TArrayOfString;
begin
  Result := '';
  CleanInstall := False;
  AppDir   := ExpandConstant('{app}');
  ConfigDir := ExpandConstant('{commonappdata}') + '\SpeakEasy AI\config';
  TempDir   := ExpandConstant('{commonappdata}') + '\SpeakEasy AI\temp';

  { Only act if there is an existing install with a config directory }
  if not DirExists(ConfigDir) then
    Exit;

  if WizardSilent then
    DoClean := True
  else
  begin
    SetArrayLength(ButtonLabels, 2);
    ButtonLabels[0] := 'Clean Install';
    ButtonLabels[1] := 'Repair Install';
    DoClean := (TaskDialogMsgBox('An existing SpeakEasy AI installation was detected.',
                        'Clean Install — remove old settings and temp files (recommended).' + #13#10 +
                        'Repair Install — keep existing settings and overwrite application files only.',
                        mbConfirmation, MB_YESNO, ButtonLabels, 0) = IDYES);
  end;

  if DoClean then
  begin
    CleanInstall := True;
    DelTree(ConfigDir, True, True, True);
    DelTree(TempDir,  True, True, True);
  end;
end;

function DetectGPU: String;
var
  ResultCode: Integer;
  TempFile: String;
  Lines: TArrayOfString;
  Raw, Token: String;
  CommaPos: Integer;
begin
  Result := '';
  DetectedGPU_Name := '';
  DetectedVRAM_MB := 0;
  TempFile := ExpandConstant('{tmp}\gpu_detect.txt');
  if Exec('cmd.exe',
      '/C nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits > "' + TempFile + '" 2>&1',
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    if (ResultCode = 0) and LoadStringsFromFile(TempFile, Lines) then
    begin
      if GetArrayLength(Lines) > 0 then
      begin
        Raw := Trim(Lines[0]);
        Result := Raw;
        CommaPos := Pos(',', Raw);
        if CommaPos > 0 then
        begin
          DetectedGPU_Name := Trim(Copy(Raw, 1, CommaPos - 1));
          Token := Trim(Copy(Raw, CommaPos + 1, Length(Raw)));
          DetectedVRAM_MB := StrToIntDef(Token, 0);
        end else
          DetectedGPU_Name := Raw;
      end;
    end;
  end;
  DeleteFile(TempFile);
end;

function FormatVRAM_GB(MB: Integer): String;
var
  GB_Whole, GB_Frac: Integer;
begin
  GB_Whole := MB div 1024;
  GB_Frac  := ((MB mod 1024) * 10) div 1024;
  Result := IntToStr(GB_Whole) + '.' + IntToStr(GB_Frac) + ' GB';
end;

procedure CreateTokenPage;
var
  Lbl: TNewStaticText;
  TopPos, TokenTop: Integer;
begin
  TokenPage := CreateCustomPage(wpSelectDir,
    'Model Download',
    'The IBM Granite Speech model will be downloaded automatically after installation.');

  DetectedGPU := DetectGPU;
  TopPos := 0;

  { -- GPU info (always visible) -- }
  Lbl := TNewStaticText.Create(TokenPage);
  Lbl.Parent := TokenPage.Surface;
  Lbl.Left := 0;  Lbl.Top := TopPos;
  Lbl.Width := TokenPage.SurfaceWidth;
  Lbl.Caption := 'Your GPU';
  Lbl.Font.Style := [fsBold];  Lbl.Font.Size := 9;
  TopPos := TopPos + ScaleY(18);

  GpuInfoLabel := TNewStaticText.Create(TokenPage);
  GpuInfoLabel.Parent := TokenPage.Surface;
  GpuInfoLabel.Left := ScaleX(8);  GpuInfoLabel.Top := TopPos;
  GpuInfoLabel.Width := TokenPage.SurfaceWidth - ScaleX(8);
  GpuInfoLabel.AutoSize := False;  GpuInfoLabel.WordWrap := True;

  if DetectedGPU <> '' then
  begin
    if DetectedVRAM_MB > 0 then
      GpuInfoLabel.Caption := DetectedGPU_Name + '  —  ' + FormatVRAM_GB(DetectedVRAM_MB) + ' VRAM'
    else
      GpuInfoLabel.Caption := DetectedGPU_Name;
    GpuInfoLabel.Height := ScaleY(18);
  end else
  begin
    GpuInfoLabel.Caption := 'No NVIDIA GPU detected. Transcription will use CPU (slower).';
    GpuInfoLabel.Height := ScaleY(18);
  end;
  TopPos := TopPos + GpuInfoLabel.Height + ScaleY(4);

  if DetectedGPU <> '' then
  begin
    Lbl := TNewStaticText.Create(TokenPage);
    Lbl.Parent := TokenPage.Surface;
    Lbl.Left := ScaleX(16);  Lbl.Top := TopPos;
    Lbl.Width := TokenPage.SurfaceWidth - ScaleX(16);
    if DetectedVRAM_MB >= 6144 then
    begin
      Lbl.Caption := #$2713 + '  IBM Granite Speech GPU mode selected — your GPU appears to have enough VRAM';
      Lbl.Font.Color := clGreen;
    end else
    begin
      Lbl.Caption := #$2717 + '  IBM Granite Speech may need more VRAM than detected (CPU fallback available)';
      Lbl.Font.Color := $0000C0;
    end;
    TopPos := TopPos + ScaleY(18);
  end;

  TopPos := TopPos + ScaleY(12);

  { Remember where the swappable section starts }
  TokenTop := TopPos;

  { -- Download-info section (hidden when model exists) -- }
  TokenLblHeader := TNewStaticText.Create(TokenPage);
  TokenLblHeader.Parent := TokenPage.Surface;
  TokenLblHeader.Left := 0;  TokenLblHeader.Top := TopPos;
  TokenLblHeader.Width := TokenPage.SurfaceWidth;
  TokenLblHeader.Caption := 'IBM Granite Speech Model';
  TokenLblHeader.Font.Style := [fsBold];  TokenLblHeader.Font.Size := 9;
  TopPos := TopPos + ScaleY(22);

  TokenLblSteps := TNewStaticText.Create(TokenPage);
  TokenLblSteps.Parent := TokenPage.Surface;
  TokenLblSteps.Left := ScaleX(8);  TokenLblSteps.Top := TopPos;
  TokenLblSteps.Width := TokenPage.SurfaceWidth - ScaleX(8);
  TokenLblSteps.AutoSize := False;  TokenLblSteps.WordWrap := True;  TokenLblSteps.Height := ScaleY(72);
  TokenLblSteps.Caption := 'The IBM Granite Speech model is public and will be downloaded automatically.' + #13#10 +
                 'No HuggingFace account or access token is required.' + #13#10 + #13#10 +
                 'Model page: https://huggingface.co/ibm-granite/granite-speech-4.1-2b';
  TokenLblSteps.Font.Color := $808080;

  { -- Model-found section (hidden when model does not exist) -- }
  TopPos := TokenTop;

  ModelFoundHeader := TNewStaticText.Create(TokenPage);
  ModelFoundHeader.Parent := TokenPage.Surface;
  ModelFoundHeader.Left := 0;  ModelFoundHeader.Top := TopPos;
  ModelFoundHeader.Width := TokenPage.SurfaceWidth;
  ModelFoundHeader.Caption := #$2713 + '  IBM Granite Speech model already installed';
  ModelFoundHeader.Font.Style := [fsBold];  ModelFoundHeader.Font.Size := 10;
  ModelFoundHeader.Font.Color := clGreen;
  ModelFoundHeader.Visible := False;
  TopPos := TopPos + ScaleY(28);

  ModelFoundNote := TNewStaticText.Create(TokenPage);
  ModelFoundNote.Parent := TokenPage.Surface;
  ModelFoundNote.Left := ScaleX(8);  ModelFoundNote.Top := TopPos;
  ModelFoundNote.Width := TokenPage.SurfaceWidth - ScaleX(16);
  ModelFoundNote.AutoSize := False;  ModelFoundNote.WordWrap := True;  ModelFoundNote.Height := ScaleY(72);
  ModelFoundNote.Caption := 'The IBM Granite Speech model was found in your existing installation.' + #13#10 + #13#10 +
                 'The model will be preserved during this upgrade — no download is needed.' + #13#10 +
                 'Click Next to continue.';
  ModelFoundNote.Font.Color := $808080;
  ModelFoundNote.Visible := False;
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo,
  MemoTypeInfo, MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
var
  Info: String;
begin
  Info := '';
  Info := Info + 'Application:' + NewLine;
  Info := Info + Space + 'SpeakEasy AI Granite {#MyAppVersion} — Native Windows Voice-to-Text' + NewLine + NewLine;
  if MemoDirInfo <> '' then
    Info := Info + MemoDirInfo + NewLine + NewLine;
  Info := Info + 'Speech engine:' + NewLine;
  Info := Info + Space + 'IBM Granite Speech 4.1 2B  (ASR, translation, keyword biasing)' + NewLine + NewLine;
  Info := Info + 'The installer will:' + NewLine;
  Info := Info + Space + '1. Extract SpeakEasy AI application files' + NewLine;
  if ModelExists then
    Info := Info + Space + '2. IBM Granite Speech model — already installed (skip download)' + NewLine
  else
    Info := Info + Space + '2. Download IBM Granite Speech model from HuggingFace' + NewLine;
  Info := Info + Space + '3. Create desktop and Start Menu shortcuts' + NewLine;
  Info := Info + Space + '4. Configure Windows Defender exclusions' + NewLine + NewLine;
  if DetectedGPU <> '' then
    Info := Info + 'GPU: ' + DetectedGPU + NewLine
  else
    Info := Info + 'GPU: No NVIDIA GPU detected (will use CPU)' + NewLine;
  Result := Info;
end;

procedure DirectoryCopy(SourceDir, DestDir: String);
var
  FindRec: TFindRec;
  SourcePath, DestPath: String;
begin
  if not ForceDirectories(DestDir) then Exit;
  if FindFirst(SourceDir + '\*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Name = '.') or (FindRec.Name = '..') then Continue;
        SourcePath := SourceDir + '\' + FindRec.Name;
        DestPath := DestDir + '\' + FindRec.Name;
        if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
          DirectoryCopy(SourcePath, DestPath)
        else
          CopyFile(SourcePath, DestPath, False);
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

procedure MigrateOldData;
var
  OldSettings, NewSettings, OldModelsDir, NewEngineDir: String;
  FindRec: TFindRec;
  OldLogDir, OldLog, NewLog: String;
  LogFiles: array[0..2] of String;
  I: Integer;
begin
  { Migrate from legacy dictat0r.AI location }
  OldSettings := ExpandConstant('{userappdata}\dictat0r.AI\settings.json');
  NewSettings := ExpandConstant('{commonappdata}') + '\SpeakEasy AI\config\settings.json';
  if FileExists(OldSettings) and (not FileExists(NewSettings)) then
    CopyFile(OldSettings, NewSettings, False);

  // Migrate settings from previous layout (data was under {app})
  OldSettings := ExpandConstant('{app}\config\settings.json');
  if FileExists(OldSettings) and (not FileExists(NewSettings)) then
    CopyFile(OldSettings, NewSettings, False);

  { Migrate models from legacy dictat0r.AI location }
  OldModelsDir := ExpandConstant('{localappdata}\dictat0r.AI\models');
  if DirExists(OldModelsDir) then
    if FindFirst(OldModelsDir + '\*', FindRec) then
    begin
      try
        repeat
          if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
            if (FindRec.Name <> '.') and (FindRec.Name <> '..') then
            begin
              NewEngineDir := ExpandConstant('{commonappdata}') + '\SpeakEasy AI\models\' + FindRec.Name;
              if not DirExists(NewEngineDir) then
                DirectoryCopy(OldModelsDir + '\' + FindRec.Name, NewEngineDir);
            end;
        until not FindNext(FindRec);
      finally
        FindClose(FindRec);
      end;
    end;

  // Migrate models from previous layout (data was under {app})
  OldModelsDir := ExpandConstant('{app}\models');
  if DirExists(OldModelsDir) then
    if FindFirst(OldModelsDir + '\*', FindRec) then
    begin
      try
        repeat
          if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
            if (FindRec.Name <> '.') and (FindRec.Name <> '..') then
            begin
              NewEngineDir := ExpandConstant('{commonappdata}') + '\SpeakEasy AI\models\' + FindRec.Name;
              if not DirExists(NewEngineDir) then
                DirectoryCopy(OldModelsDir + '\' + FindRec.Name, NewEngineDir);
            end;
        until not FindNext(FindRec);
      finally
        FindClose(FindRec);
      end;
    end;

  OldLogDir := ExpandConstant('{userappdata}\dictat0r.AI');
  LogFiles[0] := 'speakeasy.log';
  LogFiles[1] := 'speakeasy.log.1';
  LogFiles[2] := 'speakeasy.log.2';
  for I := 0 to 2 do
  begin
    OldLog := OldLogDir + '\' + LogFiles[I];
    NewLog := ExpandConstant('{commonappdata}') + '\SpeakEasy AI\logs\' + LogFiles[I];
    if FileExists(OldLog) and (not FileExists(NewLog)) then
      CopyFile(OldLog, NewLog, False);
  end;
end;

procedure WriteDefaultSettings;
var
  SettingsFile, Json: String;
  ResultCode: Integer;
begin
  SettingsFile := ExpandConstant('{commonappdata}') + '\SpeakEasy AI Granite\config\settings.json';
  if not FileExists(SettingsFile) then
  begin
    Json := '{' + #13#10 + '  "engine": "granite"' + #13#10 + '}';
    SaveStringToFile(SettingsFile, Json, False);
  end;
  { Grant regular users write (Modify) access so the app can save settings without
    requiring elevation.  Uses the well-known SID for BUILTIN\Users so it works
    regardless of the Windows display language.  Runs unconditionally so it also
    repairs permissions on files created by older installer versions. }
  Exec('icacls.exe',
       '"' + SettingsFile + '" /grant *S-1-5-32-545:(M)',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

procedure ConfigureDefenderExclusions;
var
  ExeFullPath, PsCmd: String;
  ResultCode: Integer;
begin
  ExeFullPath := ExpandConstant('{app}') + '\{#MyAppExeName}';
  PsCmd := 'Add-MpPreference -ExclusionProcess ''' + ExeFullPath + ''' -ErrorAction SilentlyContinue';
  Exec('powershell.exe', '-NoProfile -ExecutionPolicy Bypass -Command "' + PsCmd + '"',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function PowerShellQuote(Value: String): String;
begin
  StringChangeEx(Value, #39, #39 + #39, True);
  Result := #39 + Value + #39;
end;

function CheckModelDiskSpace(ModelsDir: String): Boolean;
var
  PsCmd: String;
  ResultCode: Integer;
begin
  Result := True;
  if not DirExists(ModelsDir) then
    ForceDirectories(ModelsDir);

  PsCmd := '$ErrorActionPreference = ''Stop''; ' +
    '$path = ' + PowerShellQuote(ModelsDir) + '; ' +
    '$required = 5368709120; ' +
    '$drive = (Get-Item -LiteralPath $path).PSDrive; ' +
    'if ($drive.Free -lt $required) { exit 1 } else { exit 0 }';

  if Exec('powershell.exe', '-NoProfile -ExecutionPolicy Bypass -Command "' + PsCmd + '"',
          '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    if ResultCode = 1 then
    begin
      MsgBox('Not enough free disk space to download the IBM Granite Speech model.' + #13#10 + #13#10 +
             'At least 5 GB of free disk space is required.' + #13#10 + #13#10 +
             'Free disk space and run the installer again, or download the model later using granite-model-setup.ps1.',
             mbError, MB_OK);
      Result := False;
    end;
  end;
end;

function JsonStringValue(Line, Key: String): String;
var
  Marker, Remainder: String;
  StartPos, EndPos: Integer;
begin
  Result := '';
  Marker := '"' + Key + '": "';
  StartPos := Pos(Marker, Line);
  if StartPos = 0 then Exit;

  Remainder := Copy(Line, StartPos + Length(Marker), Length(Line));
  EndPos := Pos('"', Remainder);
  if EndPos = 0 then
    Result := Remainder
  else
    Result := Copy(Remainder, 1, EndPos - 1);

  StringChangeEx(Result, '\\', '\', True);
  StringChangeEx(Result, '\"', '"', True);
  StringChangeEx(Result, '\n', ' ', True);
end;

function JsonIntValue(Line, Key: String; Default: Integer): Integer;
var
  Marker, Remainder, Ch, Digits: String;
  StartPos, I: Integer;
begin
  Result := Default;
  Marker := '"' + Key + '": ';
  StartPos := Pos(Marker, Line);
  if StartPos = 0 then Exit;

  Remainder := Copy(Line, StartPos + Length(Marker), Length(Line));
  Digits := '';
  for I := 1 to Length(Remainder) do
  begin
    Ch := Copy(Remainder, I, 1);
    if (Ch >= '0') and (Ch <= '9') then
      Digits := Digits + Ch
    else
      Break;
  end;
  if Digits <> '' then
    Result := StrToIntDef(Digits, Default);
end;

procedure ApplyDownloadProgressLine(Line: String);
var
  Message, LabelText: String;
  Percent: Integer;
begin
  if Pos('SPEAKEASY_PROGRESS ', Line) <> 1 then Exit;

  Message := JsonStringValue(Line, 'message');
  LabelText := JsonStringValue(Line, 'label');
  Percent := JsonIntValue(Line, 'percent', -1);

  if Message = '' then
    Message := 'Downloading IBM Granite Speech model...';
  if LabelText = '' then
    LabelText := 'Source: huggingface.co/ibm-granite/granite-speech-4.1-2b';

  DownloadPage.SetText(Message, LabelText);
  if Percent >= 0 then
    DownloadPage.SetProgress(Percent, 100);
end;

procedure ProcessDownloadProgressChunk(var Buffer: String; Chunk: String);
var
  Line: String;
  LineEnd: Integer;
begin
  Buffer := Buffer + Chunk;
  LineEnd := Pos(#10, Buffer);
  while LineEnd > 0 do
  begin
    Line := Copy(Buffer, 1, LineEnd - 1);
    if (Length(Line) > 0) and (Copy(Line, Length(Line), 1) = #13) then
      Delete(Line, Length(Line), 1);
    ApplyDownloadProgressLine(Line);
    Delete(Buffer, 1, LineEnd);
    LineEnd := Pos(#10, Buffer);
  end;
end;

procedure PollDownloadOutput(OutputPath: String; var LastLength: Integer; var Buffer: String);
var
  Text: AnsiString;
  Chunk: String;
begin
  if LoadStringFromFile(OutputPath, Text) then
  begin
    if Length(Text) > LastLength then
    begin
      Chunk := Copy(Text, LastLength + 1, Length(Text) - LastLength);
      LastLength := Length(Text);
      ProcessDownloadProgressChunk(Buffer, Chunk);
    end;
  end;
end;

function RunDownloadProcess(ExePath, ModelsDir: String; var ExitCode: Integer): Boolean;
var
  ScriptPath, OutPath, ErrPath, CodePath, DonePath: String;
  Script, OutBuffer, ErrBuffer: String;
  CodeText: AnsiString;
  LaunchCode, OutLength, ErrLength: Integer;
begin
  Result := False;
  ExitCode := 1;
  ScriptPath := ExpandConstant('{tmp}\speakeasy-model-download.ps1');
  OutPath := ExpandConstant('{tmp}\speakeasy-model-download.out');
  ErrPath := ExpandConstant('{tmp}\speakeasy-model-download.err');
  CodePath := ExpandConstant('{tmp}\speakeasy-model-download.code');
  DonePath := ExpandConstant('{tmp}\speakeasy-model-download.done');

  DeleteFile(ScriptPath);
  DeleteFile(OutPath);
  DeleteFile(ErrPath);
  DeleteFile(CodePath);
  DeleteFile(DonePath);

  Script := '$ErrorActionPreference = ' + PowerShellQuote('Stop') + #13#10 +
    '$exe = ' + PowerShellQuote(ExePath) + #13#10 +
    '$arguments = @(' + PowerShellQuote('download-model') + ', ' +
      PowerShellQuote('--target-dir') + ', ' + PowerShellQuote(ModelsDir) + ', ' +
      PowerShellQuote('--progress-format') + ', ' + PowerShellQuote('jsonl') + ')' + #13#10 +
    'try {' + #13#10 +
    '  $process = Start-Process -FilePath $exe -ArgumentList $arguments -NoNewWindow -PassThru -RedirectStandardOutput ' + PowerShellQuote(OutPath) + ' -RedirectStandardError ' + PowerShellQuote(ErrPath) + #13#10 +
    '  $process.WaitForExit()' + #13#10 +
    '  Set-Content -Path ' + PowerShellQuote(CodePath) + ' -Value $process.ExitCode -Encoding ASCII' + #13#10 +
    '} catch {' + #13#10 +
    '  $_ | Out-String | Add-Content -Path ' + PowerShellQuote(ErrPath) + ' -Encoding UTF8' + #13#10 +
    '  Set-Content -Path ' + PowerShellQuote(CodePath) + ' -Value 1 -Encoding ASCII' + #13#10 +
    '} finally {' + #13#10 +
    '  New-Item -ItemType File -Path ' + PowerShellQuote(DonePath) + ' -Force | Out-Null' + #13#10 +
    '}' + #13#10;

  if not SaveStringToFile(ScriptPath, Script, False) then Exit;
  if not Exec('powershell.exe', '-NoProfile -ExecutionPolicy Bypass -File "' + ScriptPath + '"',
              '', SW_HIDE, ewNoWait, LaunchCode) then Exit;

  Result := True;
  OutLength := 0;
  ErrLength := 0;
  OutBuffer := '';
  ErrBuffer := '';
  while not FileExists(DonePath) do
  begin
    PollDownloadOutput(OutPath, OutLength, OutBuffer);
    PollDownloadOutput(ErrPath, ErrLength, ErrBuffer);
    WizardForm.Refresh;
    Sleep(250);
  end;

  PollDownloadOutput(OutPath, OutLength, OutBuffer);
  PollDownloadOutput(ErrPath, ErrLength, ErrBuffer);
  if OutBuffer <> '' then
    ProcessDownloadProgressChunk(OutBuffer, #10);
  if ErrBuffer <> '' then
    ProcessDownloadProgressChunk(ErrBuffer, #10);

  if LoadStringFromFile(CodePath, CodeText) then
    ExitCode := StrToIntDef(Trim(CodeText), 1);
end;

{ download-model exit codes: 0 = success, 1 = failure, 2 = auth required }
procedure DownloadModel;
var
  ExePath, ModelsDir: String;
  ResultCode: Integer;
begin
  ExePath := ExpandConstant('{app}\{#MyAppExeName}');
  ModelsDir := ExpandConstant('{commonappdata}') + '\SpeakEasy AI Granite\models';
  if not CheckModelDiskSpace(ModelsDir) then
    Exit;

  DownloadPage := CreateOutputProgressPage('Downloading Model',
    'Downloading the IBM Granite Speech model that powers SpeakEasy AI Granite. This may take several minutes.');
  DownloadPage.Show;
  DownloadPage.SetText('Downloading IBM Granite Speech (ibm-granite/granite-speech-4.1-2b)...',
    'Source: huggingface.co/ibm-granite/granite-speech-4.1-2b');
  DownloadPage.SetProgress(0, 100);
  try
    if RunDownloadProcess(ExePath, ModelsDir, ResultCode) then
    begin
      if ResultCode = 0 then
        DownloadPage.SetProgress(100, 100)
      else
        MsgBox('Model download failed (exit code ' + IntToStr(ResultCode) + ').' + #13#10 + #13#10 +
               'You can download it later using granite-model-setup.ps1' + #13#10 +
               'or the model will be downloaded on first launch.',
               mbError, MB_OK);
    end else
      MsgBox('Model download failed (exit code ' + IntToStr(ResultCode) + ').' + #13#10 + #13#10 +
             'Could not start the download process. You can download it later using granite-model-setup.ps1.',
             mbError, MB_OK);
  except
    MsgBox('Could not start model download.' + #13#10 +
           'You can download the model later using granite-model-setup.ps1.',
           mbError, MB_OK);
  end;
  DownloadPage.Hide;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Summary, InstDir, ModelsDir: String;
begin
  if CurStep = ssPostInstall then
  begin
    if not CleanInstall then
      MigrateOldData;
    WriteDefaultSettings;
    ConfigureDefenderExclusions;
    if not ModelExists then
      DownloadModel;
    InstDir := ExpandConstant('{app}');
    ModelsDir := ExpandConstant('{commonappdata}') + '\SpeakEasy AI Granite\models';
    Summary := 'SpeakEasy AI {#MyAppVersion} is ready.' + #13#10;
    Summary := Summary + 'Press Ctrl+Alt+P from any application to start recording.' + #13#10;
    Summary := Summary + 'Powered by IBM Granite Speech 4.1 2B.' + #13#10 + #13#10;
    Summary := Summary + 'INSTALL LOCATION' + #13#10;
    Summary := Summary + '  ' + InstDir + #13#10 + #13#10;
    Summary := Summary + 'MODEL STATUS' + #13#10;
    if DirExists(ModelsDir + '\granite') then
      Summary := Summary + '  [OK] IBM Granite Speech — ready' + #13#10
    else
      Summary := Summary + '  [!!] IBM Granite Speech — download failed (run granite-model-setup.ps1)' + #13#10;
    Summary := Summary + #13#10;
    Summary := Summary + 'SHORTCUTS' + #13#10;
    Summary := Summary + '  Desktop shortcut created' + #13#10;
    Summary := Summary + '  Start Menu group created' + #13#10 + #13#10;
    Summary := Summary + 'DEFAULT HOTKEYS' + #13#10;
    Summary := Summary + '  Ctrl+Alt+P   Start recording' + #13#10;
    Summary := Summary + '  Ctrl+Alt+L   Stop recording & transcribe' + #13#10;
    Summary := Summary + '  Ctrl+Alt+Q   Quit application' + #13#10;
    if DetectedGPU <> '' then
      Summary := Summary + #13#10 + 'GPU: ' + DetectedGPU + #13#10
    else
      Summary := Summary + #13#10 + 'GPU: No NVIDIA GPU detected (will use CPU)' + #13#10;
    SummaryMemo.Text := Summary;
  end;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = TokenPage.ID then
  begin
    { Toggle between token-entry and model-found UI }
    TokenLblHeader.Visible     := not ModelExists;
    TokenLblSteps.Visible      := not ModelExists;
    ModelFoundHeader.Visible   := ModelExists;
    ModelFoundNote.Visible     := ModelExists;
  end;
end;

procedure InitializeWizard;
begin
  ModelExists := False;

  CreateTokenPage;
  SummaryPage := CreateCustomPage(wpInfoAfter,
    'Installation Summary', 'Review what was installed and configured.');
  SummaryMemo := TNewMemo.Create(SummaryPage);
  SummaryMemo.Parent := SummaryPage.Surface;
  SummaryMemo.Left := 0;  SummaryMemo.Top := 0;
  SummaryMemo.Width := SummaryPage.SurfaceWidth;
  SummaryMemo.Height := SummaryPage.SurfaceHeight;
  SummaryMemo.ScrollBars := ssVertical;
  SummaryMemo.ReadOnly := True;
  SummaryMemo.Font.Name := 'Consolas';
  SummaryMemo.Font.Size := 9;
  SummaryMemo.Text := 'Installing...';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  GraniteDir: String;
begin
  Result := True;
  if CurPageID = wpSelectDir then
  begin
    GraniteDir := ExpandConstant('{commonappdata}') + '\SpeakEasy AI Granite\models\granite';
    ModelExists := DirExists(GraniteDir) and FileExists(GraniteDir + '\config.json');
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  AppDir, ModelsDir, GraniteDir: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    AppDir    := ExpandConstant('{commonappdata}') + '\SpeakEasy AI Granite';
    ModelsDir := AppDir + '\models';
    GraniteDir := ModelsDir + '\granite';
    if DirExists(GraniteDir) then
      if not UninstallSilent then
        if MsgBox('Delete the IBM Granite Speech model?' + #13#10 + #13#10 +
                   'Click Yes to remove, or No to keep for reinstall.',
                   mbConfirmation, MB_YESNO) = IDYES then
          DelTree(GraniteDir, True, True, True);
    if DirExists(ModelsDir) then RemoveDir(ModelsDir);
    if DirExists(AppDir) then RemoveDir(AppDir);
  end;
  if CurUninstallStep = usPostUninstall then
  begin
    AppDir := ExpandConstant('{app}');
    if DirExists(AppDir) then RemoveDir(AppDir);
  end;
end;
