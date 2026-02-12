#!/bin/bash
# ── Qwen3-VL Embedding + Reranker 服务管理 ──
cd "$(dirname "$0")"

EMBED_PORT=8010
RERANK_PORT=8011
EMBED_LOG=embed_log.txt
RERANK_LOG=rerank_log.txt

# ── 1. 停掉旧进程 ──
echo "🔄 正在停止旧进程..."
for pattern in embed_engine_server rerank_engine_server; do
    pids=$(ps -ef | grep "[p]ython.*${pattern}" | awk '{print $2}')
    if [ -n "$pids" ]; then
        echo "   杀掉 ${pattern}: $pids"
        echo "$pids" | xargs kill -9 2>/dev/null
    fi
done
# 等端口释放
sleep 2

# ── 2. 检查端口是否被占用 ──
for port in $EMBED_PORT $RERANK_PORT; do
    if ss -tlnp 2>/dev/null | grep -q ":${port} "; then
        echo "❌ 端口 ${port} 仍被占用:"
        ss -tlnp | grep ":${port} "
        echo "   请手动 kill 占用进程后重试"
        exit 1
    fi
done

# ── 3. 启动 Embedding 服务 ──
echo "🚀 正在启动 Embedding 服务 (${EMBED_PORT})..."
> "$EMBED_LOG"
nohup python embed_engine_server.py > "$EMBED_LOG" 2>&1 &
EMBED_PID=$!

# ── 4. 启动 Reranker 服务 ──
echo "🚀 正在启动 Reranker 服务 (${RERANK_PORT})..."
> "$RERANK_LOG"
nohup python rerank_engine_server.py > "$RERANK_LOG" 2>&1 &
RERANK_PID=$!

# ── 5. 等待并检查是否存活 ──
echo "⏳ 等待进程启动（10秒）..."
sleep 10

FAILED=0

if kill -0 $EMBED_PID 2>/dev/null; then
    echo "✅ Embedding 服务已启动 (PID=$EMBED_PID, port=${EMBED_PORT})"
else
    echo "❌ Embedding 服务启动失败，日志:"
    tail -20 "$EMBED_LOG"
    FAILED=1
fi

if kill -0 $RERANK_PID 2>/dev/null; then
    echo "✅ Reranker 服务已启动 (PID=$RERANK_PID, port=${RERANK_PORT})"
else
    echo "❌ Reranker 服务启动失败，日志:"
    tail -20 "$RERANK_LOG"
    FAILED=1
fi

if [ $FAILED -eq 1 ]; then
    echo ""
    echo "⚠️  有服务启动失败，请检查上方日志"
    exit 1
fi

echo ""
echo "📋 查看日志: tail -f $EMBED_LOG"
