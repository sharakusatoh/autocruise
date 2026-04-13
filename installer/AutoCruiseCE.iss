#define MyAppName "AutoCruise CE"
#define MyAppPublisher "Sharaku Satoh"
#define MyAppExeName "AutoCruiseCE.exe"
#ifndef AppVersion
  #define AppVersion "1.0.2"
#endif
#ifndef SourceDir
  #define SourceDir "..\release\AutoCruiseCE"
#endif
#ifndef OutputDir
  #define OutputDir "..\release\installer"
#endif

[Setup]
AppId={{9E6928AF-E4C5-49A6-8CF2-4F16A8BA0E69}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://developers.openai.com/codex/app-server
AppSupportURL=https://developers.openai.com/codex/app-server
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=
InfoAfterFile=
OutputDir={#OutputDir}
OutputBaseFilename=AutoCruiseCE-Setup-{#AppVersion}
SetupIconFile=..\autocruise_logo.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
