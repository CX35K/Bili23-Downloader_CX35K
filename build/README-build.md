# Bili23 Downloader_CX35K 安装包构建说明

用 **Inno Setup 6** 把"可运行目录"打成按用户安装的安装包。

## 前置条件

1. 已安装 Inno Setup 6，`ISCC.exe` 可用（默认 `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`，
   本项目开发机在 `D:\Inno Setup\Inno Setup 6\ISCC.exe`）；
2. 一个**已部署好的运行目录**（包含 `Bili23.exe`、`runtime\`、`site-packages\`、`bundle\`、`patch\`、`LICENSE`）；
3. `WebView2Loader.dll`（可从 NuGet 包 `Microsoft.Web.WebView2` 的
   `build/native/x64/WebView2Loader.dll` 取得，或从已安装用户数据目录复制）。

## 一键构建

```powershell
powershell -ExecutionPolicy Bypass -File build\make_installer.ps1 `
    -InstallDir "D:\Bili23 Downloader" `
    -LoaderPath "C:\path\to\WebView2Loader.dll" `
    -InnoSetupDir "D:\Inno Setup\Inno Setup 6" `
    -OutputDir "E:\Agents_Workspace\release"
```

脚本会：

1. 把运行目录复制到临时载荷目录，**自动排除** `*.bak_*`（开发备份）、旧卸载器
   （`unins000.*`）、`__pycache__` 之外没必要的东西；
2. 调用 `ISCC.exe` 编译 `Bili23_CX35K.iss`；
3. 在 `-OutputDir` 输出 `Bili23_Downloader_CX35K_Setup_<版本>.exe`。

## 安装包行为

- **按用户安装**：默认 `%LOCALAPPDATA%\Programs\Bili23 Downloader_CX35K`，无需管理员权限；
- 开始菜单快捷方式（可选桌面快捷方式）；
- `WebView2Loader.dll` 安装到 `%APPDATA%\Bili23 Downloader\browser\`
  （安装目录有完整性校验，不能新增文件）；
- 卸载只删程序文件，**不删**用户配置/登录/任务库。

## 注意

- `Bili23_CX35K.iss` 里的 `AppId` 发布后不要改，否则升级/卸载会认成两个程序；
- 升级版本时改 `MyAppVersion`（脚本可通过 `-AppVersion` 传入）；
- 安装包未做代码签名，Windows SmartScreen 可能提示；正式发布建议自行签名。
