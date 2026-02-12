#!/usr/bin/env bash

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$ROOT/poc_app.pid"
LOG_FILE="$ROOT/poc_app.log"

if [[ -f "$PID_FILE" ]]; then
  echo "PID 文件已存在: $PID_FILE，可能已经在运行。如果确认没有运行，可以手动删除该文件。"
  exit 0
fi

cd "$ROOT"

# 初始化 conda
echo "=== 初始化 Conda 环境 ==="
if [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
    source "$HOME/miniconda3/etc/profile.d/conda.sh"
    echo "✓ 找到 conda.sh: $HOME/miniconda3/etc/profile.d/conda.sh"
elif [ -f "/root/miniconda3/etc/profile.d/conda.sh" ]; then
    source "/root/miniconda3/etc/profile.d/conda.sh"
    echo "✓ 找到 conda.sh: /root/miniconda3/etc/profile.d/conda.sh"
elif [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
    source "$HOME/anaconda3/etc/profile.d/conda.sh"
    echo "✓ 找到 conda.sh: $HOME/anaconda3/etc/profile.d/conda.sh"
else
    echo "✗ 警告: 找不到 conda.sh，假设已在外部激活环境"
fi

# 激活 conda 环境
if command -v conda &> /dev/null; then
    echo "正在激活 multimodal 环境..."
    conda activate multimodal

    # 验证环境
    if [ "$CONDA_DEFAULT_ENV" != "multimodal" ]; then
        echo "✗ 警告: conda 环境激活失败，当前环境是: $CONDA_DEFAULT_ENV"
        echo "建议手动运行: conda activate multimodal && bash $0"
    else
        echo "✓ 成功激活环境: $CONDA_DEFAULT_ENV"
    fi
fi

echo "当前 Python: $(which python)"
python poc/app/app_ui.py >>"$LOG_FILE" 2>&1 &
PID=$!
echo "$PID" >"$PID_FILE"
echo "已启动多模态视联 POC (NiceGUI)，PID=$PID，日志文件: $LOG_FILE"
echo "访问地址: http://localhost:8080"
