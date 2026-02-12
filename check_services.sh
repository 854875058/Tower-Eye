#!/bin/bash

echo "========================================"
echo "检查服务状态 (NiceGUI)"
echo "========================================"
echo ""

echo "[1] 检查应用日志..."
if [ -f logs/app.log ]; then
    echo "应用日志（最近 50 行）："
    tail -50 logs/app.log
else
    echo "应用日志文件不存在"
fi

echo ""
echo "[2] 检查端口占用..."
echo "8080 端口（NiceGUI）："
lsof -i :8080 2>/dev/null || echo "端口 8080 未被占用"

echo ""
echo "[3] 检查 Python 环境..."
python --version 2>/dev/null || python3 --version 2>/dev/null || echo "未找到 Python"
echo "nicegui: $(python -c 'import nicegui; print(nicegui.__version__)' 2>/dev/null || echo '未安装')"
echo "lancedb: $(python -c 'import lancedb; print(lancedb.__version__)' 2>/dev/null || echo '未安装')"

echo ""
echo "[4] 检查数据库文件..."
ls -lh poc/data/metadata.db 2>/dev/null || echo "metadata.db 不存在"
ls -lh poc/data/lancedb/ 2>/dev/null || echo "lancedb 目录不存在"

echo ""
echo "[5] 检查进程..."
if [ -f logs/app.pid ]; then
    APP_PID=$(cat logs/app.pid)
    if ps -p $APP_PID > /dev/null 2>&1; then
        echo "✓ NiceGUI 应用运行中 (PID: $APP_PID)"
    else
        echo "✗ PID 文件存在但进程不在运行"
    fi
else
    echo "未找到 PID 文件"
fi
ps aux | grep "app_ui.py" | grep -v grep || echo "未发现 app_ui.py 进程"

echo ""
echo "[6] 测试连通性..."
if curl -s -o /dev/null -w "%{http_code}" http://localhost:8080 | grep -q "200"; then
    echo "✓ http://localhost:8080 响应正常"
else
    echo "✗ http://localhost:8080 无响应"
fi
echo ""
