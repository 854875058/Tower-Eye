@echo off
chcp 65001 >nul 2>&1

:: ========================================
:: 多模态检索系统 - Windows 重启脚本
:: ========================================

set BIN_DIR=%~dp0

echo 正在停止服务...
call "%BIN_DIR%stop_win.bat"

echo.
echo 正在启动服务...
call "%BIN_DIR%start_win.bat"
