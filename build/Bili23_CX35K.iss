; Bili23 Downloader_CX35K 安装脚本（Inno Setup 6）
;
; 按用户安装（无需管理员权限）。路径/版本通过 ISCC 的 /D 定义传入，
; 这样既可以用 build\make_installer.ps1 一键构建，也可以手动：
;
;   ISCC.exe Bili23_CX35K.iss /DPayloadDir="C:\payload" /DExtraDir="C:\extra" ^
;            /DOutputDir=".\release" /DMyAppVersion="2.20.0"
;
; 说明：
;   * 安装目录只放运行时 + 补丁层，不放任何开发期备份；
;   * WebView2Loader.dll 必须放到 %APPDATA%\Bili23 Downloader\browser\：
;     Bili23.exe 的启动器有安装目录完整性校验，往安装目录里新增文件会被拒绝启动；
;   * 用户数据（配置/登录/任务库）不在安装包内，卸载时也不会删除。

#ifndef MyAppVersion
  #define MyAppVersion "2.20.0"
#endif

#ifndef PayloadDir
  #define PayloadDir "payload"
#endif

#ifndef ExtraDir
  #define ExtraDir "extra"
#endif

#ifndef OutputDir
  #define OutputDir "."
#endif

#define MyAppName "Bili23 Downloader_CX35K"
#define MyAppPublisher "Bili23 Downloader_CX35K"
#define MyAppExeName "Bili23.exe"

[Setup]
; AppId 用于识别"同一个程序"，升级/卸载依赖它，发布后不要改
AppId={{43226E2E-9445-4269-9998-EEF2E2DBF723}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=Bili23_Downloader_CX35K_Setup_{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
CloseApplications=yes
AllowNoIcons=yes
VersionInfoVersion={#MyAppVersion}.0
VersionInfoDescription={#MyAppName} 安装程序
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional tasks:"; Flags: checkedonce

[Files]
; 主程序 + 运行时 + 依赖 + 补丁层（递归）
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; WebView2 的加载器：安装目录不允许新增文件，放到用户数据目录
Source: "{#ExtraDir}\WebView2Loader.dll"; DestDir: "{userappdata}\Bili23 Downloader\browser"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 补丁层缓存目录兜底清理（补丁文件本身由 Inno 自动记录）
Type: filesandordirs; Name: "{app}\patch\__pycache__"
