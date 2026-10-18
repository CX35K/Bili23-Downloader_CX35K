# NOTICE / 第三方组件说明

本仓库是 **Bili23 Downloader** 的修改版，按 GNU General Public License v3.0 发布。
以下列出随程序分发的第三方组件及其许可证（最终以各项目官方声明为准）。

## 上游项目

- **Bili23 Downloader** — Copyright © 2022-2026 Scott Sloan
  - 许可：GNU General Public License v3.0
  - 仓库：https://github.com/ScottSloan/Bili23-Downloader
  - 本仓库在 GPLv3 条款下分发其源码的修改版本；修改内容见 `docs/` 与 `patches/`。

## 运行时与依赖

| 组件 | 用途 | 许可 |
|---|---|---|
| Qt 6 / PySide6 | GUI 框架 | LGPLv3 / GPLv3（Qt 双许可；本项目按 GPLv3 分发） |
| PyQt-Fluent-Widgets (qfluentwidgets) | Fluent 风格控件 | GPLv3 |
| qframelesswindow | 无边框窗口 | GPLv3 |
| FFmpeg（随包裁剪版） | 音视频转封装/转码 | LGPLv2.1+ / GPL（取决于构建配置） |
| httpx / orjson / psutil 等 | 网络与工具库 | 各自的开源许可（MIT / Apache-2.0 / BSD 等） |

## 系统组件（不随仓库分发）

- **Microsoft Edge WebView2 Runtime**：内置浏览器使用，由系统/Edge 提供；
  安装包中只包含 `WebView2Loader.dll`（来自 Microsoft.Web.WebView2 SDK，按微软可再分发条款使用）。
- **Microsoft Edge / Chromium** 相关组件版权归 Microsoft 及 Chromium 项目所有。

## 图标与资源

程序图标、界面资源来自上游 Bili23 Downloader 项目与上述组件，版权归各自权利人所有。

## 免责声明

本修改版为非官方版本，与 Bili23 Downloader 原作者无关。请遵守当地法律法规与目标网站的服务条款；
仅用于个人学习与研究，不得用于商业用途或侵犯他人权益。
