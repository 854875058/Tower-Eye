"""
VL模型视频和图片分析模块
使用视觉语言模型对监控视频和图片进行分析
"""
import base64
import json
import os
import glob
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import yaml


def load_config() -> Dict[str, Any]:
    """加载配置文件"""
    config_path = Path(__file__).parent.parent / "config" / "poc.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# VLLM配置 - 从环境变量读取
VLLM_BASE_URL = os.environ.get("VLLM_BASE_URL")
VLLM_API_KEY = os.environ.get("VLLM_API_KEY")
VLLM_MODEL = os.environ.get("VLLM_MODEL")

# 验证必需的环境变量
if not VLLM_BASE_URL:
    raise ValueError("环境变量 VLLM_BASE_URL 未设置，请在 .env 或系统环境中配置")
if not VLLM_API_KEY:
    raise ValueError("环境变量 VLLM_API_KEY 未设置，请在 .env 或系统环境中配置")
if not VLLM_MODEL:
    raise ValueError("环境变量 VLLM_MODEL 未设置，请在 .env 或系统环境中配置")


def encode_image(image_path: str) -> str:
    """将图片编码为base64格式"""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def vllm_request(messages: List[Dict], max_tokens: int = 4096) -> str:
    """发送请求到VLLM API"""
    # 使用新的 /v1/responses 协议路径，避免触发旧版兼容错误
    url = f"{VLLM_BASE_URL}/v1/responses"
    headers = {
        "Authorization": f"Bearer {VLLM_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": VLLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0
    }

    response = requests.post(url, headers=headers, json=payload, timeout=300)
    response.raise_for_status()

    result = response.json()
    return result["choices"][0]["message"]["content"]


# 图片分析prompt
IMAGE_PROMPT = """# 角色
你是一名专业的监控图像理解分析专家，擅长从监控摄像头截图中识别车辆与工程机械类型，并对场景进行详细、客观的理解分析。

# 任务描述

给定一张监控画面截图，请严格基于图像内容进行理解分析，并以【合法 JSON】格式输出结果。

# 分析任务

## 1. 场景分析（scene）

对截图所呈现的监控场景进行详细描述，必须包含：

- scene_type：场地类型（road / intersection / parking_lot / construction_site / entrance_exit / other / unknown）
- camera_view：摄像头视角（fixed_overview / top_down / angled_view / close_view / unknown）
- environment_objects：画面中可见的固定环境元素（如道路、车道线、建筑、围挡、施工设备、标志牌等）
- weather_lighting：可见的光照或天气情况（daylight / night / rain / fog / indoor_lighting / unknown）
- scene_activity：对当前画面中"正在发生什么"的详细、客观描述

## 2. 车辆与工程机械识别（objects）

识别截图中出现的所有车辆及工程机械目标，每个目标必须包含：

- object_id：目标编号（如 obj_1）
- category：目标类型（从给定枚举中选择，无法确认则为 unknown）
- appearance：
  - color：颜色（unknown 表示不确定）
  - size_shape：体型或结构特征（如大型箱式车、挖掘机长臂等）
  - markings_text：车身或设备文字（可见则原样输出，不可见则 null）
- position：目标在画面中的位置（如 left / center / right + near / far）
- state_action：单张图片中可直接观察到的状态或动作：
  - moving / stopped / parked / operating / turning / waiting / unknown
- interaction：与环境或其他目标的关系（不明显则 null）

## 3. 画面文字信息（text_in_image）

若画面中存在文字、标牌或叠加信息，则逐条输出：

- type：sign / plate / overlay / other
- content：文字内容（高保真复述）
- location：文字在画面中的位置

## 4. 不确定信息（uncertainties）

列出画面中无法确认或不清晰的要点（没有则为空数组）。

## 5. 综合总结（summary）

用一段客观、简洁的文字，对该截图整体内容进行中文总结，概括：

- 这是一个什么场景
- 画面中主要有哪些车辆或工程机械
- 当前画面呈现的主要活动状态

# category 类型枚举（只能从中选择）

- car
- suv
- van
- truck
- cargo_truck
- heavy_truck
- excavator
- loader
- engineering_vehicle
- motorcycle
- bicycle
- unknown

# 约束

- 所有描述必须严格基于截图画面，不进行任何推测或臆断。
- 不清晰的信息必须标注 unknown 或列入 uncertainties。
- 输出必须是【合法 JSON】，不得包含任何多余说明。

# 输入数据

（单张或多张监控截图）

# 输出格式

输出一个 JSON 对象"""


