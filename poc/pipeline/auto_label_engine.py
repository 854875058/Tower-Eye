"""
自动标注算法引擎 - 基于 YOLOv26x 本地模型检测 + 目标跟踪
"""

import sys
import tempfile
import time
import os
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from PIL import Image, ImageDraw
import base64
import io
import json
import re
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 模型路径
MODEL_PATH = ROOT / "data" / "pretrainModel" / "yolo26x.pt"


# 目标类别配置
TARGET_CLASSES = {
    'person': 0, 'car': 2, 'truck': 7, 'bus': 5, 'van': 8,
    'motorcycle': 3, 'bicycle': 1,
    'excavator': 11, 'bulldozer': 12, 'dump truck': 24, 'tractor': 25, 'trailer': 26
}

CLASS_NAMES_CN = {
    'person': '人', 'car': '汽车', 'truck': '卡车', 'bus': '公交车', 'van': '面包车',
    'motorcycle': '摩托车', 'bicycle': '自行车',
    'excavator': '挖掘机', 'bulldozer': '推土机', 'dump truck': '卸土车', 'tractor': '拖拉机', 'trailer': '挂车'
}

# 跟踪器颜色
TRACK_COLORS = [
    (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255),
    (255, 0, 255), (255, 128, 0), (128, 255, 0), (0, 128, 255), (255, 0, 128),
    (128, 0, 255), (0, 255, 128), (255, 128, 128), (128, 255, 128), (128, 128, 255)
]


def get_track_color(track_id: int) -> Tuple[int, int, int]:
    """获取跟踪ID对应的颜色"""
    return TRACK_COLORS[track_id % len(TRACK_COLORS)]


def xywh_to_tlbr(x: float, y: float, w: float, h: float) -> Tuple[float, float, float, float]:
    """xywh 转 tlbr (top-left, bottom-right)"""
    return x, y, x + w, y + h


def tlbr_to_xywh(x1: float, y1: float, x2: float, y2: float) -> Tuple[float, float, float, float]:
    """tlbr 转 xywh"""
    return x1, y1, x2 - x1, y2 - y1


def compute_iou(box1: Tuple[float, float, float, float], box2: Tuple[float, float, float, float]) -> float:
    """计算两个边界框的 IoU"""
    x1, y1, x2, y2 = box1
    x1_, y1_, x2_, y2_ = box2

    # 计算交集
    inter_x1 = max(x1, x1_)
    inter_y1 = max(y1, y1_)
    inter_x2 = min(x2, x2_)
    inter_y2 = min(y2, y2_)

    if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
        return 0.0

    inter_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)

    # 计算并集
    area1 = (x2 - x1) * (y2 - y1)
    area2 = (x2_ - x1_) * (y2_ - y1_)
    union_area = area1 + area2 - inter_area

    if union_area <= 0:
        return 0.0

    return inter_area / union_area


class KalmanBoxTracker:
    """简单的卡尔曼滤波器跟踪单个目标"""

    def __init__(self, bbox: Tuple[float, float, float, float]):
        self.bbox = bbox  # [x1, y1, x2, y2]
        self.id = None  # 跟踪ID由外部分配
        self.age = 0  # 存在帧数
        self.time_since_update = 0  # 距上次更新的帧数
        self.hits = 0  # 命中次数
        self.hit_streak = 0  # 连续命中次数

        # 状态: [x, y, w, h, vx, vy]
        self.x_state = np.zeros(6)
        self._init_state(bbox)

        # 卡尔曼矩阵
        self._init_kalman()

    def _init_state(self, bbox: Tuple[float, float, float, float]):
        """初始化状态"""
        x1, y1, x2, y2 = bbox
        cx, cy, w, h = (x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1
        self.x_state = np.array([cx, cy, w, h, 0, 0])

    def _init_kalman(self):
        """初始化卡尔曼滤波器参数"""
        n_state = 6  # [cx, cy, w, h, vx, vy]
        n_obs = 4    # [cx, cy, w, h]
        dt = 1.0

        # 状态转移矩阵 (6x6)
        self.F = np.eye(n_state)
        self.F[0, 4] = dt  # cx += vx * dt
        self.F[1, 5] = dt  # cy += vy * dt

        # 观测矩阵 (4x6)
        self.H = np.zeros((n_obs, n_state))
        for i in range(n_obs):
            self.H[i, i] = 1

        # 状态协方差矩阵 (6x6)
        self.P = np.eye(n_state) * 10

        # 过程噪声 (6x6)
        self.Q = np.eye(n_state) * 0.1
        self.Q[4, 4] = 0.5  # vx noise
        self.Q[5, 5] = 0.5  # vy noise

        # 观测噪声 (4x4)
        self.R = np.eye(n_obs) * 1

    def predict(self) -> Tuple[float, float, float, float]:
        """预测下一帧位置"""
        self.age += 1
        self.time_since_update += 1

        # 卡尔曼预测
        self.x_state = self.F @ self.x_state
        self.P = self.F @ self.P @ self.F.T + self.Q

        cx, cy, w, h = self.x_state[:4]
        x1, y1 = cx - w / 2, cy - h / 2
        x2, y2 = cx + w / 2, cy + h / 2

        return (x1, y1, x2, y2)

    def update(self, bbox: Tuple[float, float, float, float]):
        """更新状态"""
        self.time_since_update = 0
        self.hits += 1
        self.hit_streak += 1

        x1, y1, x2, y2 = bbox
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        w, h = x2 - x1, y2 - y1

        # 卡尔曼更新
        z = np.array([cx, cy, w, h])
        y_res = z - self.H @ self.x_state
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.x_state = self.x_state + K @ y_res
        self.P = (np.eye(6) - K @ self.H) @ self.P

        self.bbox = self.predict()
        return self.bbox

    def get_state(self) -> Tuple[float, float, float, float]:
        """获取当前状态"""
        return self.bbox


class SimpleTracker:
    """简单的 IoU + 卡尔曼滤波多目标跟踪器"""

    def __init__(self, iou_threshold: float = 0.3, max_age: int = 30, min_hits: int = 1):
        """
        Args:
            iou_threshold: IoU 匹配阈值
            max_age: 最大丢失帧数
            min_hits: 最小命中次数
        """
        self.iou_threshold = iou_threshold
        self.max_age = max_age
        self.min_hits = min_hits

        self.trackers: List[KalmanBoxTracker] = []
        self.track_id_count = 0

    def update(self, detections: List[Dict], img_size: Tuple[int, int] = None) -> List[Dict]:
        """
        更新跟踪器

        Args:
            detections: 检测结果列表 [{class, confidence, bbox, ...}]
            img_size: 图像尺寸 (w, h)

        Returns:
            带跟踪ID的结果列表 [{class, confidence, bbox, track_id, ...}]
        """
        if not detections:
            # 没有检测时，仅预测
            for tracker in self.trackers:
                tracker.predict()
            return []

        # 预测所有跟踪器
        for tracker in self.trackers:
            tracker.predict()

        # 匹配检测与跟踪器
        matched, unmatched_dets, unmatched_trks = self._match(detections)

        # 更新匹配的跟踪器
        for m in matched:
            det_idx, trk_idx = m
            bbox = detections[det_idx]['bbox']
            if img_size:
                bbox = self._normalize_bbox(bbox, img_size)
            self.trackers[trk_idx].update(bbox)

        # 创建新的跟踪器
        for det_idx in unmatched_dets:
            bbox = detections[det_idx]['bbox']
            if img_size:
                bbox = self._normalize_bbox(bbox, img_size)
            tracker = KalmanBoxTracker(bbox)
            tracker.id = self.track_id_count
            tracker.hits = 1  # 新创建的tracker立即计为命中1次
            # 保存检测的类别信息
            tracker.det_class = detections[det_idx].get('class', 'unknown')
            tracker.det_class_id = detections[det_idx].get('class_id', 0)
            tracker.det_confidence = detections[det_idx].get('confidence', 0.0)
            self.track_id_count += 1
            self.trackers.append(tracker)

        # 移除丢失的跟踪器
        self.trackers = [t for t in self.trackers
                        if t.time_since_update <= self.max_age and t.hit_streak >= 0]

        # 构建结果
        result = []
        for tracker in self.trackers:
            if tracker.time_since_update == 0 and tracker.hits >= self.min_hits:
                x1, y1, x2, y2 = tracker.get_state()
                if img_size:
                    x1, y1, x2, y2 = self._denormalize_bbox([x1, y1, x2, y2], img_size)
                result.append({
                    'class': getattr(tracker, 'det_class', 'unknown'),
                    'class_id': getattr(tracker, 'det_class_id', 0),
                    'confidence': getattr(tracker, 'det_confidence', 0.0),
                    'bbox': [int(x1), int(y1), int(x2), int(y2)],
                    'track_id': tracker.id,
                    'age': tracker.age,
                    'hits': tracker.hits
                })

        return result

    def _normalize_bbox(self, bbox: List, img_size: Tuple[int, int]) -> Tuple:
        """归一化边界框"""
        w, h = img_size
        x1, y1, x2, y2 = bbox
        return (x1 / w, y1 / h, x2 / w, y2 / h)

    def _denormalize_bbox(self, bbox: List, img_size: Tuple[int, int]) -> Tuple:
        """反归一化边界框"""
        w, h = img_size
        x1, y1, x2, y2 = bbox
        return (x1 * w, y1 * h, x2 * w, y2 * h)

    def _match(self, detections: List[Dict]) -> Tuple[List, List, List]:
        """使用 Hungarian 算法匹配"""
        n_dets = len(detections)
        n_trks = len(self.trackers)

        if n_trks == 0:
            return [], list(range(n_dets)), []

        # 构建 IoU 矩阵
        iou_matrix = np.zeros((n_dets, n_trks))
        for i, det in enumerate(detections):
            det_bbox = tuple(det['bbox'])
            for j, trk in enumerate(self.trackers):
                trk_bbox = trk.get_state()
                iou_matrix[i, j] = compute_iou(det_bbox, trk_bbox)

        # 使用 IoU 阈值过滤
        matched_indices = []
        used_trks = set()

        # 优先匹配高 IoU
        while True:
            best_iou = self.iou_threshold
            best_pair = None

            for i in range(n_dets):
                if i in used_trks:
                    continue
                for j in range(n_trks):
                    if j in used_trks:
                        continue
                    if iou_matrix[i, j] > best_iou:
                        best_iou = iou_matrix[i, j]
                        best_pair = (i, j)

            if best_pair is None:
                break

            matched_indices.append(best_pair)
            used_trks.add(best_pair[0])
            used_trks.add(best_pair[1])

        unmatched_dets = [i for i in range(n_dets) if i not in used_trks]
        unmatched_trks = [j for j in range(n_trks) if j not in used_trks]

        return matched_indices, unmatched_dets, unmatched_trks

    def get_track_info(self, track_id: int) -> Optional[Dict]:
        """获取指定跟踪ID的信息"""
        for trk in self.trackers:
            if trk.id == track_id:
                return {
                    'id': trk.id,
                    'bbox': trk.bbox,
                    'age': trk.age,
                    'hits': trk.hits
                }
        return None


def image_to_base64(image_path: str) -> str:
    """将图片转换为 base64 编码"""
    with Image.open(image_path) as img:
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=85)
        return base64.b64encode(buffer.getvalue()).decode('utf-8')


