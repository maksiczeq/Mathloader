; ───────────────────────────────────────────────────────────────────────────
;  Mathloader — skrypt instalatora (Inno Setup 6.3+)
;
;  Buduj przez:  build.ps1     (albo ręcznie: ISCC.exe installer.iss)
;  Wymaga wcześniejszego `pyinstaller Mathloader.spec` — instalator pakuje
;  zawartość folderu dist\Mathloader.
; ───────────────────────────────────────────────────────────────────────────

#define AppName        "Mathloader"

; Numer wersji ma JEDNO zrodlo prawdy: version.py (APP_VERSION).
; build.ps1 czyta go stamtad i podaje tutaj jako /DAppVersion=...
; Wartosc ponizej jest wylacznie awaryjna - dla recznego ISCC.exe installer.iss.
#ifndef AppVersion
  #define AppVersion   "3.0.0"
#endif

#define AppPublisher   "Maksymilian Borowski"
#define AppExeName     "Mathloader.exe"
#define SourceDir      "dist\Mathloader"

[Setup]
AppId={{7B3F2C1A-9E4D-4A8B-B6F0-2D5C8E1A7F93}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}

; {autopf} = Program Files przy instalacji dla wszystkich,
;            %LOCALAPPDATA%\Programs przy instalacji tylko dla mnie.
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes

; Użytkownik sam wybiera: wszyscy (UAC) czy tylko ja (bez UAC).
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

LicenseFile=LICENSE
SetupIconFile=assets\mathloader.ico
UninstallDisplayIcon={app}\{#AppExeName}
WizardStyle=modern

OutputDir=dist_installer
OutputBaseFilename={#AppName}-{#AppVersion}-Setup
Compression=lzma2/max
SolidCompression=yes

; ~700 MB rozpakowane — nie pozwól zacząć bez miejsca na dysku.
ExtraDiskSpaceRequired=52428800

[Languages]
Name: "polish"; MessagesFile: "compiler:Languages\Polish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Cała zawartość builda PyInstallera (exe + _internal + Chromium).
Source: "{#SourceDir}\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; \
    Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; \
    Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; \
    Flags: nowait postinstall skipifsilent

[Code]
// Przy DEINSTALACJI (nie przy aktualizacji!) zapytaj, czy skasować ustawienia
// i historię lekcji. Aktualizacja nadpisuje wyłącznie zawartość {app} —
// dane w {userappdata}\Mathloader zostają nietknięte.
// Same pobrane obrazy lekcji leżą w folderach wybranych przez użytkownika
// i NIGDY nie są ruszane.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{userappdata}\{#AppName}');
    if DirExists(DataDir) then
    begin
      // MB_DEFBUTTON2: domyślnie zaznaczone jest "Nie" - przypadkowy Enter
      // nie kasuje historii lekcji.
      if MsgBox('Usunąć także ustawienia i historię lekcji?' + #13#10 + #13#10 +
                DataDir + #13#10 + #13#10 +
                'Jeśli planujesz instalację nowszej wersji Mathloadera, wybierz NIE' + #13#10 +
                '- Twoje ustawienia i numeracja lekcji zostaną zachowane.' + #13#10 + #13#10 +
                'Pobrane obrazy lekcji NIE zostaną usunięte w żadnym wypadku.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
    end;
  end;
end;