# 视频分析prompt模板
VIDEO_PROMPT_TEMPLATE = """# 角色
你是一名专业的监控视频理解分析专家，擅长从固定摄像头拍摄的视频中分析整体场景，并识别车辆与工程机械的类型及其活动行为。

# 任务描述

给定一个监控视频片段，请严格基于视频画面内容进行理解分析，并以【合法 JSON】格式输出结果。

# 分析任务

## 1. 场景分析（scene）

对整个视频所呈现的监控场景进行详细描述，必须包含：

- scene_type：场地类型（road / intersection / parking_lot / construction_site / entrance_exit / other / unknown）
- camera_view：摄像头视角（fixed_overview / top_down / angled_view / moving_camera / unknown）
- environment_objects：场景中可见的固定环境元素（如道路、围挡、建筑、施工设备、标线等）
- scene_activity：从视频整体角度描述场景"在发生什么"（如车辆通行、施工车辆作业等）
- scene_change：视频过程中场景是否发生变化（如有变化则描述，否则为 null）

## 2. 车辆与工程机械识别（objects）

识别视频中出现的所有车辆及工程机械目标，每个目标必须包含：

- object_id：目标唯一编号（如 vehicle_1）
- category：目标类型（必须从以下枚举中选择，无法确认则为 unknown）
- appearance：
  - color：颜色（unknown 表示不确定）
  - shape_features：明显的结构或外形特征
  - markings_text：车身或设备上的文字/标识（可见则原样输出，不可见则 null）
- initial_position：首次出现时在画面中的位置描述

## 3. 目标活动与行为分析（activities）

按时间顺序总结每个目标在视频中的行为变化：

- object_id：对应 objects 中的目标
- action_sequence：行为序列数组（按发生顺序），可选值包括：
  - enter_scene
  - move_forward
  - turn
  - slow_down
  - stop
  - wait
  - park
  - reverse
  - operate（工程机械作业）
  - exit_scene
- action_notes：对行为的补充说明（没有则为 null）

## 4. 综合概述（summary）

用一段客观、简洁的中文文字总结该监控视频片段中出现了哪些目标，目标做了哪些动作，整体发生了什么。

# category 类型枚举（只能从中选择）

- car
- suv
- van
- truck
- cargo_truck
- heavy_truck
- excavator
- loader
- engineering_vehicle
- motorcycle
- bicycle
- unknown

# 约束

- 所有内容必须严格基于视频画面本身，不得进行任何推测或臆断。
- 在不确定的情况下使用 unknown 或 null。
- 不得猜测驾驶员意图、作业目的或未来行为。
- 行为分析基于时间段总结，不进行逐帧描述。
- 输出必须是【合法 JSON】，不要包含任何解释性文字。

# 输入数据

## 视频片段信息

{video_info}

# 输出格式

仅输出一个 JSON 对象"""


def parse_json_response(content: str) -> Dict[str, Any]:
    """解析JSON响应"""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # 尝试从markdown代码块中提取
        json_match = re.search(r"```json\s*\n(.+?)\n```", content, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # 尝试查找任意JSON对象
        json_match = re.search(r"\{.+\}", content, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

        return {"error": "Failed to parse JSON", "raw_response": content}


def analyze_image(image_path: str) -> Dict[str, Any]:
    """分析单张图片"""
    # 编码图片
    base64_image = encode_image(image_path)

    # 构建消息
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": IMAGE_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
            ]
        }
    ]

    # 调用API
    content = vllm_request(messages)

    # 解析JSON
    result = parse_json_response(content)

    # 添加图片路径信息
    result["source_image"] = image_path
    result["analyzed_at"] = datetime.now().isoformat()

    return result