class AutoLabelEngine:
    """自动标注引擎 - 支持 VLLM API 图片检测 + YOLOv26x 视频检测"""

    def __init__(self, base_url: str = None, api_key: str = None, model: str = None,
                 yolo_model_path: str = None, confidence_threshold: float = 0.25):
        """
        初始化引擎

        Args:
            base_url: VLLM API 地址（用于图片检测）
            api_key: VLLM API 密钥
            model: VLLM 模型名称
            yolo_model_path: YOLOv26x 模型文件路径（用于视频检测）
            confidence_threshold: YOLO 检测置信度阈值
        """
        # 项目根目录
        self.base_dir = Path(__file__).resolve().parent.parent

        # VLLM API 配置（用于图片检测）
        self.base_url = base_url or "http://10.132.19.82:50100"
        self.api_key = api_key or "sk-8fA3kP2QxR7mJ9WZC6dE0T1B4yH5VnL"
        self.model = model or "/models/Qwen/Qwen3-VL-8B-Instruct"
        self.client = None

        # YOLOv26x 配置（用于视频检测）
        self.confidence_threshold = confidence_threshold
        self.yolo_model = None
        self.yolo_model_path = yolo_model_path or str(MODEL_PATH)

        self._init_vllm_client()
        self._init_yolo_model()

    def _init_vllm_client(self):
        """初始化 VLLM API 客户端（用于图片检测）"""
        try:
            from openai import OpenAI
            self.client = OpenAI(
                base_url=self.base_url + "/v1",
                api_key=self.api_key,
            )
            print(f"[AutoLabel] VLLM API 客户端初始化成功（图片检测）")
        except Exception as e:
            print(f"[AutoLabel] VLLM API 客户端初始化失败: {e}")
            self.client = None

    def _init_yolo_model(self):
        """初始化 YOLOv26x 模型（用于视频检测）"""
        try:
            from ultralytics import YOLO
            # 启用混合精度和推理优化
            self.yolo_model = YOLO(self.yolo_model_path)
            self.yolo_model.fuse()  # 融合模型层加速
            print(f"[AutoLabel] YOLOv26x 模型加载成功: {self.yolo_model_path}")
        except Exception as e:
            print(f"[AutoLabel] YOLOv26x 模型加载失败: {e}")
            self.yolo_model = None

    def _get_yolo_class_name(self, class_id: int) -> str:
        """将 YOLO class_id 转换为类别名称"""
        class_mapping = {
            0: 'person', 1: 'bicycle', 2: 'car', 3: 'motorcycle',
            5: 'bus', 7: 'truck', 8: 'van',
            11: 'excavator', 12: 'bulldozer', 24: 'dump truck', 25: 'tractor', 26: 'trailer',
        }
        return class_mapping.get(class_id, 'unknown')

    def detect_image(self, image_path: str) -> List[Dict]:
        """检测单张图片 - 使用 VLLM API"""
        if self.client is None:
            print("[AutoLabel] VLLM API 不可用，无法检测")
            return []

        print(f"\n[AutoLabel] === VLLM 检测: {Path(image_path).name} ===")

        try:
            b64_image = image_to_base64(image_path)
            image_url = f"data:image/jpeg;base64,{b64_image}"
        except Exception as e:
            print(f"[AutoLabel] 图片编码失败: {e}")
            return []

        img = Image.open(image_path)
        w, h = img.size

        prompt = f"""你是一个目标检测系统。

请检测图像中所有可以识别的目标。

仅检测以下目标类别（不得输出其他类别）：
person, car, truck, bus, van, motorcycle, bicycle,
excavator, bulldozer, dump truck, tractor, trailer

检测要求：
- 检测图像中所有可见实例，包括远处、小目标、被部分遮挡的目标。
- 工程场景中的车辆需要仔细区分：
  - 装载土石的工程卡车使用 "dump truck"
  - 带有挖掘机械臂的履带或轮式工程车使用 "excavator"
  - 用于推土或整平地面的工程车使用 "bulldozer"
  - 农业或工业用拖拉机使用 "tractor"
  - 无动力、被牵引的车辆使用 "trailer"
- 如多个类别相似，请选择最符合视觉外观的类别。
- 不要虚构不存在的目标。
- 不要将多个目标合并为一个检测框。

输出格式要求：
- 仅输出 JSON 数组，不要输出任何解释性文字。
- 每个检测结果必须严格遵循以下格式：

[
  {
    "class": "car",
    "confidence": 0.85,
    "bbox": [x1, y1, x2, y2]
  }
]

边界框（bbox）要求：
- 使用 0 到 1 的归一化坐标
- [x1, y1] 为左上角坐标
- [x2, y2] 为右下角坐标
- 所有坐标必须为浮点数

严格约束：
- 只允许输出合法 JSON
- 不允许输出注释、说明、Markdown 或多余文本
- 不允许输出不在目标类别列表中的类别
"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": image_url}}
                        ]
                    }
                ],
                max_tokens=2048,
                temperature=0.1,
            )

            output = response.choices[0].message.content

            print(f"\n{'='*60}")
            print(f"[Debug VLLM] 图片: {Path(image_path).name}")
            print(f"[Debug VLLM] 图片尺寸: {w}x{h}")

            # 打印原始输出
            print(f"[Debug VLLM] 原始输出:")
            print(f"{'-'*40}")
            print(output[:500] if len(output) > 500 else output)
            print(f"{'-'*40}")

            results = self._parse_vllm_output(output, w, h)

            print(f"[Debug VLLM] 解析结果: {len(results)} 个目标")
            if results:
                for r in results:
                    print(f"  - {r['class']}: bbox={r['bbox']}, conf={r.get('confidence', 0):.2f}")
            else:
                print(f"[Debug VLLM] 警告: 未检测到任何目标！")
            print(f"{'='*60}\n")

            return results

        except Exception as e:
            print(f"[AutoLabel] VLLM 检测失败: {e}")
            return []

    def _parse_vllm_output(self, output: str, w: int, h: int) -> List[Dict]:
        """解析 VLLM JSON 输出"""
        results = []

        try:
            # 尝试提取 JSON
            json_match = re.search(r'```json\s*\n(.+?)\n```', output, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
                print(f"[Debug VLLM] 从 ```json 块提取 JSON")
            else:
                start = output.find('[')
                end = output.rfind(']') + 1
                if start >= 0 and end > start:
                    json_str = output[start:end]
                    print(f"[Debug VLLM] 从原始文本提取 JSON")
                else:
                    print(f"[Debug VLLM] 错误: 无法找到 JSON 数组")
                    print(f"[Debug VLLM] 原始输出: {output[:200]}...")
                    return results

            json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
            json_str = json_str.replace(';', ',')
            json_str = re.sub(r"'([^']*?)'", r'"\1"', json_str)

            print(f"[Debug VLLM] 清理后的JSON: {json_str[:200]}...")

            data = json.loads(json_str)
            if not isinstance(data, list):
                print(f"[Debug VLLM] 错误: JSON 不是数组类型")
                return results

            print(f"[Debug VLLM] 解析到 {len(data)} 个检测项")

            for item in data:
                if not isinstance(item, dict):
                    print(f"[Debug VLLM] 跳过: 项不是字典")
                    continue
                cls = item.get('class', '')
                print(f"[Debug VLLM] 检测到类别: '{cls}'")

                if cls not in TARGET_CLASSES:
                    print(f"[Debug VLLM] 跳过: 类别不在目标列表中")
                    print(f"[Debug VLLM] 允许的类别: {list(TARGET_CLASSES.keys())}")
                    continue

                bbox = item.get('bbox', [0, 0, 0, 0])
                print(f"[Debug VLLM] bbox={bbox}")

                if not all(isinstance(x, (int, float)) for x in bbox):
                    print(f"[Debug VLLM] 跳过: bbox 包含非数字")
                    continue

                is_normalized = all(x <= 1.0 for x in bbox)
                if is_normalized:
                    x1 = int(bbox[0] * w)
                    y1 = int(bbox[1] * h)
                    x2 = int(bbox[2] * w)
                    y2 = int(bbox[3] * h)
                else:
                    x1, y1, x2, y2 = [int(x) for x in bbox]

                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(w - 1, x2), min(h - 1, y2)

                if x2 > x1 and y2 > y1:
                    results.append({
                        'class': cls,
                        'class_id': TARGET_CLASSES[cls],
                        'confidence': item.get('confidence', 0.5),
                        'bbox': [x1, y1, x2, y2],
                        'manual': False
                    })
                    print(f"[Debug VLLM] ✓ 添加检测: {cls} at [{x1},{y1},{x2},{y2}]")
                else:
                    print(f"[Debug VLLM] 跳过: 无效的bbox尺寸 ({x1},{y1},{x2},{y2})")

        except json.JSONDecodeError as e:
            print(f"[Debug VLLM] JSON 解析错误: {e}")
            print(f"[Debug VLLM] 问题JSON: {json_str[:200]}...")
        except Exception as e:
            print(f"[Debug VLLM] 解析异常: {e}")
            import traceback
            traceback.print_exc()

        return results

    def detect_image_with_yolo(self, image_path: str) -> List[Dict]:
        """检测单张图片 - 使用 YOLOv26x 本地模型（用于视频检测）"""
        if self.yolo_model is None:
            print("[AutoLabel] YOLO 模型未加载，无法检测")
            return []

        print(f"\n[AutoLabel] === YOLO 检测: {Path(image_path).name} ===")

        try:
            results = self.yolo_model(image_path, conf=self.confidence_threshold, verbose=False)

            if not results or len(results) == 0:
                print(f"[AutoLabel] 未检测到目标")
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
                    x1_norm, y1_norm, w_norm, h_norm = xywhn

                    x1 = x1_norm - w_norm / 2
                    y1 = y1_norm - h_norm / 2
                    x2 = x1_norm + w_norm / 2
                    y2 = y1_norm + h_norm / 2

                    class_name = self._get_yolo_class_name(class_id)

                    if class_name != 'unknown':
                        detections.append({
                            'class': class_name,
                            'class_id': class_id,
                            'confidence': confidence,
                            'bbox': [x1, y1, x2, y2],
                            'manual': False
                        })

            print(f"[AutoLabel] YOLO 检测到 {len(detections)} 个目标")
            return detections

        except Exception as e:
            print(f"[AutoLabel] YOLO 检测失败: {e}")
            return []

    def describe_image(self, image_path: str, preview_dir: str = None) -> str:
        """使用 VL 模型描述图片场景"""
        img_p = Path(image_path)
        desc_path = Path(preview_dir) / (img_p.name.replace(img_p.suffix, '') + '_desc.txt') if preview_dir else None

        # 如果有预览目录，先尝试读取已保存的描述
        if preview_dir and desc_path and desc_path.exists():
            with open(desc_path, 'r', encoding='utf-8') as f:
                return f.read().strip()

        if self.client is None:
            print("[AutoLabel] VLLM API 不可用，无法描述图片")
            return ""

        print(f"\n[AutoLabel] === VL 场景描述: {Path(image_path).name} ===")

        try:
            b64_image = image_to_base64(image_path)
            image_url = f"data:image/jpeg;base64,{b64_image}"

            prompt = """你是一个视频智能分析系统。

