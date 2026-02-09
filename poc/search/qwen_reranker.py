"""
Qwen3-VL Reranker HTTP 客户端
调用远程 Qwen3-VL Reranker 服务对检索结果进行重排序
"""
import requests
from typing import List, Dict
import base64
import os


class Qwen3VLReranker:
    """Qwen3-VL Reranker HTTP 客户端"""

    def __init__(self, api_url: str = "http://10.132.19.82:8011", timeout: int = 60):
        """
        初始化 Qwen3-VL Reranker 客户端

        Args:
            api_url: API 服务地址
            timeout: 请求超时时间（秒）
        """
        self.api_url = api_url.rstrip('/')
        self.timeout = timeout

        print(f"✓ Qwen3-VL Reranker 客户端初始化: {self.api_url}")

    def compute_relevance_score(
        self,
        query_text: str,
        image_path: str,
        summary: str = None
    ) -> float:
        """
        计算查询与图像的相关性得分

        Args:
            query_text: 查询文本
            image_path: 图像路径（必须是服务器可访问的绝对路径）
            summary: 图像摘要（可选）

        Returns:
            相关性得分 (0-1)
        """
        try:
            if not os.path.exists(image_path):
                print(f"⚠ 图像文件不存在: {image_path}")
                return 0.5

            # 使用绝对路径
            abs_image_path = os.path.abspath(image_path)

            payload = {
                "text": query_text,
                "image_path": abs_image_path
            }

            response = requests.post(
                f"{self.api_url}/v1/tower/rerank",
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()

            result = response.json()

            if "score" in result:
                score = float(result["score"])
                return min(max(score, 0.0), 1.0)  # 限制在 0-1 之间
            else:
                print(f"⚠ API 返回格式错误: {result}")
                return 0.5

        except requests.exceptions.RequestException as e:
            print(f"⚠ Rerank 请求失败: {e}")
            return 0.5  # 默认中等得分
        except Exception as e:
            print(f"⚠ 计算相关性得分失败: {e}")
            return 0.5

    def rerank(
        self,
        query_text: str,
        results: List[Dict],
        top_k: int = 20
    ) -> List[Dict]:
        """
        对检索结果进行重排序

        Args:
            query_text: 查询文本
            results: 检索结果列表
            top_k: 返回前 k 个结果

        Returns:
            重排序后的结果
        """
        print(f"正在对 {len(results)} 条结果进行重排序...")

        scored_results = []

        for idx, result in enumerate(results):
            try:
                # 计算相关性得分
                relevance_score = self.compute_relevance_score(
                    query_text=query_text,
                    image_path=result.get("file_path", ""),
                    summary=result.get("summary", "")
                )

                # 组合原始距离和相关性得分
                # 距离越小越好，相关性越大越好
                original_distance = result.get("distance", result.get("_distance", 1.0))
                # 综合得分：70% 相关性 + 30% 原始相似度
                combined_score = 0.7 * relevance_score + 0.3 * (1 - float(original_distance))

                result["relevance_score"] = relevance_score
                result["rerank_score"] = combined_score

                scored_results.append(result)

                print(f"  [{idx+1}/{len(results)}] 相关性: {relevance_score:.3f}, 综合得分: {combined_score:.3f}")

            except Exception as e:
                print(f"  [{idx+1}/{len(results)}] 重排序失败: {e}")
                result["relevance_score"] = 0.5
                result["rerank_score"] = 0.5
                scored_results.append(result)

        # 按综合得分排序
        scored_results.sort(key=lambda x: x["rerank_score"], reverse=True)

        # 返回 top_k
        return scored_results[:top_k]


# 使用示例
if __name__ == "__main__":
    # 初始化
    reranker = Qwen3VLReranker(api_url="http://10.132.19.82:8011")

    # 模拟检索结果
    results = [
        {
            "asset_id": "123",
            "file_path": "image1.jpg",
            "summary": "一辆红色的车",
            "distance": 0.3
        },
        {
            "asset_id": "456",
            "file_path": "image2.jpg",
            "summary": "一辆蓝色的车",
            "distance": 0.4
        }
    ]

    # 重排序
    reranked = reranker.rerank(
        query_text="红色汽车",
        results=results,
        top_k=10
    )

    print("\n重排序结果:")
    for r in reranked:
        print(f"  {r['asset_id']}: 相关性={r['relevance_score']:.3f}, 综合得分={r['rerank_score']:.3f}")
