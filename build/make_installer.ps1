# 一键构建 Bili23 Downloader_CX35K 安装包
#
# 用法示例：
#   powershell -ExecutionPolicy Bypass -File build\make_installer.ps1 `
#       -InstallDir "D:\Bili23 Downloader" `
#       -LoaderPath "C:\path\to\WebView2Loader.dll" `
#       -InnoSetupDir "D:\Inno Setup\Inno Setup 6" `
#       -OutputDir "E:\Agents_Workspace\release"
#
# 不传 -LoaderPath 时，会自动尝试 %APPDATA%\Bili23 Downloader\browser\WebView2Loader.dll。

[CmdletBinding()]
param(
    [string]$InstallDir = "D:\Bili23 Downloader",
    [string]$LoaderPath = "",
    [string]$InnoSetupDir = "D:\Inno Setup\Inno Setup 6",
    [string]$OutputDir = "",
    [string]$AppVersion = "2.20.0"
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent $here

if (-not $OutputDir) { $OutputDir = Join-Path $repo "release" }

$iscc = Join-Path $InnoSetupDir "ISCC.exe"
if (-not (Test-Path $iscc)) {
    throw "找不到 ISCC.exe：$iscc（用 -InnoSetupDir 指定 Inno Setup 6 目录）"
}

if (-not (Test-Path (Join-Path $InstallDir "Bili23.exe"))) {
    throw "安装目录里没有 Bili23.exe：$InstallDir"
}

if (-not $LoaderPath) {
    $LoaderPath = Join-Path $env:APPDATA "Bili23 Downloader\browser\WebView2Loader.dll"
}

if (-not (Test-Path $LoaderPath)) {
    throw "找不到 WebView2Loader.dll：$LoaderPath（用 -LoaderPath 指定）"
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$tmp = Join-Path $env:TEMP "Bili23Installer_$stamp"
$payload = Join-Path $tmp "payload"
$extra = Join-Path $tmp "extra"

New-Item -ItemType Directory -Force -Path $payload, $extra, $OutputDir | Out-Null

Write-Host "1/4 复制运行目录（排除备份/旧卸载器/日志）…"
$items = @("Bili23.exe", "bundle", "runtime", "site-packages", "patch", "LICENSE")
foreach ($item in $items) {
    $src = Join-Path $InstallDir $item
    if (Test-Path $src) {
        Copy-Item $src -Destination $payload -Recurse -Force
    } else {
        Write-Warning "缺少：$src（安装包将不包含它）"
    }
}

# 排除开发期备份、旧卸载器、日志、pyc（patch 下的 pyc 保留，加快启动）
Get-ChildItem $payload -Recurse -File -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -match "\.bak" -or $_.Name -match "^Bili23\.exe\." -or $_.Name -match "^unins000\.(exe|dat|msg)$" -or $_.Name -match "\.log$"
} | Remove-Item -Force -ErrorAction SilentlyContinue

Copy-Item $LoaderPath (Join-Path $extra "WebView2Loader.dll") -Force

Write-Host "2/4 参数量…"
$payloadSize = (Get-ChildItem $payload -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
Write-Host ("    载荷体积：{0:N1} MB" -f $payloadSize)

Write-Host "3/4 编译安装包…"
$iss = Join-Path $here "Bili23_CX35K.iss"
$args = @(
    $iss,
    "/DMyAppVersion=$AppVersion",
    "/DPayloadDir=$payload",
    "/DExtraDir=$extra",
    "/DOutputDir=$OutputDir"
)

& $iscc @args | Out-Host
if ($LASTEXITCODE -ne 0) { throw "ISCC 编译失败，退出码 $LASTEXITCODE" }

Write-Host "4/4 清理临时载荷…"
Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue

$result = Join-Path $OutputDir "Bili23_Downloader_CX35K_Setup_$AppVersion.exe"
if (-not (Test-Path $result)) { throw "没有找到输出文件：$result" }

$size = (Get-Item $result).Length / 1MB
Write-Host ("完成：{0}（{1:N1} MB）" -f $result, $size)