请仔细观察图片，描述图片中的场景，包括：
1. 场景类型（如道路、工地、十字路口、停车场等）
2. 主要目标及其行为（如车辆行驶、行人行走、工程作业等）
3. 异常情况（如烟雾、火光、闯红灯、违规操作等）

请用简洁的中文描述，2-3句话即可。

输出格式要求：
- 仅输出描述文本，不要输出 JSON
- 不要输出"图片显示"或"场景描述"等前缀
"""

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": image_url}}
                        ]
                    }
                ],
                max_tokens=256,
                temperature=0.3,
            )

            description = response.choices[0].message.content.strip()
            print(f"[AutoLabel] 场景描述: {description}")

            # 保存描述到文件
            if preview_dir:
                Path(preview_dir).mkdir(parents=True, exist_ok=True)
                with open(desc_path, 'w', encoding='utf-8') as f:
                    f.write(description)

            return description

        except Exception as e:
            print(f"[AutoLabel] 场景描述失败: {e}")
            # 尝试读取缓存
            if preview_dir and desc_path and desc_path.exists():
                with open(desc_path, 'r', encoding='utf-8') as f:
                    cached = f.read().strip()
                    if cached:
                        print(f"[AutoLabel] 使用缓存描述")
                        return cached
            return ""

    def describe_video(self, video_path: str, preview_dir: str = None, max_frames: int = 2) -> str:
        """使用 VL 模型描述视频场景（采样多帧分析）"""
        video_p = Path(video_path)
        desc_path = Path(preview_dir) / (video_p.name.replace(video_p.suffix, '') + '_desc.txt') if preview_dir else None

        # 如果有预览目录，先尝试读取已保存的描述
        if preview_dir and desc_path and desc_path.exists():
            with open(desc_path, 'r', encoding='utf-8') as f:
                return f.read().strip()

        if self.client is None:
            print("[AutoLabel] VLLM API 不可用，无法描述视频")
            return ""

        print(f"\n[AutoLabel] === VL 视频场景描述: {Path(video_path).name} ===")

        try:
            import cv2
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                print(f"[AutoLabel] 无法打开视频: {video_path}")
                return ""

            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS)

            # 采样关键帧（首帧、中间帧、末帧）
            frame_indices = []
            if total_frames >= 3:
                frame_indices = [0, total_frames // 2, total_frames - 1]
            elif total_frames > 0:
                frame_indices = list(range(total_frames))

            frames_base64 = []
            for idx in frame_indices:
                cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                ret, frame = cap.read()
                if ret:
                    # 调整为较小尺寸以减少 token 数量
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    temp_img = Image.fromarray(frame_rgb)
                    temp_img = temp_img.resize((320, 320), Image.LANCZOS)
                    temp_path = os.path.join(tempfile.gettempdir(), f"video_frame_{idx}.jpg")
                    temp_img.save(temp_path, quality=80)
                    b64_image = image_to_base64(temp_path)
                    frames_base64.append(b64_image)

            cap.release()

            if not frames_base64:
                return ""

            # 简化的 prompt
            prompt = "观察以下视频帧，描述场景、目标、行为和事件。"

            # 构建消息
            content = [{"type": "text", "text": prompt}]
            for b64_image in frames_base64:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}
                })

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": content}],
                max_tokens=256,
                temperature=0.3,
            )

            description = response.choices[0].message.content.strip()
            print(f"[AutoLabel] 视频场景描述: {description}")

            # 保存描述到文件
            if preview_dir:
                Path(preview_dir).mkdir(parents=True, exist_ok=True)
                with open(desc_path, 'w', encoding='utf-8') as f:
                    f.write(description)

            return description

        except Exception as e:
            print(f"[AutoLabel] 视频场景描述失败: {e}")
            # 尝试读取缓存
            if preview_dir and desc_path and desc_path.exists():
                with open(desc_path, 'r', encoding='utf-8') as f:
                    cached = f.read().strip()
                    if cached:
                        print(f"[AutoLabel] 使用缓存描述")
                        return cached
            return ""

    def detect_image_yolo_then_vl(self, image_path: str, vl_detect_size: int = 448,
                                    preview_dir: str = None) -> List[Dict]:
        """
        混合检测：先用 YOLO 定位目标，再用 VL 模型识别类别

        优点：
        - YOLO 定位快速准确
        - VL 模型可以准确区分相似类别（truck/dump truck/excavator）

        Args:
            image_path: 图片路径
            vl_detect_size: VL模型裁剪后的图片尺寸（越大越慢但识别越准）
            preview_dir: 预览图片保存目录
        """
        if self.yolo_model is None:
            print("[AutoLabel] YOLO 模型未加载，无法检测")
            return []
        if self.client is None:
            print("[AutoLabel] VLLM API 不可用，无法识别")
            return []

        print(f"\n[AutoLabel] === YOLO+VL 混合检测: {Path(image_path).name} ===")

        try:
            # 1. 用 YOLO 检测目标位置
            yolo_results = self.yolo_model(image_path, conf=self.confidence_threshold, verbose=False)

            if not yolo_results or len(yolo_results) == 0 or yolo_results[0].boxes is None:
                print(f"[AutoLabel] YOLO 未检测到任何目标")
                return []

            img = Image.open(image_path)
            w, h = img.size

            # 提取 YOLO 检测的 bbox
            yolo_detections = []
            for box in yolo_results[0].boxes:
                xywhn = box.xywhn.cpu().numpy()[0]
                x1_norm, y1_norm, w_norm, h_norm = xywhn
                x1 = x1_norm - w_norm / 2
                y1 = y1_norm - h_norm / 2
                x2 = x1_norm + w_norm / 2
                y2 = y1_norm + h_norm / 2
                yolo_detections.append({
                    'bbox_norm': [x1, y1, x2, y2],  # 归一化坐标
                    'yolo_confidence': float(box.conf.item()),
                })

            print(f"[AutoLabel] YOLO 检测到 {len(yolo_detections)} 个目标")

            if len(yolo_detections) == 0:
                return []

            # 2. 用 VL 模型识别每个目标
            # 将所有目标裁剪并拼接成一张图，加快识别速度
            final_detections = self._vl_recognize_crops(image_path, yolo_detections, w, h, vl_detect_size)

            print(f"[AutoLabel] 混合检测完成: {len(final_detections)} 个目标")

            # 保存预览和结果
            if preview_dir and final_detections:
                import cv2 as cv2_module
                img_p = Path(image_path)
                preview_img_path = Path(preview_dir) / (img_p.name.replace(img_p.suffix, '') + '_preview.jpg')
                json_path = Path(preview_dir) / (img_p.name.replace(img_p.suffix, '') + '_result.json')

                # 绘制标注预览图片
                img_pil = Image.open(image_path)
                draw = ImageDraw.Draw(img_pil)
                colors = {
                    'person': (0, 255, 0), 'car': (0, 128, 255), 'truck': (255, 128, 0), 'bus': (128, 0, 255),
                    'van': (135, 206, 250), 'motorcycle': (255, 0, 128), 'bicycle': (0, 255, 255),
                    'excavator': (255, 165, 0), 'bulldozer': (0, 206, 209), 'dump truck': (255, 20, 147),
                    'tractor': (147, 112, 219), 'trailer': (255, 215, 0)
                }
                w, h = img_pil.size
                for det in final_detections:
                    bbox = det.get('bbox', [])
                    if len(bbox) == 4:
                        x1 = int(bbox[0] * w)
                        y1 = int(bbox[1] * h)
                        x2 = int(bbox[2] * w)
                        y2 = int(bbox[3] * h)
                        cls = det.get('class', 'unknown')
                        c = colors.get(cls, (255, 128, 0))
                        draw.rectangle([x1, y1, x2, y2], outline=c, width=3)
                        label = CLASS_NAMES_CN.get(cls, cls)
                        draw.rectangle([x1, y1 - 20, x1 + 100, y1], fill=c)
                        draw.text((x1 + 5, y1 - 18), label, fill=(255, 255, 255))

                preview_img = cv2_module.cvtColor(np.array(img_pil), cv2_module.COLOR_RGB2BGR)
                cv2_module.imwrite(str(preview_img_path), preview_img)

                # 保存JSON结果
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(final_detections, f, indent=2, ensure_ascii=False)

                print(f"[AutoLabel] 预览已保存: {preview_img_path}")

            return final_detections

        except Exception as e:
            print(f"[AutoLabel] 混合检测失败: {e}")
            import traceback
            traceback.print_exc()
            return []

    def _vl_recognize_crops(self, image_path: str, yolo_detections: List, w: int, h: int,
                             crop_size: int = 448) -> List[Dict]:
        """
        将 YOLO 检测的目标裁剪后用 VL 模型识别类别
        将多个裁剪图拼接成一张图，一次性识别
        """
        import cv2
        from PIL import Image

        img = Image.open(image_path)
        img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

        # 裁剪所有目标区域
        crops = []
        for det in yolo_detections:
            x1, y1, x2, y2 = det['bbox_norm']
            # 转换为像素坐标
            x1_px = int(x1 * w)
            y1_px = int(y1 * h)
            x2_px = int(x2 * w)
            y2_px = int(y2 * h)
            # 稍微扩展一点
            pad = 10
            x1_px = max(0, x1_px - pad)
            y1_px = max(0, y1_px - pad)
            x2_px = min(w, x2_px + pad)
            y2_px = min(h, y2_px + pad)
            crop = img_cv[y1_px:y2_px, x1_px:x2_px]
            if crop.size > 0:
                crop_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
                crop_pil = Image.fromarray(crop_rgb)
                # 缩放到固定大小
                crop_pil = crop_pil.resize((crop_size, crop_size), Image.LANCZOS)
                crops.append(crop_pil)

        if len(crops) == 0:
            return []

        # 拼接成网格
        n = len(crops)
        cols = min(n, 4)  # 最多4列
        rows = (n + cols - 1) // cols

        grid_w = cols * crop_size
        grid_h = rows * crop_size
        grid = Image.new('RGB', (grid_w, grid_h), (255, 255, 255))

        for i, crop in enumerate(crops):
            row = i // cols
            col = i % cols
            grid.paste(crop, (col * crop_size, row * crop_size))

        # 添加编号标签
        draw = ImageDraw.Draw(grid)
        for i in range(n):
            row = i // cols
            col = i % cols
            label = f"#{i}"
            draw.text((col * crop_size + 5, row * crop_size + 5), label, fill=(255, 0, 0))

        # 保存临时图片
        import tempfile
        temp_path = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
        grid.save(temp_path.name, quality=95)

        # 编码图片
        b64_image = image_to_base64(temp_path.name)
        image_url = f"data:image/jpeg;base64,{b64_image}"

        # VL 模型 prompt
        prompt = f"""识别图中所有编号的目标是什么类别。

