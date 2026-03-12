"""
导入告警明细表数据到数据库（全量字段入库版）

用法：
    python import_warning_data.py
"""

import csv
import json
import sqlite3
import hashlib
import re
from pathlib import Path
from datetime import datetime

from poc.pipeline.utils import load_yaml, resolve_path


DEFAULT_RAW_IMAGES_DIR = "data/warning_img"
DEFAULT_RAW_VIDEOS_DIR = "data/warning_file"
DEFAULT_DB_PATH = "data/metadata.db"


# events 表需要的新增列（用于 ALTER TABLE 兼容旧数据库）
NEW_COLUMNS = [
    ("province_name", "TEXT"),
    ("city_name", "TEXT"),
    ("county_name", "TEXT"),
    ("town_code", "TEXT"),
    ("town_name", "TEXT"),
    ("device_code", "TEXT"),
    ("channel_code", "TEXT"),
    ("channel_name", "TEXT"),
    ("warning_order_id", "TEXT"),
    ("warning_type_id", "TEXT"),
    ("alarm_body", "TEXT"),
    ("algorithm_code", "TEXT"),
    ("algorithm_name", "TEXT"),
    ("emergency_level", "TEXT"),
    ("importance_level", "TEXT"),
    ("order_status", "TEXT"),
    ("confidence_level_max", "REAL"),
    ("tenant_name", "TEXT"),
    ("video_path", "TEXT"),
    ("img_src_path", "TEXT"),
    ("img_icon_path", "TEXT"),
]


