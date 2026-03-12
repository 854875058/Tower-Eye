"""
Ray Actor 定义 — GPU 模型推理 Actor
- YOLODetectorActor  — YOLO 目标检测
- EmbeddingActor     — 向量编码（CLIP 本地 / Qwen HTTP）
- VLAnalyzerActor    — VL 场景描述（VLLM HTTP）
"""
import io
import re
import json
import base64
from pathlib import Path
from typing import Dict, List, Optional, Union

import numpy as np
import ray

from poc.pipeline.utils import resolve_path


def _resolve_qwen_dummy_image(config: dict, search_config: dict) -> Optional[str]:
    dummy_image = search_config.get("qwen_dummy_image")
    if not dummy_image:
        dummy_image = config.get("paths", {}).get("raw_images_dir", "data/warning_img")
    if not dummy_image:
        return None
    return str(resolve_path(dummy_image))


# ── YOLODetectorActor ─────────────────────────────────────────────────────

@ray.remote
class YOLODetectorActor:
    """YOLO 目标检测 Actor（持有 GPU 模型实例）"""

    def __init__(self, config: dict):
        self.config = config
        self.yolo_model = None
        self.confidence_threshold = 0.25
        self._init_model()

    def _init_model(self):
        from ultralytics import YOLO
        model_path = str(
            Path(__file__).resolve().parents[1] / "data" / "pretrainModel" / "yolo26x.pt"
        )
        self.yolo_model = YOLO(model_path)
        self.yolo_model.fuse()
        print(f"[YOLODetectorActor] 模型加载成功: {model_path}")

    def _get_class_name(self, class_id: int) -> str:
        mapping = {
            0: "person", 1: "bicycle", 2: "car", 3: "motorcycle",
            5: "bus", 7: "truck", 8: "van",
            11: "excavator", 12: "bulldozer", 24: "dump truck",
            25: "tractor", 26: "trailer",
        }
        return mapping.get(class_id, "unknown")

    def detect_image(self, image_path: str) -> List[Dict]:
        """单张图片 YOLO 检测"""
        if self.yolo_model is None:
            return []

        from PIL import Image
        results = self.yolo_model(image_path, conf=self.confidence_threshold, verbose=False)
        if not results or len(results) == 0:
            return []

        img = Image.open(image_path)
        w, h = img.size
        detections = []
        result = results[0]

        if result.boxes is not None:
            for box in result.boxes:
                class_id = int(box.cls.item())
                confidence = float(box.conf.item())
                xywhn = box.xywhn.cpu().numpy()[0]
                cx, cy, bw, bh = xywhn
                x1 = cx - bw / 2
                y1 = cy - bh / 2
                x2 = cx + bw / 2
                y2 = cy + bh / 2
                class_name = self._get_class_name(class_id)
                if class_name != "unknown":
                    detections.append({
                        "class": class_name,
                        "class_id": class_id,
                        "confidence": confidence,
                        "bbox": [x1, y1, x2, y2],
                        "manual": False,
                    })

        return detections

    def detect_batch(self, image_paths: List[str]) -> List[List[Dict]]:
        """批量检测"""
        return [self.detect_image(p) for p in image_paths]

    def detect_frame(self, frame_bytes: bytes) -> List[Dict]:
        """视频帧检测（接收序列化帧数据）"""
        import tempfile, os
        from PIL import Image

        img = Image.open(io.BytesIO(frame_bytes))
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            img.save(f, format="JPEG")
            tmp_path = f.name
        try:
            return self.detect_image(tmp_path)
        finally:
            os.unlink(tmp_path)


# ── EmbeddingActor ────────────────────────────────────────────────────────

