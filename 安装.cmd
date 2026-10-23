@echo off
chcp 65001 >nul
rem 双击运行：调用 install.ps1 完成安装。也可以在命令行带参数运行，例如：安装.cmd -WorkDir "D:\访谈长文"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
echo.
pause