def analyze_video(video_path: str, asr_info: str = "") -> Dict[str, Any]:
    """分析视频"""
    import cv2

    # 编码视频第一帧作为代表
    cap = cv2.VideoCapture(video_path)
    ret, frame = cap.read()
    cap.release()

    if not ret:
        return {"error": "Failed to read video frame", "source_video": video_path}

    # 保存临时帧图片
    temp_frame_path = "/tmp/vl_temp_frame.jpg"
    cv2.imwrite(temp_frame_path, frame)

    # 编码帧
    base64_frame = encode_image(temp_frame_path)

    # 构建视频信息
    video_info = f"视频文件路径: {video_path}"
    if asr_info:
        video_info += f"\n\nASR字幕信息:\n{asr_info}"

    # 构建完整prompt
    prompt = VIDEO_PROMPT_TEMPLATE.format(video_info=video_info)

    # 构建消息
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_frame}"}}
            ]
        }
    ]

    # 调用API
    content = vllm_request(messages)

    # 解析JSON
    result = parse_json_response(content)

    # 添加视频路径信息
    result["source_video"] = video_path
    result["analyzed_at"] = datetime.now().isoformat()

    # 清理临时文件
    os.remove(temp_frame_path)

    return result


def process_images(image_dir: str, output_dir: str = "./outputdir") -> List[Dict[str, Any]]:
    """处理目录下所有图片"""
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # 获取所有图片
    image_patterns = ["*.jpg", "*.jpeg", "*.png", "*.bmp", "*.webp"]
    image_files = []
    for pattern in image_patterns:
        image_files.extend(glob.glob(os.path.join(image_dir, pattern)))
        image_files.extend(glob.glob(os.path.join(image_dir, "**", pattern), recursive=True))

    image_files = list(set(image_files))  # 去重
    image_files.sort()

    if not image_files:
        print(f"警告: 在 {image_dir} 中未找到图片文件")
        return []

    print(f"找到 {len(image_files)} 个图片文件")

    results = []
    for i, image_path in enumerate(image_files):
        print(f"处理图片 [{i+1}/{len(image_files)}]: {os.path.basename(image_path)}")
        try:
            result = analyze_image(image_path)
            results.append(result)
            time.sleep(0.5)  # 避免请求过快
        except Exception as e:
            print(f"处理图片失败 {image_path}: {e}")
            results.append({
                "source_image": image_path,
                "error": str(e),
                "analyzed_at": datetime.now().isoformat()
            })

    # 保存CSV
    if results:
        save_image_results_to_csv(results, output_dir)

    return results


def process_videos(video_dir: str, warning_dir: str = None, output_dir: str = "./outputdir") -> List[Dict[str, Any]]:
    """处理目录下所有视频"""
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # 获取所有视频
    video_patterns = ["*.mp4", "*.avi", "*.mov", "*.mkv", "*.flv", "*.wmv"]
    video_files = []
    for pattern in video_patterns:
        video_files.extend(glob.glob(os.path.join(video_dir, pattern)))
        video_files.extend(glob.glob(os.path.join(video_dir, "**", pattern), recursive=True))

    video_files = list(set(video_files))
    video_files.sort()

    if not video_files:
        print(f"警告: 在 {video_dir} 中未找到视频文件")
        return []

    print(f"找到 {len(video_files)} 个视频文件")

    # 获取警告文件
    warning_files = {}
    if warning_dir and os.path.exists(warning_dir):
        for pattern in ["*.txt", "*.json", "*.csv"]:
            for wf in glob.glob(os.path.join(warning_dir, pattern)):
                basename = os.path.splitext(os.path.basename(wf))[0]
                warning_files[basename] = wf

    results = []
    for video_path in video_files:
        video_name = os.path.splitext(os.path.basename(video_path))[0]
        print(f"处理视频: {os.path.basename(video_path)}")

        # 获取对应的ASR信息
        asr_info = ""
        if video_name in warning_files:
            try:
                with open(warning_files[video_name], "r", encoding="utf-8") as f:
                    asr_info = f.read()
            except Exception:
                pass

        try:
            result = analyze_video(video_path, asr_info)
            results.append(result)
            time.sleep(0.5)  # 避免请求过快
        except Exception as e:
            print(f"处理视频失败 {video_path}: {e}")
            results.append({
                "source_video": video_path,
                "error": str(e),
                "analyzed_at": datetime.now().isoformat()
            })

    # 保存CSV
    if results:
        save_video_results_to_csv(results, output_dir)

    return results