@ray.remote
class EmbeddingActor:
    """向量编码 Actor（CLIP 本地模型 或 Qwen HTTP 客户端）"""

    def __init__(self, config: dict):
        self.config = config
        self.search_config = config.get("search", {})
        self.model_type = self.search_config.get("embedding_model", "clip")
        self.embedding_model = None
        self._resolved_dummy_image = None
        self._init_model()

    def _init_model(self):
        if self.model_type == "clip":
            from poc.search.query import load_model
            model_name = self.search_config.get("clip_model", "clip-ViT-L-14")
            cache_dir = self.search_config.get("model_cache_dir")
            hf_mirror = self.search_config.get("hf_mirror")
            self.embedding_model = load_model(model_name, cache_dir=cache_dir, hf_mirror=hf_mirror)
            print(f"[EmbeddingActor] CLIP 模型加载成功: {model_name}")
        elif self.model_type == "qwen":
            from poc.search.qwen_embedding import Qwen3VLEmbedding
            api_url = self.search_config.get("qwen_api_url", "http://10.132.19.82:8010")
            timeout = self.search_config.get("qwen_timeout", 30)
            dummy_image = _resolve_qwen_dummy_image(self.config, self.search_config)
            self._resolved_dummy_image = dummy_image
            self.embedding_model = Qwen3VLEmbedding(api_url=api_url, timeout=timeout, dummy_image=dummy_image)
            print(f"[EmbeddingActor] Qwen3-VL 客户端初始化成功: {api_url}")

    def encode_text(self, text: str) -> np.ndarray:
        if self.model_type == "clip":
            return self.embedding_model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
        else:
            return self.embedding_model.encode_text(text)

    def encode_image(self, image_path: Union[str, Path]) -> np.ndarray:
        if self.model_type == "clip":
            from PIL import Image
            image = Image.open(image_path).convert("RGB")
            return self.embedding_model.encode(image, convert_to_numpy=True, normalize_embeddings=True)
        else:
            return self.embedding_model.encode_image(image_path)

    def encode_image_bytes(self, image_bytes: bytes) -> np.ndarray:
        """图像向量化（bytes 输入，避免路径传递问题）"""
        if self.model_type == "qwen":
            return self.embedding_model.encode_image_bytes(image_bytes)
        else:
            # CLIP: 从 bytes 加载
            from PIL import Image
            import io
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            return self.embedding_model.encode(image, convert_to_numpy=True, normalize_embeddings=True)

    def encode_batch(self, image_paths: List[str]) -> List[np.ndarray]:
        """批量编码（Daft 管线用）"""
        return [self.encode_image(p) for p in image_paths]

    def get_runtime_info(self) -> Dict[str, Optional[str]]:
        info: Dict[str, Optional[str]] = {"model_type": self.model_type}
        if self.model_type == "clip":
            info["clip_model"] = self.search_config.get("clip_model", "clip-ViT-L-14")
        elif self.model_type == "qwen":
            info["qwen_api_url"] = self.search_config.get("qwen_api_url", "http://10.132.19.82:8010")
            info["dummy_image"] = self._resolved_dummy_image
        return info


# ── VLAnalyzerActor ───────────────────────────────────────────────────────

def _image_to_base64(image_path: str) -> str:
    """将图片转换为 base64 编码"""
    from PIL import Image
    with Image.open(image_path) as img:
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode("utf-8")


@ray.remote
class VLAnalyzerActor:
    """VL 场景分析 Actor（VLLM HTTP 调用）"""

    TARGET_CLASSES = [
        "person", "car", "truck", "bus", "van", "motorcycle", "bicycle",
        "excavator", "bulldozer", "dump truck", "tractor", "trailer",
    ]

    def __init__(self, config: dict):
        self.config = config
        self.base_url = "http://10.132.19.82:50100"
        self.api_key = "sk-8fA3kP2QxR7mJ9WZC6dE0T1B4yH5VnL"
        self.model = "/models/Qwen/Qwen3-VL-8B-Instruct"
        self.client = None
        self._init_client()

    def _init_client(self):
        try:
            from openai import OpenAI
            self.client = OpenAI(
                base_url=self.base_url + "/v1",
                api_key=self.api_key,
            )
            print("[VLAnalyzerActor] VLLM 客户端初始化成功")
        except Exception as e:
            print(f"[VLAnalyzerActor] VLLM 客户端初始化失败: {e}")

    def detect_image(self, image_path: str) -> List[Dict]:
        """VL 图片检测（与 AutoLabelEngine.detect_image 逻辑一致）"""
        if self.client is None:
            return []

        from PIL import Image
        b64 = _image_to_base64(image_path)
        image_url = f"data:image/jpeg;base64,{b64}"
        img = Image.open(image_path)
        w, h = img.size

        classes_str = ", ".join(self.TARGET_CLASSES)
        prompt = f"""你是一个目标检测系统。
请检测图像中所有可以识别的目标。
仅检测以下目标类别：{classes_str}

输出格式：仅输出 JSON 数组，每个元素包含 class, confidence, bbox（归一化坐标 [x1,y1,x2,y2]）。
不要输出任何解释性文字。"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }],
                max_tokens=2048,
                temperature=0.1,
            )
            output = response.choices[0].message.content
            return self._parse_json_detections(output, w, h)
        except Exception as e:
            print(f"[VLAnalyzerActor] detect_image 失败: {e}")
            return []

    def describe_image(self, image_path: str) -> str:
        """场景描述"""
        if self.client is None:
            return ""

        b64 = _image_to_base64(image_path)
        image_url = f"data:image/jpeg;base64,{b64}"

        prompt = """请仔细观察图片，用简洁的中文描述场景（2-3句话），包括场景类型、主要目标及行为、异常情况。
