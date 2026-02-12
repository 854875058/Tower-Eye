#!/bin/bash

echo "========================================"
echo "多模态检索系统 - 一键启动 (NiceGUI)"
echo "========================================"
echo ""

# 配置端口
APP_PORT=${APP_PORT:-8080}

# 配置 conda 环境
CONDA_ENV=${CONDA_ENV:-multimodal}

# 创建日志目录
mkdir -p logs

# 激活 conda 环境
echo "[0/4] 激活 conda 环境: $CONDA_ENV"
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
echo "[1/4] 停止旧服务..."
pkill -f "python poc/app/app_ui.py" 2>/dev/null
pkill -f "python poc/app/app_v2.py" 2>/dev/null
pkill -f "python3 main.py" 2>/dev/null
sleep 2

# 检查端口占用
echo ""
echo "[2/4] 检查端口占用..."
if lsof -i :$APP_PORT > /dev/null 2>&1; then
    echo "⚠ 端口 $APP_PORT 被占用，尝试释放..."
    lsof -ti :$APP_PORT | xargs kill -9 2>/dev/null
    sleep 1
fi
echo "✓ 端口检查完成"

# 检查依赖
echo ""
echo "[3/4] 检查依赖..."
python -c "import nicegui" 2>/dev/null && echo "✓ nicegui 已安装" || echo "⚠ nicegui 未安装，请运行: pip install nicegui"
python -c "import lancedb" 2>/dev/null && echo "✓ lancedb 已安装" || echo "⚠ lancedb 未安装，请运行: pip install lancedb"
python -c "import sentence_transformers" 2>/dev/null && echo "✓ sentence-transformers 已安装" || echo "⚠ sentence-transformers 未安装"

# 启动 NiceGUI 应用
echo ""
echo "[4/4] 启动 NiceGUI 应用（端口: $APP_PORT）..."
nohup python poc/app/app_ui.py > logs/app.log 2>&1 &
APP_PID=$!

# 保存 PID
echo $APP_PID > logs/app.pid
echo "✓ 应用已启动 (PID: $APP_PID)"

# 等待启动
echo "等待应用启动..."
for i in {1..15}; do
    sleep 1
    if ps -p $APP_PID > /dev/null; then
        if curl -s http://localhost:$APP_PORT > /dev/null 2>&1; then
            echo "✓ 应用运行正常"
            break
        fi
    else
        echo "✗ 应用启动失败！"
        echo "查看日志: tail -f logs/app.log"
        exit 1
    fi
    if [ $i -eq 15 ]; then
        echo "⚠ 应用暂未响应，可能还在初始化..."
    fi
done

echo ""
echo "========================================"
echo "服务启动完成！"
echo "========================================"
echo ""
echo "环境信息："
echo "  Conda 环境: $CONDA_ENV"
echo "  Python: $(python --version 2>&1)"
echo ""
echo "访问地址："
echo "  应用: http://10.132.19.82:$APP_PORT"
echo ""
echo "管理服务："
echo "  查看日志: tail -f logs/app.log"
echo "  停止服务: bash stop_all.sh"
echo "  查看进程: ps aux | grep 'app_ui.py'"
echo ""
echo "进程信息："
echo "  PID: $APP_PID (端口: $APP_PORT)"
echo ""
