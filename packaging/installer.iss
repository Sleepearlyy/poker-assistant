#ifndef AppVersion
  #define AppVersion "0.3.0"
#endif
[Setup]
AppId={{AC54977D-6828-493D-AC70-C015A41796B3}
AppName=德扑助手
AppVersion={#AppVersion}
AppPublisher=Sleepearlyy
AppPublisherURL=https://github.com/Sleepearlyy/poker-screen-reader
AppSupportURL=https://github.com/Sleepearlyy/poker-screen-reader/issues
DefaultDirName={localappdata}\Programs\PokerScreenReader
DefaultGroupName=德扑助手
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\release
OutputBaseFilename=PokerAssistant-{#AppVersion}-windows-x64-setup
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\LICENSE
UninstallDisplayIcon={app}\德扑助手.exe
CloseApplications=yes
[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked
[Files]
Source: "..\dist\德扑助手\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\德扑助手"; Filename: "{app}\德扑助手.exe"
Name: "{group}\Uninstall"; Filename: "{uninstallexe}"
Name: "{autodesktop}\德扑助手"; Filename: "{app}\德扑助手.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\德扑助手.exe"; Description: "Launch Poker Assistant"; Flags: nowait postinstall skipifsilent
