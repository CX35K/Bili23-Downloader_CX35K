# Bili23 Downloader_CX35K

基于开源项目 **Bili23 Downloader**（GPLv3）的修改版，在保留原有功能的基础上新增了内置浏览器、
M4A→FLAC 转换等能力，并按个人使用习惯做了一些调整。

> 非官方版本，与原作者无关。原项目：<https://github.com/ScottSloan/Bili23-Downloader>
>
> 关于页里的 GitHub 链接目前仍指向原项目，等本仓库地址确定后会替换。
>
> 说明：内置浏览器等**新增功能**在开发过程中遇到过弹窗交互、页面叠层之类的适配问题，
> 都已在本项目内部解决；这些属于新功能自身的实现细节，与原版软件无关，也不代表原版存在问题。

---

## 相比原版的差异

| 类型 | 内容 |
|---|---|
| 新增 | 内置浏览器（**WebView2** 内核）：应用内浏览 B 站、网页内直接播放视频、自动登录当前账号、按窗口自动缩放、底部「下载该页面的项目」一键切解析 |
| 新增 | 设置 → 下载 → 下载格式：**将 M4A 转换为 FLAC**（仅音频任务；与转 MP3 同时开启时 FLAC 优先） |
| 新增 | 设置 → 高级 → 浏览器主页（默认 B 站首页） |
| 修复 | 只下载音频（独立音频流）时 FFmpeg 报错：内置 ffmpeg 缺 `.m4a` 封装器，改为显式 `-f` + 封装器能力探测 + 降级 |
| 变更 | **移除整个软件更新模块**（不再检查更新、无更新入口） |

---

## 仓库结构

```
src/            可编辑源码（原版提取 + 本项目修改）
tools/          开发/构建/回归脚本
patches/        相对原版的两份补丁（音频修复、M4A→FLAC）
build/          Inno Setup 安装包构建配置与脚本
launcher.py     用原版安装目录的 Python 运行时直接跑 src/（开发用）
run_dev.cmd     双击从源码启动（Windows）
LICENSE         GPLv3（与上游一致）
NOTICE.md       第三方组件与版权说明
```

## 运行环境

- Windows 10 1809+（x64）
- 原版程序安装目录（提供 Python 3.13 运行时、PySide6、qfluentwidgets、ffmpeg 等）
  默认路径 `D:\Bili23 Downloader`，可用环境变量 `BILI23_HOME` 覆盖
- Microsoft Edge WebView2 Runtime（内置浏览器需要；系统通常已随 Edge 安装）

> 本项目可以不改原版安装目录里的文件运行（`patch\` 外置补丁层）；
> 完整安装包里已包含运行时、依赖、ffmpeg 与补丁层，可直接安装使用。

## 从源码运行（开发）

```bat
:: 1) 环境自检（不建窗口）
python launcher.py --smoke

:: 2) 从源码启动界面
run_dev.cmd
```

`launcher.py` 会复刻 PyStand 的环境变量与 `sys.path`，从 `src\` 加载代码，效果等价于打包版。

## 部署到安装目录（外置补丁层）

```powershell
"D:\Bili23 Downloader\runtime\python.exe" tools\deploy_patch.py
```

把 `src` 镜像到 `D:\Bili23 Downloader\patch\`（并预编译 `__pycache__`），重启程序即生效；
exe 里只需一次性回填过补丁层钩子（`main.py`）。

回填 exe（仅在修改 `src\main.py` 的启动逻辑时需要）：

```powershell
"D:\Bili23 Downloader\runtime\python.exe" tools\repack_exe.py --src src --exe "D:\Bili23 Downloader\Bili23.exe" --strip-pyc --apply
```

## 构建安装包

需要 [Inno Setup 6](https://jrsoftware.org/isinfo.php)。详见 [`build/README-build.md`](build/README-build.md)。

```powershell
powershell -ExecutionPolicy Bypass -File build\make_installer.ps1 -InstallDir "D:\Bili23 Downloader" -LoaderPath "C:\path\to\WebView2Loader.dll"
```

安装包按用户安装（`%LOCALAPPDATA%\Programs\Bili23 Downloader_CX35K`，无需管理员权限），
`WebView2Loader.dll` 自动放到 `%APPDATA%\Bili23 Downloader\browser\`，卸载不删用户配置与登录数据。

## 回归测试

```powershell
"D:\Bili23 Downloader\runtime\python.exe" tools\test_audio_remux.py        # 音频/FLAC 30 项
"D:\Bili23 Downloader\runtime\python.exe" tools\test_download_badge.py     # 红点位置/不误显示 99+
"D:\Bili23 Downloader\runtime\python.exe" tools\test_browser_page.py       # 内置浏览器页
"D:\Bili23 Downloader\runtime\python.exe" tools\test_browser_exit.py       # 关闭询问弹窗
"D:\Bili23 Downloader\runtime\python.exe" tools\test_browser_overlap.py    # 页面重叠
"D:\Bili23 Downloader\runtime\python.exe" tools\test_rename_about.py       # 改名/关于页
```

涉及 B 站网页的测试需要能正常访问 bilibili.com。

## 隐私

- 本版本移除了更新检查模块，不会向更新服务器发起请求；
- 程序本身不包含遥测/统计；
- 内置浏览器的 WebView2 profile、配置、登录 Cookie、任务库都在
  `%APPDATA%\Bili23 Downloader\` 下，卸载程序不会删除这些用户数据。

## 常见问题：不要设置 Windows 兼容模式

**请勿**给 `Bili23.exe`（以及桌面/开始菜单快捷方式）勾选「以兼容模式运行这个程序」
（Windows 7 / Windows 8 兼容模式等）。

给 exe 设置兼容模式后，Windows 会向程序谎报系统版本，实测会导致：

- 内置浏览器无法启动（WebView2 认为系统是 Win7 而拒绝工作）；
- Qt 的 DPI 处理退回旧逻辑：窗口缩放错位、对话框被裁切、按钮点击位置错位（看起来像"弹窗点不动"）；
- 即使之后取消兼容模式，只要还有旧进程/托盘实例没退出，问题也会看起来"没恢复"。

程序启动时会检测兼容性（注册表兼容性标志 + 系统版本谎报），一旦发现会弹出提示并退出，
避免进入这种半坏状态。

需要 Windows 7 支持的话：当前版本基于 Qt 6.10 + Python 3.13，官方最低要求 Windows 10 1809，
**不是**靠兼容模式或 VxKex 能稳定解决的；Win7 需要基于上游的 Win7 兼容版重建。

## 许可证

本项目基于 Bili23 Downloader（GPLv3）修改，整体沿用 **GNU General Public License v3.0**，
详见 [`LICENSE`](LICENSE) 与 [`NOTICE.md`](NOTICE.md)。

## 致谢

- [Bili23 Downloader](https://github.com/ScottSloan/Bili23-Downloader)（原作者 Scott Sloan）
- [PySide6](https://www.qt.io/qt-for-python) / [Qt](https://www.qt.io/)
- [PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets)
- [FFmpeg](https://ffmpeg.org/)
- [Microsoft Edge WebView2](https://developer.microsoft.com/microsoft-edge/webview2/)
