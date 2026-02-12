"""
Qwen3-VL Embedding HTTP 客户端
调用远程 Qwen3-VL Embedding 服务
"""
import requests
from typing import Union, List
from pathlib import Path
import numpy as np
import base64
import os

from poc.infra.http_utils import post_with_retry, get_logger

log = get_logger("qwen_embedding")


class Qwen3VLEmbedding:
    """Qwen3-VL Embedding HTTP 客户端"""

    def __init__(self, api_url: str = "http://10.132.19.82:8010", timeout: int = 30, dummy_image: str = None):
        """
        初始化 Qwen3-VL Embedding 客户端

        Args:
            api_url: API 服务地址
            timeout: 请求超时时间（秒）
            dummy_image: 占位图像路径（用于纯文本编码）
        """
        self.api_url = api_url.rstrip('/')
        self.timeout = timeout
        self._embedding_dim = None
        self.dummy_image = dummy_image  # 占位图像路径
        self.max_retries = 3

        log.info("Qwen3-VL Embedding 客户端初始化: %s", self.api_url)

    def encode_text(self, text: str, dummy_image_path: str = None) -> np.ndarray:
        """
        文本向量化
        注意：Qwen3-VL API 要求同时提供 text 和 image_path

        Args:
            text: 输入文本
            dummy_image_path: 占位图像路径（如果不提供，使用实例的 dummy_image）

        Returns:
            向量 (numpy array)
        """
        try:
            # 确定使用哪个占位图像
            image_path = dummy_image_path or self.dummy_image

            if not image_path:
                raise ValueError("纯文本编码需要提供 dummy_image_path 或在初始化时设置 dummy_image")

            # 如果是目录，自动选取第一张图片作为占位图
            if os.path.isdir(image_path):
                import glob
                images = glob.glob(os.path.join(image_path, "*.jpg")) + \
                         glob.glob(os.path.join(image_path, "*.png"))
                if not images:
                    raise ValueError(f"占位图像目录为空: {image_path}")
                image_path = images[0]

            # API 要求必须提供 image_path
            payload = {
                "text": text,
                "image_path": os.path.abspath(image_path) if os.path.exists(image_path) else image_path
            }

            response = post_with_retry(
                f"{self.api_url}/v1/tower/embed",
                json=payload,
                timeout=self.timeout,
                max_retries=self.max_retries,
                logger=log,
            )

            result = response.json()
            if "embedding" not in result:
                raise ValueError(f"API 返回格式错误: {result}")

            embedding = np.array(result["embedding"], dtype=np.float32)

            # 归一化
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm

            return embedding

        except requests.exceptions.RequestException as e:
            log.error("文本向量化请求失败: %s", e)
            raise
        except Exception as e:
            log.error("文本向量化失败: %s", e)
            raise

    def encode_image(self, image_path: Union[str, Path]) -> np.ndarray:
        """
        图像向量化

        Args:
            image_path: 图像路径（必须是服务器可访问的绝对路径）

        Returns:
            向量 (numpy array)
        """
        try:
            image_path = str(image_path)

            if not os.path.exists(image_path):
                raise FileNotFoundError(f"图像文件不存在: {image_path}")

            # 使用绝对路径
            abs_image_path = os.path.abspath(image_path)

            response = post_with_retry(
                f"{self.api_url}/v1/tower/embed",
                json={
                    "text": "",  # 空文本
                    "image_path": abs_image_path
                },
                timeout=self.timeout,
                max_retries=self.max_retries,
                logger=log,
            )

            result = response.json()
            if "embedding" not in result:
                raise ValueError(f"API 返回格式错误: {result}")

            embedding = np.array(result["embedding"], dtype=np.float32)

            # 归一化
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm

            return embedding

        except requests.exceptions.RequestException as e:
            log.error("图像向量化请求失败: %s", e)
            raise
        except Exception as e:
            log.error("图像向量化失败: %s", e)
            raise

    def encode_batch(self, texts: List[str] = None, images: List[Union[str, Path]] = None) -> np.ndarray:
        """
        批量向量化 — 优先使用服务端 batch API，失败时逐条 fallback

        Args:
            texts: 文本列表
            images: 图像路径列表

        Returns:
            向量矩阵 (numpy array)
        """
        # 尝试服务端 batch API（仅图片）
        if images and not texts:
            try:
                return self._encode_batch_remote(images)
            except Exception as e:
                log.warning("batch API 不可用，fallback 到逐条请求: %s", e)

        embeddings = []

        if texts:
            for text in texts:
                emb = self.encode_text(text)
                embeddings.append(emb)

        if images:
            for image_path in images:
                emb = self.encode_image(image_path)
                embeddings.append(emb)

        return np.array(embeddings)

    def _encode_batch_remote(self, images: List[Union[str, Path]]) -> np.ndarray:
        """调用服务端 /v1/tower/embed_batch 批量接口"""
        items = []
        for img_path in images:
            p = str(img_path)
            if not os.path.exists(p):
                raise FileNotFoundError(f"图像文件不存在: {p}")
            items.append({"text": "", "image_path": os.path.abspath(p)})

        response = post_with_retry(
            f"{self.api_url}/v1/tower/embed_batch",
            json={"items": items},
            timeout=self.timeout * len(items),  # batch 超时按数量放大
            max_retries=self.max_retries,
            logger=log,
        )
        result = response.json()
        if "embeddings" not in result:
            raise ValueError(f"batch API 返回格式错误: {result}")

        embeddings = np.array(result["embeddings"], dtype=np.float32)
        # 逐行归一化
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1
        return embeddings / norms

    def get_embedding_dimension(self) -> int:
        """获取向量维度"""
        if self._embedding_dim is None:
            # 使用第一张可用图片获取维度（避免纯文本编码的 API 限制）
            if self.dummy_image and os.path.exists(self.dummy_image):
                # 如果 dummy_image 是目录，找第一张图片
                if os.path.isdir(self.dummy_image):
                    import glob
                    images = glob.glob(os.path.join(self.dummy_image, "*.jpg")) + \
                             glob.glob(os.path.join(self.dummy_image, "*.png"))
                    if images:
                        test_emb = self.encode_image(images[0])
                    else:
                        raise ValueError(f"占位图像目录为空: {self.dummy_image}")
                else:
                    test_emb = self.encode_image(self.dummy_image)
            else:
                # 降级：尝试纯文本编码（可能失败）
                test_emb = self.encode_text("test", dummy_image_path=self.dummy_image)

            self._embedding_dim = len(test_emb)
        return self._embedding_dim



# 使用示例
if __name__ == "__main__":
    # 初始化
    embedder = Qwen3VLEmbedding(api_url="http://10.132.19.82:8010")

    # 文本向量化
    text_emb = embedder.encode_text("一辆红色的车")
    print(f"文本向量维度: {len(text_emb)}")

    # 图像向量化
    image_emb = embedder.encode_image("test.jpg")
    print(f"图像向量维度: {len(image_emb)}")

    # 计算相似度
    similarity = np.dot(text_emb, image_emb)
    print(f"相似度: {similarity}")
