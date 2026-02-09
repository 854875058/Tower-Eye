@echo off
echo ========================================
echo 启动多模态检索系统 - 前端应用
echo ========================================
echo.

cd frontend

echo [1/3] 检查 Node.js 环境...
node --version
if errorlevel 1 (
    echo 错误: 未找到 Node.js，请先安装 Node.js 16+
    pause
    exit /b 1
)

echo.
echo [2/3] 检查依赖...
if not exist "node_modules" (
    echo 首次运行，正在安装依赖...
    npm install
    if errorlevel 1 (
        echo 错误: 依赖安装失败
        pause
        exit /b 1
    )
) else (
    echo 依赖已安装
)

echo.
echo [3/3] 启动开发服务器...
echo 应用地址: http://localhost:3000
echo.
echo 按 Ctrl+C 停止服务
echo.

npm start

pause
