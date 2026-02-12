 #!/bin/bash
# 彻底清理残余进程
ps -ef | grep _server.py | awk '{print $2}' | xargs kill -9 2>/dev/null

echo "🚀 正在启动 Embedding 服务 (8010)..."
nohup python embed_engine_server.py > embed_log.txt 2>&1 &

echo "🚀 正在启动 Reranker 服务 (8011)..."
nohup python rerank_engine_server.py > rerank_log.txt 2>&1 &

echo "✅ 服务已在后台启动，请使用 tail -f embed_log.txt 查看进度"
