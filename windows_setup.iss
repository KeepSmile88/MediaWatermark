[Setup]
; 应用基础信息
AppName=MediaWatermark
AppVersion=2.8.0
AppPublisher=KeepSmile88
AppSupportURL=https://github.com/KeepSmile88/MediaWatermark

; 默认安装位置和压缩属性
DefaultDirName=C:\software\MediaWatermark
DefaultGroupName=MediaWatermark
OutputDir=dist
OutputBaseFilename=MediaWatermark-Windows-Setup
Compression=lzma
SolidCompression=yes

; 权限：最低权限，允许未授权用户仅为自己安装，或者普通标准模式
PrivilegesRequired=lowest

; 图标路径设置
SetupIconFile=app_icon.ico
UninstallDisplayIcon={app}\MediaWatermark.exe



[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; 这里的相对路径是相对于运行 iscc 所在的目录（我们会在根目录执行，所以填 dist/MediaWatermark/*）
Source: "dist\MediaWatermark\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; 包含根目录下的说明文件如果有的话
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; 开始菜单快捷方式
Name: "{group}\MediaWatermark"; Filename: "{app}\MediaWatermark.exe"; IconFilename: "{app}\app_icon.ico"
Name: "{group}\{cm:UninstallProgram,MediaWatermark}"; Filename: "{uninstallexe}"
; 桌面快捷方式
Name: "{autodesktop}\MediaWatermark"; Filename: "{app}\MediaWatermark.exe"; Tasks: desktopicon; IconFilename: "{app}\app_icon.ico"

[Run]
Filename: "{app}\MediaWatermark.exe"; Description: "{cm:LaunchProgram,MediaWatermark}"; Flags: nowait postinstall skipifsilent