def flatten_dict(d: Dict[str, Any], parent_key: str = '', sep: str = '_') -> Dict[str, Any]:
    """将嵌套字典展平为单层字典"""
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep).items())
        elif isinstance(v, list):
            items.append((new_key, json.dumps(v, ensure_ascii=True)))
        else:
            items.append((new_key, v))
    return dict(items)


def save_image_results_to_csv(results: List[Dict[str, Any]], output_dir: str):
    """保存图片分析结果到CSV"""
    import csv

    output_path = os.path.join(output_dir, "image_analysis_results.csv")

    # 展平所有结果以获取所有可能的列
    flattened_results = []
    all_columns = set()

    for result in results:
        flattened = flatten_dict(result)
        flattened_results.append(flattened)
        all_columns.update(flattened.keys())

    # 按优先级排序列
    fixed_fields = [
        "source_image", "analyzed_at",
        "scene_scene_type", "scene_camera_view", "scene_environment_objects",
        "scene_weather_lighting", "scene_scene_activity",
        "summary",
    ]

    priority_cols = [f for f in fixed_fields if f in all_columns]
    other_cols = sorted([c for c in all_columns if c not in priority_cols and "objects" not in c and "text_in_image" not in c and "uncertainties" not in c])
    object_cols = sorted([c for c in all_columns if "objects" in c])
    text_cols = sorted([c for c in all_columns if "text_in_image" in c])
    uncertain_cols = sorted([c for c in all_columns if "uncertainties" in c])

    fieldnames = priority_cols + other_cols + object_cols + text_cols + uncertain_cols

    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for result in flattened_results:
            row = {col: result.get(col, "") for col in fieldnames}
            writer.writerow(row)

    print(f"图片分析结果已保存到: {output_path}")


def save_video_results_to_csv(results: List[Dict[str, Any]], output_dir: str):
    """保存视频分析结果到CSV"""
    import csv

    output_path = os.path.join(output_dir, "video_analysis_results.csv")

    # 展平所有结果
    flattened_results = []
    all_columns = set()

    for result in results:
        flattened = flatten_dict(result)
        flattened_results.append(flattened)
        all_columns.update(flattened.keys())

    # 固定字段
    fixed_fields = [
        "source_video", "analyzed_at",
        "scene_scene_type", "scene_camera_view", "scene_environment_objects",
        "scene_scene_activity", "scene_scene_change",
        "summary",
    ]

    # 按优先级排序
    priority_cols = [f for f in fixed_fields if f in all_columns]
    other_cols = sorted([c for c in all_columns if c not in priority_cols and "objects" not in c and "activities" not in c])

    fieldnames = priority_cols + other_cols

    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for result in flattened_results:
            row = {col: result.get(col, "") for col in fieldnames}
            writer.writerow(row)

    print(f"视频分析结果已保存到: {output_path}")


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="VL模型视频和图片分析")
    parser.add_argument("--images", type=str, help="图片目录路径")
    parser.add_argument("--videos", type=str, help="视频目录路径")
    parser.add_argument("--warnings", type=str, help="警告文件目录路径")
    parser.add_argument("--output", type=str, default="./outputdir", help="输出目录")

    args = parser.parse_args()

    if not args.images and not args.videos:
        parser.error("请指定 --images 或 --videos 参数")

    output_dir = args.output
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    if args.images:
        print(f"处理图片目录: {args.images}")
        process_images(args.images, output_dir)

    if args.videos:
        print(f"处理视频目录: {args.videos}")
        process_videos(args.videos, args.warnings, output_dir)


if __name__ == "__main__":
    main()
