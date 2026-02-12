@echo off
chcp 65001 >nul 2>&1

:: ========================================
:: 多模态检索系统 - Windows 停止脚本
:: ========================================

set APP_PORT=8080

echo ========================================
echo   多模态检索系统 - 停止服务
echo ========================================
echo.

:: 查找占用端口的进程并结束
set FOUND=0
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%APP_PORT% " ^| findstr "LISTENING"') do (
    echo   发现进程 PID=%%a 占用端口 %APP_PORT%
    taskkill /PID %%a /F >nul 2>&1
    if not errorlevel 1 (
        echo   [OK] 已停止进程 %%a
        set FOUND=1
    ) else (
        echo   [!] 无法停止进程 %%a
    )
)

:: 兜底：按进程名查杀 app_ui.py
for /f "tokens=2" %%a in ('wmic process where "commandline like '%%app_ui.py%%'" get processid /value 2^>nul ^| findstr "="') do (
    set PID=%%a
    if defined PID (
        taskkill /PID %%a /F >nul 2>&1
        echo   [OK] 已停止 app_ui.py 进程 %%a
        set FOUND=1
    )
)

if %FOUND%==0 (
    echo   没有发现运行中的服务
)

echo.
echo   停止完成。
pause
