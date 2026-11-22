; ============================================================================
;  羊供应链管理系统 —— GitHub Actions 打包用 Inno Setup 6 安装包脚本
;
;  产物：Mutton_Supply_Chain_MS_setup.exe（名称固定，带版本信息，可直接分发）
;
;  CI 调用（见 .github/workflows/package.yml）：
;    ISCC.exe /DMyAppVersion=1.6.0 ^
;             /DVersionInfoVersion=1.6.0.12 ^
;             /DOutputBaseFilename=Mutton_Supply_Chain_MS_setup ^
;             /DMyAppExeName=Mutton_Supply_Chain_MS.exe ^
;             /DSourceDistDir=<RepoRoot>\package_stage\Mutton_Supply_Chain_MS ^
;             /DRepoRoot=<RepoRoot> ^
;             /DMySetupIcon=<RepoRoot>\...\app.ico ^      (可选：项目暂无 .ico)
;             ".github\inno\Mutton_Supply_Chain_MS.iss"
;
;  本地调试：先按 package.yml 的「Nuitka 独立打包」步骤产出 main.dist，
;  再把 main.dist 复制成 package_stage\Mutton_Supply_Chain_MS，然后
;    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" .github\inno\Mutton_Supply_Chain_MS.iss
;  不传任何 /D 也能跑（走下面的默认值）。
;
;  命名口径（与仓库要求一致，别改）：
;    · 程序 exe / 安装目录 / 安装包文件名 一律 Mutton_Supply_Chain_MS
;    · 桌面与开始菜单里显示的中文名 羊供应链管理
;    · AppId 是升级/卸载的唯一标识，一旦发布就不能再改
; ============================================================================

; ---- 仓库根目录（本脚本位于 <RepoRoot>\.github\inno\）----------------------
#ifndef RepoRoot
  #define RepoRoot AddBackslash(SourcePath) + "..\.."
#endif

; ---- 可由命令行 /D 覆盖的变量 ----------------------------------------------
; 显示名（开始菜单、控制面板「程序和功能」里看到的）
#ifndef MyAppName
  #define MyAppName "羊供应链管理"
#endif
; 安装目录名 / 主程序名 / 安装包名：统一用 ASCII 的英文标识
#ifndef MyAppDirName
  #define MyAppDirName "Mutton_Supply_Chain_MS"
#endif
#ifndef MyAppExeName
  #define MyAppExeName "Mutton_Supply_Chain_MS.exe"
#endif
; 显示版本（"关于"里看到的，取源码 config.APP_VERSION）
#ifndef MyAppVersion
  #define MyAppVersion "1.6.0"
#endif
; 文件版本信息必须是合法数字版本（a.b.c.d），由 CI 用 源码版本.运行编号 拼出
#ifndef VersionInfoVersion
  #define VersionInfoVersion "1.6.0.0"
#endif
; 应用唯一标识：升级覆盖安装、卸载项依赖它，发布后禁止修改
#ifndef MyAppId
  #define MyAppId "{{A13A378A-D53F-444E-88E9-B5AFB8F536B8}}"
#endif
#ifndef OutputBaseFilename
  #define OutputBaseFilename "Mutton_Supply_Chain_MS_setup"
#endif
; Nuitka 产物 + VERSION.txt 已由 workflow 组装到这个目录
#ifndef SourceDistDir
  #define SourceDistDir RepoRoot + "\package_stage\Mutton_Supply_Chain_MS"
#endif
#ifndef OutputDirPath
  #define OutputDirPath RepoRoot + "\release"
#endif
#ifndef ChineseMessagesFile
  #define ChineseMessagesFile AddBackslash(SourcePath) + "ChineseSimplified.isl"
#endif
; 图标预留：所有预处理指令放在段外，[Setup] 里只留一行展开结果（空行会被 Inno 忽略）
#ifdef MySetupIcon
  #define MySetupIconLine "SetupIconFile=" + MySetupIcon
#else
  #define MySetupIconLine ""
#endif

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=富民锐泽农业科技有限公司
AppCopyright=Copyright (C) 2026 富民锐泽农业科技有限公司
VersionInfoVersion={#VersionInfoVersion}
VersionInfoProductVersion={#VersionInfoVersion}
; 正式版 / 预览版的区分靠这个字段，便于用户分辨
VersionInfoProductName={#MyAppName}
VersionInfoCompany=富民锐泽农业科技有限公司
VersionInfoDescription={#MyAppName} 安装程序
DefaultDirName={autopf}\{#MyAppDirName}
DefaultGroupName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
; 中文排在 [Languages] 第一位，关掉语言选择框 → 向导直接是简体中文
ShowLanguageDialog=no
; 管理员安装：{autopf} 稳定解析为 Program Files，且只有管理员装才能预先给数据目录授权
PrivilegesRequired=admin
OutputDir={#OutputDirPath}
OutputBaseFilename={#OutputBaseFilename}
SolidCompression=yes
Compression=lzma2/max
LZMAUseSeparateProcess=yes
WizardStyle=modern dynamic windows11
; 项目暂无 ico：未传 /DMySetupIcon 时这一行展开为空，用 Inno 默认图标
{#MySetupIconLine}

#ifdef UseEnglishOnly
; 兜底：运行器自带 Inno 版本过旧、读不了 6.5+ 中文语言包时，由 workflow 加 /DUseEnglishOnly 重编
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
#else
[Languages]
Name: "chinesesimplified"; MessagesFile: "{#ChineseMessagesFile}"
Name: "english"; MessagesFile: "compiler:Default.isl"
#endif

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; 整个 Nuitka 产物目录（含 Qt 运行库、VERSION.txt），升级时整体覆盖。
; 用户数据 data\ 与 导出报表\ 不在产物里，安装/升级都不会动它们。
Source: "{#SourceDistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
; 程序把数据与导出报表写在 exe 同目录（mscm.config.ROOT）。装在 Program Files 时
; 普通用户默认没有写权限，这里预先建好并授权，避免每次启动都得「以管理员身份运行」。
Name: "{app}\data"; Permissions: users-modify
Name: "{app}\data\backup"; Permissions: users-modify
Name: "{app}\导出报表"; Permissions: users-modify

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; 装完直接起程序（静默安装时不弹）
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
