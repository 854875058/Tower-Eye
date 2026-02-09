@echo off
echo ========================================
echo 多模态检索系统 - 一键启动
echo ========================================
echo.
echo 正在启动后端和前端服务...
echo.

REM 启动后端（在新窗口）
start "后端服务 - FastAPI" cmd /k "cd backend && python main.py"

REM 等待2秒让后端启动
timeout /t 2 /nobreak >nul

REM 启动前端（在新窗口）
start "前端应用 - React" cmd /k "cd frontend && npm start"

echo.
echo ========================================
echo 服务启动完成！
echo ========================================
echo.
echo 后端服务: http://localhost:8000
echo API 文档: http://localhost:8000/docs
echo 前端应用: http://localhost:3000
echo.
echo 关闭此窗口不会停止服务
echo 要停止服务，请关闭对应的命令行窗口
echo.
pause
