#!/bin/bash

echo "========================================"
echo "多模态检索系统 - 一键启动"
echo "========================================"
echo ""

# 配置端口
BACKEND_PORT=${BACKEND_PORT:-8001}
FRONTEND_PORT=${FRONTEND_PORT:-3000}

# 配置 conda 环境
CONDA_ENV=${CONDA_ENV:-multimodal}

# 创建日志目录
mkdir -p logs

# 激活 conda 环境
echo "[0/5] 激活 conda 环境: $CONDA_ENV"
if [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
    source "$HOME/anaconda3/etc/profile.d/conda.sh"
    conda activate $CONDA_ENV
    echo "✓ Conda 环境已激活: $(conda info --envs | grep '*' | awk '{print $1}')"
elif [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
    source "$HOME/miniconda3/etc/profile.d/conda.sh"
    conda activate $CONDA_ENV
    echo "✓ Conda 环境已激活: $(conda info --envs | grep '*' | awk '{print $1}')"
else
    echo "⚠ 未找到 conda，使用系统 Python"
fi

# 显示 Python 信息
echo "Python 版本: $(python --version 2>&1)"
echo "Python 路径: $(which python)"

# 停止旧服务
echo ""
echo "[1/5] 停止旧服务..."
pkill -f "python3 main.py" 2>/dev/null
pkill -f "python main.py" 2>/dev/null
pkill -f "npm start" 2>/dev/null
pkill -f "node.*react-scripts" 2>/dev/null
sleep 2

# 检查端口占用
echo ""
echo "[2/5] 检查端口占用..."
if lsof -i :$BACKEND_PORT > /dev/null 2>&1; then
    echo "⚠ 端口 $BACKEND_PORT 被占用，尝试释放..."
    lsof -ti :$BACKEND_PORT | xargs kill -9 2>/dev/null
    sleep 1
fi

if lsof -i :$FRONTEND_PORT > /dev/null 2>&1; then
    echo "⚠ 端口 $FRONTEND_PORT 被占用，尝试释放..."
    lsof -ti :$FRONTEND_PORT | xargs kill -9 2>/dev/null
    sleep 1
fi

echo "✓ 端口检查完成"

# 检查后端依赖
echo ""
echo "[3/5] 检查后端依赖..."
python -c "import lancedb" 2>/dev/null && echo "✓ lancedb 已安装" || echo "⚠ lancedb 未安装，请运行: pip install lancedb"
python -c "import fastapi" 2>/dev/null && echo "✓ fastapi 已安装" || echo "⚠ fastapi 未安装，请运行: pip install fastapi"
python -c "import sentence_transformers" 2>/dev/null && echo "✓ sentence-transformers 已安装" || echo "⚠ sentence-transformers 未安装"

# 启动后端
echo ""
echo "[4/5] 启动后端服务（端口: $BACKEND_PORT）..."
cd backend
PORT=$BACKEND_PORT nohup python main.py > ../logs/backend.log 2>&1 &
BACKEND_PID=$!
cd ..

# 保存 PID
echo $BACKEND_PID > logs/backend.pid
echo "✓ 后端服务已启动 (PID: $BACKEND_PID)"

# 等待后端启动
echo "等待后端服务启动..."
for i in {1..15}; do
    sleep 1
    if ps -p $BACKEND_PID > /dev/null; then
        if curl -s http://localhost:$BACKEND_PORT/api/health > /dev/null 2>&1; then
            echo "✓ 后端服务运行正常"

            # 检查 LanceDB 连接状态
            HEALTH_RESPONSE=$(curl -s http://localhost:$BACKEND_PORT/api/health)
            if echo "$HEALTH_RESPONSE" | grep -q '"lancedb_connected":true'; then
                echo "✓ LanceDB 连接成功"
            else
                echo "⚠ LanceDB 连接失败，检索功能可能不可用"
                echo "  请确保已安装: pip install lancedb"
            fi

            if echo "$HEALTH_RESPONSE" | grep -q '"model_loaded":true'; then
                echo "✓ CLIP 模型加载成功"
            else
                echo "⚠ CLIP 模型加载失败"
            fi
            break
        fi
    else
        echo "✗ 后端服务启动失败！"
        echo "查看日志: tail -f logs/backend.log"
        exit 1
    fi
    if [ $i -eq 15 ]; then
        echo "⚠ 后端 API 暂未响应，可能还在初始化..."
    fi
done

# 启动前端
echo ""
echo "[5/5] 启动前端应用（端口: $FRONTEND_PORT）..."
cd frontend

# 设置环境变量
export PORT=$FRONTEND_PORT
export BROWSER=none  # 禁止自动打开浏览器

nohup npm start > ../logs/frontend.log 2>&1 &
FRONTEND_PID=$!
cd ..

# 保存 PID
echo $FRONTEND_PID > logs/frontend.pid
echo "✓ 前端应用已启动 (PID: $FRONTEND_PID)"

echo ""
echo "等待前端编译..."
echo "这可能需要 30-90 秒，请耐心等待..."

# 等待前端编译完成
COMPILED=false
for i in {1..90}; do
    # 检查进程是否还在运行
    if ! ps -p $FRONTEND_PID > /dev/null; then
        echo "✗ 前端进程已退出！"
        echo "查看日志: tail -5rontend.log"
        echo ""
        echo "常见问题："
        echo "1. Node.js 版本过低（需要 >= 14.0.0）"
        echo "2. 依赖未正确安装（运行: cd frontend && npm install --legacy-peer-deps）"
        echo "3. 端口被占用"
        break
    fi

    # 检查是否编译成功
    if grep -q "Compiled successfully" logs/frontend.log 2>/dev/null; then
        echo "✓ 前端编译成功！"
        COMPILED=true
        break
    fi

    # 检查是否编译失败
    if grep -q "Failed to compile" logs/frontend.log 2>/dev/null; then
        echo "✗ 前端编译失败！"
        echo "查看日志: tail -50 logs/frontend.log"
        break
    fi

    sleep 1
    if [ $((i % 15)) -eq 0 ]; then
        echo "  等待中... ($i/90 秒)"
    fi
done

if [ "$COMPILED" = false ]; then
    echo ""
    echo "⚠ 前端编译超时或失败，请查看日志"
    echo "tail -f logs/frontend.log"
fi

echo ""
echo "========================================"
echo "服务启动完成！"
echo "========================================"
echo ""
echo "环境信息："
echo "  Conda 环境: $CONDA_ENV"
echo "  Python: $(python --version 2>&1)"
echo "  Node.js: $(node --version 2>&1)"
echo ""
echo "访问地址："
echo "  前端应用: http://10.132.19.82:$FRONTEND_PORT"
echo "  后端 API: http://10.132.19.82:$BACKEND_PORT"
echo "  API 文档: http://10.132.19.82:$BACKEND_PORT/docs"
echo ""
echo "管理服务："
echo "  查看后端日志: tail -f logs/backend.log"
echo "  查看前端日志: tail -f logs/frontend.log"
echo "  停止服务: bash stop_all.sh"
echo "  查看进程: ps aux | grep -E 'python main.py|npm start'"
echo ""
echo "进程信息："
echo "  后端 PID: $BACKEND_PID (端口: $BACKEND_PORT)"
echo "  前端 PID: $FRONTEND_PID (端口: $FRONTEND_PORT)"
echo ""
echo "测试命令："
echo "  curl http://localhost:$BACKEND_PORT/api/health"
echo "  curl http://localhost:$FRONTEND_PORT"
echo ""
echo "如果 LanceDB 连接失败，请在 conda 环境中安装："
echo "  conda activate $CONDA_ENV"
echo "  pip install lancedb"
echo ""