目标类别列表：
person, car, truck, bus, van, motorcycle, bicycle,
excavator, bulldozer, dump truck, tractor, trailer

注意：
- dump truck 是装载土石的工程卡车
- excavator 是带有挖掘机械臂的挖掘机
- bulldozer 是推土机
- tractor 是拖拉机
- trailer 是无动力的挂车

请严格按照以下 JSON 格式输出，仅输出 JSON：
[
  {{"index": 0, "class": "car"}},
  {{"index": 1, "class": "truck"}}
]
不要输出置信度，只输出类别。
"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": image_url}}
                        ]
                    }
                ],
                max_tokens=512,
                temperature=0.1,
            )

            output = response.choices[0].message.content
            print(f"[AutoLabel] VL 原始输出: {output[:200]}...")

            # 解析 VL 输出
            # 提取 JSON
            json_match = re.search(r'\[\s*\{.*?\}\s*\]', output, re.DOTALL)
            if json_match:
                vl_results = json.loads(json_match.group())
            else:
                vl_results = []

            print(f"[AutoLabel] VL 识别结果: {vl_results}")

            # 构建最终检测结果
            final_detections = []
            index_to_class = {r['index']: r['class'] for r in vl_results if 'index' in r and 'class' in r}

            for i, det in enumerate(yolo_detections):
                cls = index_to_class.get(i, 'unknown')
                if cls in TARGET_CLASSES:
                    final_detections.append({
                        'class': cls,
                        'class_id': TARGET_CLASSES[cls],
                        'confidence': det['yolo_confidence'],
                        'bbox': det['bbox_norm'],
                        'manual': False
                    })
                    print(f"[AutoLabel] ✓ #{i}: {cls}")
                else:
                    print(f"[AutoLabel] ✗ #{i}: {cls} (无效类别)")

            # 清理临时文件
            import os
            os.unlink(temp_path.name)

            return final_detections

        except Exception as e:
            print(f"[AutoLabel] VL 识别失败: {e}")
            # 返回 YOLO 检测结果
            final_detections = []
            for det in yolo_detections:
                yolo_cls = self._get_yolo_class_name(0)  # 默认
                final_detections.append({
                    'class': yolo_cls,
                    'class_id': 0,
                    'confidence': det['yolo_confidence'],
                    'bbox': det['bbox_norm'],
                    'manual': False
                })
            return final_detections


    def detect_video(self, video_path: str, frame_interval: int = 5, detect_size: int = 320) -> Dict[int, List[Dict]]:
        """检测视频 - 使用 YOLO 模型，隔帧检测"""
        import cv2

        results = {}
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return results

        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if frame_idx % frame_interval == 0:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                detections = self._yolo_detect_frame_direct(frame_rgb, detect_size)
                results[frame_idx] = detections
            frame_idx += 1
        cap.release()

        print(f"[AutoLabel] 视频检测完成: {len(results)} 帧 (间隔 {frame_interval}, 分辨率 {detect_size})")
        return results

    def _process_video_segment(
        self,
        video_path: str,
        start_frame: int,
        end_frame: int,
        frame_interval: int,
        detect_size: int,
        yolo_model_path: str,
        confidence_threshold: float
    ) -> Tuple[int, Dict]:
        """
        处理视频的一个片段（用于多进程）

        Args:
            video_path: 视频路径
            start_frame: 起始帧号
            end_frame: 结束帧号（不包含）
            frame_interval: 检测间隔
            detect_size: 检测分辨率
            yolo_model_path: YOLO模型路径
            confidence_threshold: 置信度阈值

        Returns:
            (start_frame, results_dict)
        """
        import cv2

        # 每个进程独立初始化YOLO模型
        try:
            from ultralytics import YOLO
            yolo_model = YOLO(yolo_model_path)
            yolo_model.fuse()
        except Exception as e:
            print(f"[Worker] YOLO模型加载失败: {e}")
            return (start_frame, {})

        def detect_frame(frame_rgb):
            """单帧检测"""
            h, w = frame_rgb.shape[:2]
            scale = min(detect_size / h, detect_size / w)
            new_h, new_w = int(h * scale), int(w * scale)

            if scale < 1.0:
                frame_small = cv2.resize(frame_rgb, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
            else:
                frame_small = frame_rgb

            results = yolo_model(frame_small, conf=confidence_threshold, verbose=False)
            detections = []

            if results and len(results) > 0 and results[0].boxes is not None:
                result = results[0]
                for box in result.boxes:
                    class_id = int(box.cls.item())
                    confidence = float(box.conf.item())
                    xywhn = box.xywhn.cpu().numpy()[0]
                    x1_norm, y1_norm, w_norm, h_norm = xywhn

                    if scale < 1.0:
                        x1_norm = x1_norm / scale
                        y1_norm = y1_norm / scale
                        w_norm = w_norm / scale
                        h_norm = h_norm / scale

                    x1 = x1_norm - w_norm / 2
                    y1 = y1_norm - h_norm / 2
                    x2 = x1_norm + w_norm / 2
                    y2 = y1_norm + h_norm / 2

                    class_name = self._get_yolo_class_name(class_id)
                    if class_name != 'unknown':
                        detections.append({
                            'class': class_name,
                            'class_id': class_id,
                            'confidence': confidence,
                            'bbox': [x1, y1, x2, y2],
                            'manual': False
                        })
            return detections

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return (start_frame, {})

        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        results = {}
        frame_idx = start_frame
        while frame_idx < end_frame:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % frame_interval == 0:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                detections = detect_frame(frame_rgb)
                results[frame_idx] = detections

            frame_idx += 1

        cap.release()
        return (start_frame, results)

    def detect_video_with_tracking(
        self,
        video_path: str,
        save_preview: bool = True,
        preview_path: str = None,
        preview_dir: str = None,
        frame_interval: int = 3,  # 检测间隔，跳过中间帧
        detect_size: int = 320,  # 检测分辨率
        num_workers: int = 1  # 保留参数，未来扩展
    ) -> Dict[int, Dict]:
        """
        检测视频并跟踪目标 - 隔帧检测优化

        Args:
            video_path: 视频路径
            save_preview: 是否保存预览视频
            preview_path: 预览视频保存路径（完整路径）
            preview_dir: 预览视频保存目录（与 preview_path 二选一）
            frame_interval: 检测间隔（每隔几帧检测一次），跳过帧使用卡尔曼预测
            detect_size: 检测分辨率（160/320/640），越小越快

        Returns:
            Dict: {
                frame_idx: {
                    'detections': [{class, confidence, bbox}],
                    'tracks': [{bbox, track_id, class, class_id, confidence}],
                    'total_tracks': int
                }
            }
        """
        import cv2

        results = {}
        tracker = SimpleTracker(iou_threshold=0.3, max_age=30, min_hits=1)

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return results

        # 视频信息
        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        print(f"\n[AutoLabel] 开始处理视频: {Path(video_path).name}")
        print(f"[AutoLabel] 视频信息: {width}x{height}, {fps:.1f}fps, {total_frames}帧")
        print(f"[AutoLabel] 检测间隔: {frame_interval} 帧, 分辨率: {detect_size}")

        # 预览视频写入器
        out_writer = None
        preview_path_str = None
        if save_preview:
            if preview_path is None:
                video_p = Path(video_path)
                if preview_dir:
                    tmp_dir = Path(preview_dir)
                    tmp_dir.mkdir(parents=True, exist_ok=True)
                else:
                    tmp_dir = self.base_dir / "data" / "tmp" / "videos"
                    tmp_dir.mkdir(parents=True, exist_ok=True)
                preview_path_str = str(tmp_dir / (video_p.name.replace(video_p.suffix, '') + '_tracked.mp4'))
            else:
                preview_path_str = preview_path
            # 使用 H.264 编码，兼容性更好
            fourcc = cv2.VideoWriter_fourcc(*'avc1')
            out_writer = cv2.VideoWriter(preview_path_str, fourcc, fps, (width, height))

        frame_idx = 0
        total_detections = 0
        start_time = time.time()
        last_detection_frame = -1  # 上次检测的帧号

        print(f"[AutoLabel] 开始隔帧YOLO检测和跟踪 (间隔 {frame_interval})...")

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # 将BGR帧转为RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            # 判断是否需要YOLO检测
            need_detect = (frame_idx % frame_interval == 0) or (last_detection_frame < 0)

            if need_detect:
                # YOLO模型检测
                detections = self._yolo_detect_frame_direct(frame_rgb, detect_size)
                last_detection_frame = frame_idx
            else:
                # 仅预测（不检测），使用上一帧的检测结果更新跟踪器
                detections = []

            total_detections += len(detections)

            frame_anns = {
                'detections': detections,
                'tracks': [],
                'total_tracks': 0
            }

            # 更新跟踪器
            tracked = tracker.update(detections, (width, height))

            # 调试：打印第一帧的检测和跟踪结果
            if frame_idx == 0 and len(detections) > 0:
                print(f"[Debug] 检测结果(前3个):")
                for i, d in enumerate(detections[:3]):
                    print(f"  [{i}] bbox={d.get('bbox')}, cls={d.get('class')}")
            if frame_idx == 0 and len(tracked) > 0:
                print(f"[Debug] 跟踪结果(前3个):")
                for i, t in enumerate(tracked[:3]):
                    print(f"  [{i}] bbox={t.get('bbox')}, track_id={t.get('track_id')}, cls={t.get('class')}")

            # 跟踪器已自动保存类别信息，直接使用
            tracks_with_class = tracked

            # 调试：打印第一个跟踪的类别
            if frame_idx == 0 and tracked:
                print(f"[Debug] 跟踪类别: {tracked[0].get('class')}, track_id={tracked[0].get('track_id')}")

            frame_anns['tracks'] = tracks_with_class
            frame_anns['total_tracks'] = len(tracks_with_class)
            results[frame_idx] = frame_anns

            # 生成预览帧
            if out_writer is not None:
                preview_frame = self._draw_tracking_result(
                    frame.copy(),
                    tracks_with_class,
                    frame_idx
                )
                out_writer.write(preview_frame)

            # 打印进度
            if frame_idx % 30 == 0:
                elapsed = time.time() - start_time
                fps_processed = frame_idx / elapsed if elapsed > 0 else 0
                eta = (total_frames - frame_idx) / fps_processed / 60 if fps_processed > 0 else 0
                print(f"[AutoLabel] 处理: {frame_idx}/{total_frames} 帧, "
                      f"检测: {len(detections)}, 跟踪: {len(tracks_with_class)}, "
                      f"速度: {fps_processed:.1f}fps, 预计剩余: {eta:.1f}分钟")

            frame_idx += 1

        cap.release()

        if out_writer:
            out_writer.release()
            print(f"[AutoLabel] 预览视频已保存: {preview_path_str}")

        # 保存跟踪结果到JSON
        video_p = Path(video_path)
        if preview_dir:
            json_dir = Path(preview_dir)
        else:
            json_dir = self.base_dir / "data" / "tmp" / "videos"
        json_dir.mkdir(parents=True, exist_ok=True)
        json_path = json_dir / (video_p.name.replace(video_p.suffix, '') + '_tracks.json')
        self._save_tracking_results(results, str(json_path))

        total_time = time.time() - start_time
        print(f"\n[AutoLabel] 视频处理完成: {Path(video_path).name}")
        print(f"[AutoLabel] 总共 {len(results)} 帧, 检测到 {total_detections} 次目标")
        print(f"[AutoLabel] 最高同时跟踪 {self._get_max_concurrent_tracks(results)} 个目标")
        print(f"[AutoLabel] 处理时间: {total_time/60:.1f} 分钟")
        print(f"[AutoLabel] 跟踪结果已保存: {json_path}")

        return results

    def detect_video_parallel(
        self,
        video_path: str,
        num_workers: int = 4,
        frame_interval: int = 3,
        detect_size: int = 320
    ) -> Dict[int, List[Dict]]:
        """
        多进程并行检测视频（纯检测，不带跟踪）

        Args:
            video_path: 视频路径
            num_workers: 并行进程数（CPU核心数）
            frame_interval: 检测间隔
            detect_size: 检测分辨率

        Returns:
            Dict: {frame_idx: detections}
        """
        import cv2

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return {}

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()

        # 划分片段
        segment_size = max(100, total_frames // num_workers)
        segments = []
        for i in range(0, total_frames, segment_size):
            end = min(i + segment_size, total_frames)
            segments.append((i, end))

        print(f"[AutoLabel] 多进程检测: 划分为 {len(segments)} 个片段")

        # 进程参数
        yolo_model_path = str(self.yolo_model_path)
        args_list = [
            (video_path, start, end, frame_interval, detect_size, yolo_model_path, self.confidence_threshold)
            for start, end in segments
        ]

        all_results = {}

        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            futures = {executor.submit(self._process_segment, *args): args[0] for args in args_list}
            completed = 0
            for future in as_completed(futures):
                try:
                    start_frame, segment_results = future.result()
                    all_results.update(segment_results)
                    completed += 1
                    if completed % 2 == 0:
                        print(f"[AutoLabel] 进度: {completed}/{len(segments)} 片段")
                except Exception as e:
                    print(f"[AutoLabel] 片段处理失败: {e}")

        print(f"[AutoLabel] 多进程检测完成: {len(all_results)} 帧")
        return all_results

    def _process_segment(
        self,
        video_path: str,
        start_frame: int,
        end_frame: int,
        frame_interval: int,
        detect_size: int,
        yolo_model_path: str,
        confidence_threshold: float
    ) -> Tuple[int, Dict]:
        """多进程处理单个视频片段"""
        import cv2
        from ultralytics import YOLO

        try:
            yolo_model = YOLO(yolo_model_path)
            yolo_model.fuse()
        except Exception as e:
            print(f"[Worker] YOLO加载失败: {e}")
            return (start_frame, {})

        class_map = {0: 'person', 1: 'bicycle', 2: 'car', 3: 'motorcycle',
                    5: 'bus', 7: 'truck', 8: 'van', 11: 'excavator', 12: 'bulldozer',
                    24: 'dump truck', 25: 'tractor', 26: 'trailer'}

        def detect(frame_rgb):
            h, w = frame_rgb.shape[:2]
            scale = min(detect_size / h, detect_size / w)
            new_h, new_w = int(h * scale), int(w * scale)

            if scale < 1.0:
                frame_small = cv2.resize(frame_rgb, (new_w, new_h), cv2.INTER_LINEAR)
            else:
                frame_small = frame_rgb

            results = yolo_model(frame_small, conf=confidence_threshold, verbose=False)
            detections = []

            if results and results[0].boxes is not None:
                for box in results[0].boxes:
                    cid = int(box.cls.item())
                    conf = float(box.conf.item())
                    xywhn = box.xywhn.cpu().numpy()[0]

                    x1, y1, wn, hn = xywhn
                    if scale < 1.0:
                        x1, y1, wn, hn = x1/scale, y1/scale, wn/scale, hn/scale

                    detections.append({
                        'class': class_map.get(cid, 'unknown'),
                        'class_id': cid,
                        'confidence': conf,
                        'bbox': [x1 - wn/2, y1 - hn/2, x1 + wn/2, y1 + hn/2],
                        'manual': False
                    })
            return detections

        cap = cv2.VideoCapture(video_path)
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        results = {}
        frame_idx = start_frame
        while frame_idx < end_frame:
            ret, frame = cap.read()
            if not ret:
                break
            if frame_idx % frame_interval == 0:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results[frame_idx] = detect(frame_rgb)
            frame_idx += 1

        cap.release()
        return (start_frame, results)

    def _yolo_detect_frame_direct(self, frame_rgb: np.ndarray, detect_size: int = 320) -> List[Dict]:
        """
        对单帧进行YOLO检测 - 直接使用numpy数组，零IO开销
        优化：降低分辨率检测，提升速度
        """
        import cv2
        detections = []

        if self.yolo_model is None:
            print("[AutoLabel] YOLO 模型未加载，无法检测")
            return detections

        try:
            h, w = frame_rgb.shape[:2]

            # 降低分辨率检测以提升速度
            # 保持宽高比
            scale = min(detect_size / h, detect_size / w)
            new_h, new_w = int(h * scale), int(w * scale)

            if scale < 1.0:
                frame_small = cv2.resize(frame_rgb, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
            else:
                frame_small = frame_rgb

            # YOLO检测（使用半精度加速）
            results = self.yolo_model(frame_small, conf=self.confidence_threshold, verbose=False)

            if results and len(results) > 0 and results[0].boxes is not None:
                result = results[0]
                for box in result.boxes:
                    class_id = int(box.cls.item())
                    confidence = float(box.conf.item())

                    # 获取小图上的归一化边界框
                    xywhn = box.xywhn.cpu().numpy()[0]
                    x1n, y1n, wn, hn = xywhn

                    # 转换回原图坐标（像素值）
                    # xywhn 是相对于小图的（范围0-1）
                    x1 = (x1n - wn / 2) * new_w
                    y1 = (y1n - hn / 2) * new_h
                    x2 = (x1n + wn / 2) * new_w
                    y2 = (y1n + hn / 2) * new_h

                    # 如果缩放过，需要再放大到原图尺寸
                    if scale < 1.0:
                        x1 = x1 / scale
                        y1 = y1 / scale
                        x2 = x2 / scale
                        y2 = y2 / scale

                    class_name = self._get_yolo_class_name(class_id)

                    if class_name != 'unknown':
                        detections.append({
                            'class': class_name,
                            'class_id': class_id,
                            'confidence': confidence,
                            'bbox': [x1, y1, x2, y2],
                            'manual': False
                        })

        except Exception as e:
            print(f"[AutoLabel] YOLO帧检测失败: {e}")

        return detections

    def _yolo_detect_frame(self, frame_rgb: np.ndarray) -> List[Dict]:
        """对单帧进行YOLO检测（兼容旧版本，使用临时文件）"""
        import cv2
        import tempfile

        detections = []

        try:
            # 将numpy数组转为临时图片文件
            temp_path = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
            temp_path.close()

            # 保存临时图片
            temp_img_path = temp_path.name
            cv2.imwrite(temp_img_path, cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR))

            # YOLO检测
            results = self.yolo_model(temp_img_path, conf=self.confidence_threshold, verbose=False)

            if results and len(results) > 0 and results[0].boxes is not None:
                result = results[0]
                h, w = frame_rgb.shape[:2]

                for box in result.boxes:
                    class_id = int(box.cls.item())
                    confidence = float(box.conf.item())

                    # 获取归一化边界框
                    xywhn = box.xywhn.cpu().numpy()[0]
                    x1_norm, y1_norm, w_norm, h_norm = xywhn

                    # 转换为 [x1, y1, x2, y2] 归一化格式
                    x1 = x1_norm - w_norm / 2
                    y1 = y1_norm - h_norm / 2
                    x2 = x1_norm + w_norm / 2
                    y2 = y1_norm + h_norm / 2

                    class_name = self._get_yolo_class_name(class_id)

                    if class_name != 'unknown':
                        detections.append({
                            'class': class_name,
                            'class_id': class_id,
                            'confidence': confidence,
                            'bbox': [x1, y1, x2, y2],
                            'manual': False
                        })

            # 清理临时文件
            try:
                os.unlink(temp_img_path)
            except Exception:
                pass

        except Exception as e:
            print(f"[AutoLabel] YOLO帧检测失败: {e}")

        return detections

    def _draw_tracking_result(self, frame, tracks: List[Dict], frame_idx: int):
        """绘制跟踪结果到视频帧"""
        import cv2
        from PIL import Image, ImageDraw, ImageFont

        img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img_pil = Image.fromarray(img_rgb)
        draw_obj = ImageDraw.Draw(img_pil, "RGBA")

        h, w = frame.shape[:2]
        print(f"[Draw] 帧 {frame_idx}: 帧尺寸 {w}x{h}, 跟踪数 {len(tracks)}")

        # 加载字体
        try:
            font = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 16)
        except Exception:
            font = ImageFont.load_default()

        # 帧号
        draw_obj.text((10, 10), f"帧: {frame_idx}", font=font, fill=(255, 255, 255, 255))

        drawn_count = 0
        for trk in tracks:
            if 'bbox' not in trk:
                continue
            if 'track_id' not in trk:
                continue

            x1, y1, x2, y2 = trk['bbox']
            track_id = trk['track_id']
            cls = trk.get('class', 'unknown')
            conf = trk.get('confidence', 0.0)

            # 检查是否为归一化坐标（0-1范围），如果是则转换为像素坐标
            if max(x1, y1, x2, y2) <= 1.0:
                x1, y1, x2, y2 = x1 * w, y1 * h, x2 * w, y2 * h

            # 边界检查
            x1 = max(0, min(w - 1, x1))
            x2 = max(0, min(w - 1, x2))
            y1 = max(0, min(h - 1, y1))
            y2 = max(0, min(h - 1, y2))

            if x2 <= x1 or y2 <= y1:
                continue

            # 颜色
            color = get_track_color(track_id)
            label_color = (*color, 200)

            # 类别中文名
            cls_cn = CLASS_NAMES_CN.get(cls, cls)

            # 标签文本
            label = f"#{track_id} {cls_cn}"
            if conf > 0:
                label += f" {conf:.2f}"

            # 绘制边界框
            draw_obj.rectangle([x1, y1, x2, y2], outline=(*color, 255), width=3)

            # 计算标签尺寸
            try:
                text_bbox = draw_obj.textbbox((0, 0), label, font=font)
                text_w = text_bbox[2] - text_bbox[0]
                text_h = text_bbox[3] - text_bbox[1]
            except Exception:
                text_w, text_h = 100, 20

            pad = 4
            tx1 = x1
            ty1 = max(0, y1 - text_h - pad * 2)
            tx2 = min(w - 1, tx1 + text_w + pad * 2)
            ty2 = min(h - 1, ty1 + text_h + pad * 2)

            # 绘制标签背景
            draw_obj.rectangle([tx1, ty1, tx2, ty2], fill=label_color)

            # 绘制标签文字
            draw_obj.text((tx1 + pad, ty1 + pad), label, font=font, fill=(255, 255, 255, 255))

            # 绘制跟踪轨迹点
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            draw_obj.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=(*color, 255), outline=(255, 255, 255, 255))

            drawn_count += 1

        print(f"[Draw] 帧 {frame_idx}: 绘制了 {drawn_count}/{len(tracks)} 个框")
        return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

    def _save_tracking_results(self, results: Dict, output_path: str):
        """保存跟踪结果到JSON"""
        import json

        output_data = {
            'metadata': {
                'total_frames': len(results),
                'has_tracking': True
            },
            'frames': {}
        }

        for frame_idx, data in results.items():
            output_data['frames'][str(frame_idx)] = {
                'tracks': [
                    {
                        'track_id': trk.get('track_id'),
                        'class': trk.get('class'),
                        'class_id': trk.get('class_id'),
                        'bbox': trk.get('bbox'),
                        'confidence': trk.get('confidence'),
                        'age': trk.get('age'),
                        'hits': trk.get('hits')
                    }
                    for trk in data.get('tracks', [])
                ],
                'total_tracks': data.get('total_tracks', 0)
            }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)

    def _get_max_concurrent_tracks(self, results: Dict) -> int:
        """获取最大同时跟踪的目标数"""
        max_tracks = 0
        for data in results.values():
            max_tracks = max(max_tracks, data.get('total_tracks', 0))
        return max_tracks

    def is_available(self) -> bool:
        """检查模型是否可用（VLLM 或 YOLO 任一可用）"""
        return self.client is not None or self.yolo_model is not None

    def get_engine_info(self) -> Dict:
        """获取引擎信息"""
        return {
            'vllm_available': self.client is not None,
            'yolo_available': self.yolo_model is not None,
            'yolo_model_path': self.yolo_model_path,
            'confidence_threshold': self.confidence_threshold
        }
