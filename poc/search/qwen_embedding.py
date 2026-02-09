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


class Qwen3VLEmbedding:
    """Qwen3-VL Embedding HTTP 客户端"""

    def __init__(self, api_url: str = "http://10.132.19.82:8010", timeout: int = 30):
        """
        初始化 Qwen3-VL Embedding 客户端

        Args:
            api_url: API 服务地址
            timeout: 请求超时时间（秒）
        """
        self.api_url = api_url.rstrip('/')
        self.timeout = timeout
        self._embedding_dim = None

        print(f"✓ Qwen3-VL Embedding 客户端初始化: {self.api_url}")

    def encode_text(self, text: str) -> np.ndarray:
        """
        文本向量化

        Args:
            text: 输入文本

        Returns:
            向量 (numpy array)
        """
        try:
            response = requests.post(
                f"{self.api_url}/v1/tower/embed",
                json={"text": text},
                timeout=self.timeout
            )
            response.raise_for_status()

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
            print(f"文本向量化请求失败: {e}")
            raise
        except Exception as e:
            print(f"文本向量化失败: {e}")
            raise

    def encode_image(self, image_path: Union[str, Path]) -> np.ndarray:
        """
        图像向量化

        Args:
            image_path: 图像路径

        Returns:
            向量 (numpy array)
        """
        try:
            image_path = str(image_path)

            if not os.path.exists(image_path):
                raise FileNotFoundError(f"图像文件不存在: {image_path}")

            # 读取图像并转为 base64
            with open(image_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')

            response = requests.post(
                f"{self.api_url}/v1/tower/embed",
                json={
                    "image_base64": image_data,
                    "text": ""  # 可选的文本描述
                },
                timeout=self.timeout
            )
            response.raise_for_status()

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
            print(f"图像向量化请求失败: {e}")
            raise
        except Exception as e:
            print(f"图像向量化失败: {e}")
            raise

    def encode_batch(self, texts: List[str] = None, images: List[Union[str, Path]] = None) -> np.ndarray:
        """
        批量向量化

        Args:
            texts: 文本列表
            images: 图像路径列表

        Returns:
            向量矩阵 (numpy array)
        """
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

    def get_embedding_dimension(self) -> int:
        """获取向量维度"""
        if self._embedding_dim is None:
            # 使用测试文本获取维度
            test_emb = self.encode_text("test")
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
