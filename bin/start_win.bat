@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

:: ========================================
:: 多模态检索系统 - Windows 本地启动脚本
:: 模型服务在远程 GPU 服务器，本地只跑 NiceGUI Web
:: ========================================

set ROOT=%~dp0..
cd /d "%ROOT%"

set APP_PORT=8080
set VENV=%ROOT%\.venv\Scripts

echo ========================================
echo   多模态检索系统 - Windows 本地启动
echo ========================================
echo.

:: [1/5] 检查虚拟环境
echo [1/5] 检查 Python 环境...
if not exist "%VENV%\python.exe" (
    echo   [!] 未找到 .venv，正在创建...
    python -m venv .venv
    if errorlevel 1 (
        echo   [X] 创建虚拟环境失败
        pause
        exit /b 1
    )
)
echo   Python: %VENV%\python.exe
"%VENV%\python.exe" --version
echo.

:: [2/5] 安装/更新依赖
echo [2/5] 检查依赖...
"%VENV%\python.exe" -c "import nicegui" >nul 2>&1
if errorlevel 1 (
    echo   安装依赖中（首次较慢）...
    "%VENV%\pip.exe" install -q nicegui pyyaml requests numpy pillow lancedb sentence-transformers langgraph opencv-python
)
echo   [OK] 依赖就绪
echo.

:: [3/5] 检查数据文件
echo [3/5] 检查数据文件...
set DB_OK=0
set LANCE_OK=0

if exist "poc\data\metadata.db" (
    echo   [OK] metadata.db 存在
    set DB_OK=1
) else (
    echo   [!] metadata.db 不存在
)

if exist "poc\data\lancedb\embeddings.lance" (
    echo   [OK] LanceDB 向量数据存在
    set LANCE_OK=1
) else (
    :: lancedb 目录结构可能不同，检查目录是否非空
    if exist "poc\data\lancedb" (
        dir /b "poc\data\lancedb" 2>nul | findstr "." >nul 2>&1
        if not errorlevel 1 (
            echo   [OK] LanceDB 目录非空
            set LANCE_OK=1
        ) else (
            echo   [!] LanceDB 目录为空
        )
    ) else (
        echo   [!] LanceDB 目录不存在
    )
)

if %DB_OK%==0 (
    echo.
    echo   ================================================
    echo   数据库不存在，需要先从服务器同步数据：
    echo     scp -r root@服务器IP:/data/zhn_dir/多模态检索-铁塔/poc/data ./poc/
    echo   或者在本地执行入库（需要远程 Embedding 服务已启动）：
    echo     .venv\Scripts\python -m poc.pipeline.ingest --config poc/config/poc.yaml
    echo     .venv\Scripts\python import_warning_data.py
    echo     .venv\Scripts\python -m poc.pipeline.embed --config poc/config/poc.yaml
    echo   ================================================
    echo.
)
echo.

:: [4/5] 检查远程服务连通性
echo [4/5] 检查远程模型服务...
"%VENV%\python.exe" -c "import requests; r=requests.get('http://10.132.19.82:8010/docs', timeout=5); print('  [OK] Embedding 服务 8010 可达')" 2>nul
if errorlevel 1 (
    echo   [!] Embedding 服务 10.132.19.82:8010 不可达
    echo       请确认 GPU 服务器上已启动: bash start_tower_services.sh
)
"%VENV%\python.exe" -c "import requests; r=requests.get('http://10.132.19.82:8011/docs', timeout=5); print('  [OK] Reranker 服务 8011 可达')" 2>nul
if errorlevel 1 (
    echo   [!] Reranker 服务 10.132.19.82:8011 不可达
)
echo.

:: [5/5] 启动 NiceGUI Web 应用
echo [5/5] 启动 NiceGUI Web 应用...
echo   端口: %APP_PORT%
echo   地址: http://localhost:%APP_PORT%
echo.

:: 检查端口是否被占用
netstat -ano | findstr ":%APP_PORT% " | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo   [!] 端口 %APP_PORT% 已被占用
    echo   请先关闭占用该端口的程序，或修改脚本中的 APP_PORT
    echo.
    choice /c YN /m "是否仍然尝试启动 Y/N"
    if errorlevel 2 (
        pause
        exit /b 1
    )
)

echo ========================================
echo   启动中... 浏览器将自动打开
echo   按 Ctrl+C 停止服务
echo ========================================
echo.

:: 2秒后自动打开浏览器
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://localhost:%APP_PORT%"

:: 启动 NiceGUI（前台运行，Ctrl+C 可停止）
"%VENV%\python.exe" poc\app\app_ui.py

echo.
echo   服务已停止
pause
