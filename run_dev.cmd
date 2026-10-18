@echo off
chcp 65001 > nul
rem 从源码启动 Bili23 下载器（不修改官方 exe）
cd /d "%~dp0"
start "" "D:\Bili23 Downloader\runtime\pythonw.exe" "%~dp0launcher.py" %*