仅输出描述文本，不要输出 JSON。"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }],
                max_tokens=256,
                temperature=0.3,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"[VLAnalyzerActor] describe_image 失败: {e}")
            return ""

    def describe_video(self, video_path: str) -> str:
        """视频描述（采样首帧）"""
        import cv2
        cap = cv2.VideoCapture(video_path)
        ret, frame = cap.read()
        cap.release()
        if not ret:
            return ""

        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            cv2.imwrite(f.name, frame)
            tmp_path = f.name
        try:
            return self.describe_image(tmp_path)
        finally:
            os.unlink(tmp_path)

    def recognize_crops(self, image_path: str, yolo_detections: List[Dict]) -> List[Dict]:
        """YOLO+VL 混合检测的 VL 识别部分：对 YOLO 裁剪区域做类别识别"""
        if self.client is None or not yolo_detections:
            return yolo_detections

        from PIL import Image
        img = Image.open(image_path)
        w, h = img.size

        classes_str = ", ".join(self.TARGET_CLASSES)
        crops_info = []
        for i, det in enumerate(yolo_detections):
            bbox = det.get("bbox_norm", det.get("bbox", []))
            if len(bbox) != 4:
                continue
            x1p, y1p = int(bbox[0] * w), int(bbox[1] * h)
            x2p, y2p = int(bbox[2] * w), int(bbox[3] * h)
            crop = img.crop((x1p, y1p, x2p, y2p))
            buf = io.BytesIO()
            crop.save(buf, format="JPEG", quality=85)
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            crops_info.append((i, b64, bbox))

        results = []
        for idx, b64, bbox in crops_info:
            prompt = f"这个裁剪区域中的目标属于以下哪个类别？{classes_str}\n仅输出类别名称，不要输出其他内容。"
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                        ],
                    }],
                    max_tokens=32,
                    temperature=0.1,
                )
                cls = resp.choices[0].message.content.strip().lower()
                if cls in self.TARGET_CLASSES:
                    det = yolo_detections[idx].copy()
                    det["class"] = cls
                    det["bbox"] = bbox
                    results.append(det)
            except Exception:
                pass

        return results

    def _parse_json_detections(self, output: str, w: int, h: int) -> List[Dict]:
        """解析 VL 模型的 JSON 检测输出"""
        try:
            json_match = re.search(r"```json\s*\n(.+?)\n```", output, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                start = output.find("[")
                end = output.rfind("]") + 1
                if start >= 0 and end > start:
                    json_str = output[start:end]
                else:
                    return []

            items = json.loads(json_str)
            results = []
            for item in items:
                cls = item.get("class", "").lower()
                if cls not in self.TARGET_CLASSES:
                    continue
                bbox = item.get("bbox", [])
                if len(bbox) != 4:
                    continue
                # 确保归一化坐标
                if all(0 <= v <= 1 for v in bbox):
                    results.append({
                        "class": cls,
                        "confidence": float(item.get("confidence", 0.5)),
                        "bbox": [float(v) for v in bbox],
                    })
            return results
        except Exception:
            return []