def normalize_alarm_time(raw: str) -> str:
    """将 CSV 中各种时间格式统一为 YYYY-MM-DD HH:MM:SS

    支持格式:
      2025/1/10 7:21  -> 2025-01-10 07:21:00
      2026/1/16 14:45 -> 2026-01-16 14:45:00
      2025-07-01 08:00:00 -> 原样返回
    """
    if not raw or not raw.strip():
        return ""
    raw = raw.strip()
    # 已经是标准格式
    if re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", raw):
        return raw
    # 尝试多种格式
    for fmt in ("%Y/%m/%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    # 无法解析，原样返回
    return raw


def create_asset_id(warning_order_id: str, file_name: str) -> str:
    """根据工单ID和文件名生成唯一的 asset_id"""
    unique_key = f"{warning_order_id}_{file_name}"
    return hashlib.sha256(unique_key.encode()).hexdigest()


def ensure_columns(cursor):
    """用 ALTER TABLE 补齐 events 表缺失的列（兼容旧数据库）"""
    existing = {
        row[1] for row in cursor.execute("PRAGMA table_info(events)").fetchall()
    }
    for col_name, col_type in NEW_COLUMNS:
        if col_name not in existing:
            cursor.execute(f"ALTER TABLE events ADD COLUMN {col_name} {col_type}")
            print(f"  ALTER TABLE events ADD COLUMN {col_name} {col_type}")

    # 补建索引
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_town ON events(town_name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_device ON events(device_code)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_address ON events(address)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_county ON events(county_name)")


def normalize_relative_dir(path_str: str) -> str:
    return path_str.replace("\\", "/").rstrip("/")


def url_to_local_path(
    url: str,
    media_type: str = "image",
    image_dir: str = DEFAULT_RAW_IMAGES_DIR,
    video_dir: str = DEFAULT_RAW_VIDEOS_DIR,
) -> str:
    """将 URL 路径转换为本地路径

    图片: /12000000034/ThirdAlarm/pic/xxx.jpg -> data/warning_img/xxx.jpg
          https://slw-base-video.obs...xxx.jpg -> data/warning_img/xxx.jpg
    视频: /12000000034/ThirdAlarm/video/xxx.mp4 -> data/warning_file/xxx.mp4

    注意: CSV 中 video_url 字段可能含尾部逗号（如 xxx.mp4,,,），需先取第一段
    """
    if not url or not url.strip():
        return ""
    # 处理逗号分隔的多值字段：取第一个非空部分
    first_url = url.split(",")[0].strip()
    if not first_url:
        return ""
    filename = Path(first_url).name
    if not filename:
        return ""
    if media_type == "video":
        return f"{normalize_relative_dir(video_dir)}/{filename}"
    return f"{normalize_relative_dir(image_dir)}/{filename}"


def urls_to_local_paths(
    url_string: str,
    media_type: str = "image",
    image_dir: str = DEFAULT_RAW_IMAGES_DIR,
    video_dir: str = DEFAULT_RAW_VIDEOS_DIR,
) -> str:
    """将逗号分隔的多个 URL 转换为逗号分隔的本地路径"""
    if not url_string or not url_string.strip():
        return ""
    parts = [
        url_to_local_path(u, media_type, image_dir=image_dir, video_dir=video_dir)
        for u in url_string.split(",")
    ]
    return ",".join(p for p in parts if p)


def import_warning_csv(
    csv_path: str,
    db_path: str,
    image_dir: str = DEFAULT_RAW_IMAGES_DIR,
    video_dir: str = DEFAULT_RAW_VIDEOS_DIR,
):
    """导入告警明细表CSV到数据库（全量字段入库）"""

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 兼容旧数据库：补齐缺失列
    print("检查并补齐 events 表字段...")
    ensure_columns(cursor)
    conn.commit()

    # 清空现有数据
    print("清空现有数据...")
    cursor.execute("DELETE FROM events")
    cursor.execute("DELETE FROM assets")
    conn.commit()

    # 读取CSV
    print(f"读取CSV文件: {csv_path}")
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)

        assets_inserted = 0
        events_inserted = 0

        for row in reader:
            try:
                # ---- 基础字段 ----
                warning_order_id = row.get('warning_order_id', '')
                alarm_time = normalize_alarm_time(row.get('alarm_time', ''))
                warning_type_name = row.get('warning_type_name', '')
                latitude = row.get('latitude', '')
                longitude = row.get('longitude', '')
                address = row.get('address', '')
                summary = row.get('summary', '')
                description = row.get('description', '')

                # ---- 地理信息 ----
                province_name = row.get('province_name', '')
                city_name = row.get('city_name', '')
                county_name = row.get('county_name', '')
                town_code = row.get('town_code', '')
                town_name = row.get('town_name', '')

                # ---- 设备信息 ----
                device_code = row.get('device_code', '')
                device_name = row.get('device_name', '')
                channel_code = row.get('channel_code', '')
                channel_name = row.get('channel_name', '')

                # ---- 告警详情 ----
                warning_type_id = row.get('warning_type_id', '')
                alarm_body = row.get('alarm_body', '')
                algorithm_code = row.get('algorithm_code', '')
                algorithm_name = row.get('algorithm_name', '')
                emergency_level = row.get('emergency_level', '')
                importance_level = row.get('importance_level', '')
                order_status = row.get('order_status', '')
                tenant_name = row.get('tenant_name', '')
                confidence_level = row.get('confidence_level_max',
                                           row.get('confidence_level', ''))

                # ---- 媒体 URL → 本地路径 ----
                video_url = row.get('video_url', '')
                file_img_url_src = row.get('file_img_url_src', '')
                file_img_url_icon = row.get('file_img_url_icon', '')

                video_path = url_to_local_path(video_url, "video", image_dir=image_dir, video_dir=video_dir)
                img_src_path = urls_to_local_paths(file_img_url_src, "image", image_dir=image_dir, video_dir=video_dir)
                img_icon_path = urls_to_local_paths(file_img_url_icon, "image", image_dir=image_dir, video_dir=video_dir)

                # ---- extra_json 保留完整原始数据 ----
                extra_json = json.dumps(
                    {k: v for k, v in row.items() if v},
                    ensure_ascii=False,
                )

                # ---- 收集所有原图文件名（每张独立入库） ----
                src_names = [Path(u.strip()).name for u in file_img_url_src.split(',') if u.strip() and Path(u.strip()).name]
                icon_names = [Path(u.strip()).name for u in file_img_url_icon.split(',') if u.strip() and Path(u.strip()).name]
                # 如果没有原图，用框图
                all_img_names = src_names if src_names else icon_names
                if not all_img_names:
                    continue

                # 为每张图片创建独立的 asset + event
                for img_name in all_img_names:
                    asset_id = create_asset_id(warning_order_id, img_name)
                    file_path = f"{normalize_relative_dir(image_dir)}/{img_name}"

                    # 找到该图对应的框图（_01_ → _02_）
                    paired_icon = img_name.replace('_01_', '_02_')
                    this_icon_path = (
                        f"{normalize_relative_dir(image_dir)}/{paired_icon}"
                        if paired_icon != img_name and paired_icon in set(icon_names)
                        else img_icon_path
                    )

                    cursor.execute("""
                        INSERT OR REPLACE INTO assets
                        (asset_id, media_type, file_path, file_name,
                         captured_at, lat, lon, source)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        asset_id, 'image', file_path, img_name,
                        alarm_time,
                        float(latitude) if latitude else None,
                        float(longitude) if longitude else None,
                        'warning_csv',
                    ))
                    assets_inserted += 1

                    cursor.execute("""
                        INSERT OR REPLACE INTO events
                        (event_id, asset_id, event_type, alarm_level,
                         alarm_source, alarm_time, lat, lon, region,
                         extra_json, summary, description, address,
                         device_name, confidence_level,
                         province_name, city_name, county_name,
                         town_code, town_name,
                         device_code, channel_code, channel_name,
                         warning_order_id, warning_type_id, alarm_body,
                         algorithm_code, algorithm_name,
                         emergency_level, importance_level, order_status,
                         confidence_level_max, tenant_name,
                         video_path, img_src_path, img_icon_path)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                                ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        asset_id, asset_id,
                        warning_type_name,
                        emergency_level or 'medium',
                        row.get('warning_source_name', 'AI告警'),
                        alarm_time,
                        float(latitude) if latitude else None,
                        float(longitude) if longitude else None,
                        province_name,
                        extra_json,
                        summary, description, address, device_name,
                        float(confidence_level) if confidence_level else None,
                        province_name, city_name, county_name,
                        town_code, town_name,
                        device_code, channel_code, channel_name,
                        warning_order_id, warning_type_id, alarm_body,
                        algorithm_code, algorithm_name,
                        emergency_level, importance_level, order_status,
                        float(confidence_level) if confidence_level else None,
                        tenant_name,
                        video_path, file_path, this_icon_path,
                    ))
                    events_inserted += 1

                if events_inserted % 100 == 0:
                    conn.commit()
                    print(f"已处理 {events_inserted} 条记录...")

            except Exception as e:
                print(f"处理行时出错: {e}")
                print(f"问题行: {row.get('warning_order_id', 'unknown')}")
                continue

        conn.commit()

        # ---- 统计输出 ----
        print(f"\n导入完成！")
        print(f"- Assets 插入: {assets_inserted} 条")
        print(f"- Events 插入: {events_inserted} 条")

        print("\n数据验证:")
        cursor.execute("SELECT COUNT(*) FROM assets")
        print(f"- Assets 总数: {cursor.fetchone()[0]}")
        cursor.execute("SELECT COUNT(*) FROM events")
        print(f"- Events 总数: {cursor.fetchone()[0]}")

        cursor.execute(
            "SELECT event_type, COUNT(*) FROM events GROUP BY event_type"
        )
        print("\n事件类型分布:")
        for r in cursor.fetchall():
            print(f"  - {r[0]}: {r[1]} 条")

        cursor.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE summary IS NOT NULL AND summary != ''"
        )
        print(f"\n包含图像理解的记录: {cursor.fetchone()[0]} 条")

        cursor.execute(
            "SELECT town_name, COUNT(*) FROM events "
            "WHERE town_name IS NOT NULL AND town_name != '' "
            "GROUP BY town_name ORDER BY COUNT(*) DESC LIMIT 10"
        )
        print("\n乡镇/街道分布 (TOP 10):")
        for r in cursor.fetchall():
            print(f"  - {r[0]}: {r[1]} 条")

        cursor.execute(
            "SELECT device_code, device_name, COUNT(*) FROM events "
            "WHERE device_code IS NOT NULL AND device_code != '' "
            "GROUP BY device_code ORDER BY COUNT(*) DESC LIMIT 10"
        )
        print("\n设备分布 (TOP 10):")
        for r in cursor.fetchall():
            print(f"  - {r[0]} ({r[1]}): {r[2]} 条")

    conn.close()


