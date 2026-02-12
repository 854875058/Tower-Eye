#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$ROOT/logs/app.pid"
LOG_FILE="$ROOT/logs/app.log"
APP_PORT=${APP_PORT:-8080}
CONDA_ENV=${CONDA_ENV:-multimodal}

echo "========================================"
echo "多模态检索系统 - 启动 (NiceGUI)"
echo "========================================"
echo ""

# 检查是否已在运行
if [[ -f "$PID_FILE" ]]; then
    OLD_PID="$(tr -d '\n' <"$PID_FILE")"
    if [[ "$OLD_PID" =~ ^[0-9]+$ ]] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "服务已在运行 (PID=$OLD_PID)，如需重启请用 bash restart.sh"
        exit 0
    fi
    rm -f "$PID_FILE"
fi

cd "$ROOT"
mkdir -p logs

# [1/4] 激活 conda 环境
echo "[1/4] 激活 conda 环境: $CONDA_ENV"
for conda_sh in \
    "$HOME/miniconda3/etc/profile.d/conda.sh" \
    "/root/miniconda3/etc/profile.d/conda.sh" \
    "$HOME/anaconda3/etc/profile.d/conda.sh"; do
    if [[ -f "$conda_sh" ]]; then
        source "$conda_sh"
        echo "  找到 conda: $conda_sh"
        break
    fi
done

if command -v conda &>/dev/null; then
    conda activate "$CONDA_ENV" 2>/dev/null || true
    if [[ "${CONDA_DEFAULT_ENV:-}" == "$CONDA_ENV" ]]; then
        echo "  ✓ 环境已激活: $CONDA_DEFAULT_ENV"
    else
        echo "  ⚠ conda 环境激活失败，当前: ${CONDA_DEFAULT_ENV:-unknown}"
        echo "  建议: conda activate $CONDA_ENV && bash $0"
    fi
else
    echo "  ⚠ 未找到 conda，使用系统 Python"
fi
echo "  Python: $(python --version 2>&1) ($(which python))"

# [2/4] 停止旧进程 + 检查端口
echo ""
echo "[2/4] 清理旧进程..."
pkill -f "python poc/app/app_ui.py" 2>/dev/null || true
sleep 1

if command -v lsof &>/dev/null && lsof -i :"$APP_PORT" &>/dev/null; then
    echo "  ⚠ 端口 $APP_PORT 被占用，释放中..."
    lsof -ti :"$APP_PORT" | xargs kill -9 2>/dev/null || true
    sleep 1
fi
echo "  ✓ 端口 $APP_PORT 可用"

# [3/4] 检查关键依赖
echo ""
echo "[3/4] 检查依赖..."
python -c "import nicegui" 2>/dev/null && echo "  ✓ nicegui" || echo "  ⚠ nicegui 未安装: pip install nicegui"
python -c "import lancedb" 2>/dev/null && echo "  ✓ lancedb" || echo "  ⚠ lancedb 未安装: pip install lancedb"
python -c "import sentence_transformers" 2>/dev/null && echo "  ✓ sentence-transformers" || echo "  ⚠ sentence-transformers 未安装"

# [4/4] 启动应用
echo ""
echo "[4/4] 启动 NiceGUI 应用..."
nohup python poc/app/app_ui.py >>"$LOG_FILE" 2>&1 &
APP_PID=$!
echo "$APP_PID" >"$PID_FILE"

# 等待健康检查
echo "  等待启动..."
STARTED=false
for i in $(seq 1 15); do
    sleep 1
    if ! kill -0 "$APP_PID" 2>/dev/null; then
        echo "  ✗ 进程退出，启动失败！"
        echo "  查看日志: tail -f $LOG_FILE"
        rm -f "$PID_FILE"
        exit 1
    fi
    if curl -s "http://localhost:$APP_PORT" >/dev/null 2>&1; then
        STARTED=true
        break
    fi
done

if $STARTED; then
    echo "  ✓ 启动成功"
else
    echo "  ⚠ 暂未响应，可能还在加载模型..."
fi

echo ""
echo "========================================"
echo "  PID:  $APP_PID"
echo "  端口: $APP_PORT"
echo "  日志: $LOG_FILE"
echo "  地址: http://localhost:$APP_PORT"
echo "========================================"
echo ""
echo "  停止: bash stop.sh"
echo "  状态: bash status.sh"
echo ""
