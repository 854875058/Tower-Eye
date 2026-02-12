"""
模型管理器
支持 CLIP 和 Qwen3-VL 两种模型的切换
"""
from typing import Optional, Union
from pathlib import Path
import numpy as np


def _get_embedding_actor():
    """获取 Embedding Ray Actor（如果 Ray 可用）"""
    try:
        import ray
        if ray.is_initialized():
            return ray.get_actor("embedding")
    except Exception:
        pass
    return None


class ModelManager:
    """统一的模型管理器"""

    def __init__(self, config: dict):
        """
        初始化模型管理器

        Args:
            config: 配置字典
        """
        self.config = config
        self.search_config = config.get("search", {})
        self.model_type = self.search_config.get("embedding_model", "clip")  # clip 或 qwen
        self.reranker_enabled = self.search_config.get("reranker_enabled", False)

        self.embedding_model = None
        self.reranker_model = None

        self._load_models()

    def _load_models(self):
        """加载模型"""
        print(f"正在加载模型，类型: {self.model_type}")

        if self.model_type == "clip":
            self._load_clip_model()
        elif self.model_type == "qwen":
            self._load_qwen_model()
        else:
            raise ValueError(f"不支持的模型类型: {self.model_type}")

        # 加载 Reranker
        if self.reranker_enabled:
            self._load_reranker()

    def _load_clip_model(self):
        """加载 CLIP 模型"""
        from poc.search.query import load_model

        model_name = self.search_config.get("clip_model", "clip-ViT-L-14")
        cache_dir = self.search_config.get("model_cache_dir")
        hf_mirror = self.search_config.get("hf_mirror")

        self.embedding_model = load_model(model_name, cache_dir=cache_dir, hf_mirror=hf_mirror)
        print(f"[OK] CLIP 模型加载成功: {model_name}")

    def _load_qwen_model(self):
        """加载 Qwen3-VL 模型（HTTP 客户端模式）"""
        from poc.search.qwen_embedding import Qwen3VLEmbedding

        api_url = self.search_config.get("qwen_api_url", "http://10.132.19.82:8010")
        timeout = self.search_config.get("qwen_timeout", 30)
        dummy_image = self.search_config.get("qwen_dummy_image", None)

        self.embedding_model = Qwen3VLEmbedding(api_url=api_url, timeout=timeout, dummy_image=dummy_image)
        print(f"[OK] Qwen3-VL 客户端初始化成功: {api_url}")

    def _load_reranker(self):
        """加载 Reranker（HTTP 客户端模式）"""
        from poc.search.qwen_reranker import Qwen3VLReranker

        api_url = self.search_config.get("reranker_api_url", "http://10.132.19.82:8011")
        timeout = self.search_config.get("reranker_timeout", 60)

        self.reranker_model = Qwen3VLReranker(api_url=api_url, timeout=timeout)
        print(f"[OK] Reranker 客户端初始化成功: {api_url}")

    def encode_text(self, text: str) -> np.ndarray:
        """文本向量化"""
        # 优先走 Ray Actor
        actor = _get_embedding_actor()
        if actor is not None:
            import ray
            try:
                return ray.get(actor.encode_text.remote(text))
            except Exception as e:
                print(f"[ModelManager] Ray Actor 调用失败，fallback 到本地: {e}")

        if self.model_type == "clip":
            return self.embedding_model.encode(
                text,
                convert_to_numpy=True,
                normalize_embeddings=True
            )
        elif self.model_type == "qwen":
            return self.embedding_model.encode_text(text)
        else:
            raise ValueError(f"不支持的模型类型: {self.model_type}")

    def encode_image(self, image_path: Union[str, Path]) -> np.ndarray:
        """图像向量化"""
        # 优先走 Ray Actor
        actor = _get_embedding_actor()
        if actor is not None:
            import ray
            try:
                return ray.get(actor.encode_image.remote(str(image_path)))
            except Exception as e:
                print(f"[ModelManager] Ray Actor 调用失败，fallback 到本地: {e}")

        if self.model_type == "clip":
            from PIL import Image
            image = Image.open(image_path).convert("RGB")
            return self.embedding_model.encode(
                image,
                convert_to_numpy=True,
                normalize_embeddings=True
            )
        elif self.model_type == "qwen":
            return self.embedding_model.encode_image(image_path)
        else:
            raise ValueError(f"不支持的模型类型: {self.model_type}")

    def encode_images_batch(self, image_paths: list) -> np.ndarray:
        """批量图像向量化 — 利用服务端 batch API 加速"""
        if self.model_type == "qwen":
            return self.embedding_model.encode_batch(images=image_paths)
        elif self.model_type == "clip":
            from PIL import Image
            images = [Image.open(p).convert("RGB") for p in image_paths]
            return self.embedding_model.encode(
                images, convert_to_numpy=True, normalize_embeddings=True
            )
        else:
            raise ValueError(f"不支持的模型类型: {self.model_type}")

    def rerank(self, query_text: str, results: list, top_k: int = 20) -> list:
        """重排序"""
        if self.reranker_enabled and self.reranker_model:
            return self.reranker_model.rerank(query_text, results, top_k)
        else:
            # 不使用 reranker，直接返回
            return results[:top_k]

    def get_embedding_dimension(self) -> int:
        """获取向量维度"""
        if self.model_type == "clip":
            return self.embedding_model.get_sentence_embedding_dimension()
        elif self.model_type == "qwen":
            return self.embedding_model.get_embedding_dimension()
        else:
            return 768  # 默认维度


# 使用示例
if __name__ == "__main__":
    config = {
        "search": {
            "embedding_model": "qwen",  # 或 "clip"
            "qwen_api_url": "http://10.132.19.82:8010",
            "qwen_timeout": 30,
            "reranker_enabled": True,
            "reranker_api_url": "http://10.132.19.82:8011",
            "reranker_timeout": 60,
            "device": "cuda"
        }
    }

    manager = ModelManager(config)

    # 文本向量化
    text_emb = manager.encode_text("红色汽车")
    print(f"文本向量维度: {len(text_emb)}")

    # 图像向量化
    image_emb = manager.encode_image("test.jpg")
    print(f"图像向量维度: {len(image_emb)}")

    # 重排序
    results = [...]  # 检索结果
    reranked = manager.rerank("红色汽车", results, top_k=10)
    print(f"重排序完成，返回 {len(reranked)} 条结果")