if __name__ == "__main__":
    csv_path = "最终标注入库数据.csv"
    config = load_yaml("poc/config/poc.yaml") if Path("poc/config/poc.yaml").exists() else {}
    paths_cfg = config.get("paths", {})
    image_dir = normalize_relative_dir(paths_cfg.get("raw_images_dir", DEFAULT_RAW_IMAGES_DIR))
    video_dir = normalize_relative_dir(paths_cfg.get("raw_videos_dir", DEFAULT_RAW_VIDEOS_DIR))
    db_path = str(resolve_path(paths_cfg.get("db_path", DEFAULT_DB_PATH)))

    print("=" * 60)
    print("告警明细表数据导入工具（全量字段入库版）")
    print("=" * 60)
    print()

    if not Path(csv_path).exists():
        print(f"错误: CSV文件不存在: {csv_path}")
        exit(1)

    if not Path(db_path).exists():
        print(f"错误: 数据库文件不存在: {db_path}")
        print("请先运行: python -m poc.pipeline.ingest --config poc/config/poc.yaml")
        exit(1)

    import_warning_csv(csv_path, db_path, image_dir=image_dir, video_dir=video_dir)

    print()
    print("=" * 60)
    print("导入完成！现在可以在 Streamlit 中查询了")
    print("=" * 60)
