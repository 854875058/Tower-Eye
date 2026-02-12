from modelscope import snapshot_download
import os

# 定义下载基础路径
base_dir = os.path.abspath("./models")

print("🚀 开始从魔塔社区下载 Qwen3-VL 模型...")

# 1. 下载 Embedding 模型
print("正在下载 Embedding 模型 (预计 16GB+)...")
embed_dir = snapshot_download(
    'qwen/Qwen3-VL-Embedding-8B', 
    cache_dir=base_dir,
    local_files_only=False
)
print(f"✅ Embedding 下载完成，路径: {embed_dir}")

# 2. 下载 Reranker 模型
print("\n正在下载 Reranker 模型 (预计 16GB+)...")
rank_dir = snapshot_download(
    'qwen/Qwen3-VL-Reranker-8B', 
    cache_dir=base_dir,
    local_files_only=False
)
print(f"✅ Reranker 下载完成，路径: {rank_dir}")

print("\n🎉 所有模型已就绪！你可以启动服务器了。")
