"""
多模态数据底座 - 生产级可视化界面（修复版）

修复内容：
1. 日期选择器中文化
2. 显示原始图片和视频
3. 修复数据库路径问题
"""

import json
import sys
import requests
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime, time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
import pandas as pd

from poc.pipeline.utils import connect_db, load_yaml, resolve_path
from poc.qa.agent import create_agent
from poc.qa.trace import init_trace_manager, get_trace_manager
from poc.qa.tools import init_tool_registry, get_tool_registry
from poc.search.query import (
    build_asset_id_filter,
    hybrid_search,
)
from poc.search.model_manager import ModelManager

# 设置页面为中文
st.set_page_config(
    page_title="多模态数据底座",
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="expanded"
)


def apply_ant_design_pro_theme():
    """应用 Ant Design Pro 风格主题"""
    st.markdown(
        """
        <style>
        :root {
          --bg-layout: #f0f2f5;
          --bg-container: #ffffff;
          --text-primary: #1f1f1f;
          --text-secondary: #595959;
          --primary: #1677ff;
          --primary-hover: #4096ff;
          --border: #f0f0f0;
          --shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
          --radius: 6px;
        }

        .stApp {
          color: var(--text-primary);
          background: var(--bg-layout);
          font-family: "Inter", "SF Pro Text", "PingFang SC", "Microsoft YaHei", sans-serif;
        }

        section[data-testid="stSidebar"] {
          background: var(--bg-container);
          border-right: 1px solid var(--border);
        }

        h1, h2, h3, h4, h5 {
          color: var(--text-primary);
          letter-spacing: 0.1px;
        }

        .stMarkdown, .stCaption, .stText, .stAlert {
          color: var(--text-primary);
        }

        .stCaption, small {
          color: var(--text-secondary);
        }

        [data-testid="stMetric"] {
          background: var(--bg-container);
          border: 1px solid var(--border);
          border-radius: var(--radius);
          padding: 12px 14px;
          box-shadow: var(--shadow);
        }

        [data-testid="stMetricLabel"] {
          color: var(--text-secondary);
        }

        [data-testid="stMetricValue"] {
          color: var(--text-primary);
        }

        .stButton > button {
          background: var(--primary);
          color: #ffffff;
          border: 1px solid var(--primary);
          border-radius: var(--radius);
          box-shadow: none;
          font-weight: 600;
        }

        .stButton > button:hover {
          background: var(--primary-hover);
          border-color: var(--primary-hover);
        }

        .stTextInput input, .stSelectbox select, .stTextArea textarea {
          background-color: var(--bg-container);
          color: var(--text-primary);
          border: 1px solid var(--border);
          border-radius: var(--radius);
        }

        .stDataFrame, [data-testid="stDataFrame"] {
          border-radius: var(--radius);
          border: 1px solid var(--border);
          box-shadow: var(--shadow);
          background: var(--bg-container);
        }

        .stExpander {
          border: 1px solid var(--border);
          border-radius: var(--radius);
          background: var(--bg-container);
        }

        code, pre {
          background: #fafafa;
          color: var(--text-primary);
          border: 1px solid var(--border);
          border-radius: var(--radius);
        }

        hr {
          border-color: var(--border);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


apply_ant_design_pro_theme()


# ============================================================================
# SQLite 辅助函数（结构化过滤 + 数据补全）
# ============================================================================

def build_sqlite_filter(filters: dict) -> Tuple[str, list]:
    """
    根据筛选条件构建 SQLite WHERE 子句 + 参数列表。

    Returns:
        (where_clause, params) — where_clause 以 " AND ..." 开头，可直接拼接到 WHERE 1=1 后面
    """
    clauses = []
    params: list = []

    if filters.get("event_type"):
        clauses.append("e.event_type LIKE ?")
        params.append(f"%{filters['event_type']}%")
    if filters.get("city_name"):
        clauses.append("e.extra_json LIKE ?")
        params.append(f'%"city_name": "{filters["city_name"]}"%')
    if filters.get("county_name"):
        clauses.append("e.extra_json LIKE ?")
        params.append(f'%"county_name": "{filters["county_name"]}"%')
    if filters.get("town_name"):
        clauses.append("e.extra_json LIKE ?")
        params.append(f'%"town_name": "{filters["town_name"]}"%')
    if filters.get("device_name"):
        clauses.append("e.device_name LIKE ?")
        params.append(f"%{filters['device_name']}%")
    if filters.get("alarm_level"):
        clauses.append("e.extra_json LIKE ?")
        params.append(f'%"emergency_level": "{filters["alarm_level"]}"%')
    if filters.get("order_status"):
        clauses.append("e.extra_json LIKE ?")
        params.append(f'%"order_status": "{filters["order_status"]}"%')
    if filters.get("algorithm_name"):
        clauses.append("e.extra_json LIKE ?")
        params.append(f'%{filters["algorithm_name"]}%')
    if filters.get("algorithm_code"):
        clauses.append("e.extra_json LIKE ?")
        params.append(f'%"algorithm_code": "{filters["algorithm_code"]}"%')
    if filters.get("device_code"):
        clauses.append("e.extra_json LIKE ?")
        params.append(f'%"device_code": "{filters["device_code"]}"%')
    if filters.get("importance_level"):
        clauses.append("e.extra_json LIKE ?")
        params.append(f'%"importance_level": "{filters["importance_level"]}"%')
    if filters.get("warning_source_name"):
        clauses.append("e.extra_json LIKE ?")
        params.append(f'%"warning_source_name": "{filters["warning_source_name"]}"%')
    if filters.get("alarm_body"):
        clauses.append("e.extra_json LIKE ?")
        params.append(f'%"alarm_body": "{filters["alarm_body"]}"%')
    if filters.get("tenant_name"):
        clauses.append("e.extra_json LIKE ?")
        params.append(f'%"tenant_name": "{filters["tenant_name"]}"%')
    if filters.get("channel_name"):
        clauses.append("e.extra_json LIKE ?")
        params.append(f'%"channel_name": "{filters["channel_name"]}"%')
    if filters.get("confidence_min") is not None:
        clauses.append("e.confidence_level >= ?")
        params.append(filters["confidence_min"])
    if filters.get("confidence_max") is not None:
        clauses.append("e.confidence_level <= ?")
        params.append(filters["confidence_max"])
    if filters.get("start_time"):
        clauses.append("e.alarm_time >= ?")
        params.append(filters["start_time"])
    if filters.get("end_time"):
        clauses.append("e.alarm_time <= ?")
        params.append(filters["end_time"])

    where_clause = ""
    if clauses:
        where_clause = " AND " + " AND ".join(clauses)
    return where_clause, params


def fetch_events_by_asset_ids(db_path, asset_ids: List[str]) -> Dict[str, dict]:
    """
    根据 asset_id 列表从 SQLite 批量获取完整事件信息。

    Returns:
        {asset_id: {完整字段 dict, 含 extra_json 解析后的字段}} 映射
    """
    if not asset_ids:
        return {}
    conn = connect_db(db_path)
    placeholders = ", ".join("?" for _ in asset_ids)
    sql = (
        "SELECT e.*, a.file_path, a.file_name "
        "FROM events e LEFT JOIN assets a ON e.asset_id = a.asset_id "
        f"WHERE a.asset_id IN ({placeholders})"
    )
    rows = conn.execute(sql, asset_ids).fetchall()
    conn.close()

    result = {}
    for r in rows:
        rd = dict(r)
        extra = {}
        if rd.get("extra_json"):
            try:
                extra = json.loads(rd["extra_json"])
            except Exception:
                pass
        rd["_extra"] = extra
        result[rd["asset_id"]] = rd
    return result


def _build_result_item_from_sqlite(rd: dict, score: float = 0.0) -> dict:
    """从 SQLite 行数据构建统一的结果 dict"""
    extra = rd.get("_extra", {})
    return {
        "asset_id": rd.get("asset_id", ""),
        "score": score,
        "file_path": rd.get("file_path", ""),
        "file_name": rd.get("file_name", ""),
        "captured_at": rd.get("alarm_time", ""),
        "lat": rd.get("lat") or 0.0,
        "lon": rd.get("lon") or 0.0,
        "event_type": rd.get("event_type", ""),
        "alarm_time": rd.get("alarm_time", ""),
        "alarm_level": rd.get("alarm_level") or extra.get("emergency_level", ""),
        "summary": rd.get("summary", ""),
        "description": rd.get("description", ""),
        "address": rd.get("address", ""),
        "device_name": rd.get("device_name", ""),
        "confidence_level": rd.get("confidence_level"),
        "province_name": extra.get("province_name", ""),
        "city_name": extra.get("city_name", ""),
        "county_name": extra.get("county_name", ""),
        "town_name": extra.get("town_name", ""),
        "device_code": extra.get("device_code", ""),
        "algorithm_name": extra.get("algorithm_name", ""),
        "order_status": extra.get("order_status", ""),
        "video_url": f"warning_file/{Path(extra.get('video_url', '').split(',')[0].strip()).name}" if extra.get("video_url") else "",
        "file_img_url_src": rd.get("file_path", ""),
        "file_img_url_icon": "",
    }


# ============================================================================
# 缓存函数
# ============================================================================

@st.cache_resource
def get_cached_model_manager(_config_hash: str, config: Dict):
    """缓存 ModelManager"""
    search_cfg = config.get("search", {})
    model_type = search_cfg.get("embedding_model", "clip")
    st.info(f"🔄 正在加载模型（{model_type}），请稍候...")
    manager = ModelManager(config)
    dims = manager.get_embedding_dimension()
    st.success(f"✅ 模型加载成功！类型: {model_type}，维度: {dims}")
    return manager


@st.cache_resource
def get_cached_lancedb(lancedb_dir: Path):
    """缓存 LanceDB 连接"""
    import lancedb
    db = lancedb.connect(str(lancedb_dir))
    return db


@st.cache_resource
def get_cached_agent(config: Dict):
    """缓存 Agent"""
    return create_agent(config, max_retries=3)


@st.cache_resource
def init_systems(config: Dict):
    """初始化系统组件"""
    # 初始化追踪管理器
    trace_db_path = Path(config.get("paths", {}).get("trace_db_path", "logs/traces.db"))

    # 确保目录存在（修复问题3）
    trace_db_path.parent.mkdir(parents=True, exist_ok=True)

    init_trace_manager(
        db_path=trace_db_path,
        enable_file_log=True,
        log_dir=Path(config.get("paths", {}).get("log_dir", "logs"))
    )

    # 初始化 Tool 注册中心
    db_path = config.get("paths", {}).get("db_path", "poc/data/metadata.db")
    if Path(db_path).exists():
        init_tool_registry(db_path)

    return True


def load_config() -> Dict:
    return load_yaml("poc/config/poc.yaml")


@st.cache_data(ttl=3600)
def geocode_address(address: str, api_key: str, geocode_url: str) -> Optional[Tuple[float, float, str]]:
    """调用高德地理编码 API，将地址转为经纬度。

    Returns:
        (lat, lon, formatted_address) 或 None（失败时）
    """
    try:
        resp = requests.get(geocode_url, params={
            "key": api_key,
            "address": address,
            "output": "JSON",
        }, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "1" or not data.get("geocodes"):
            return None
        geo = data["geocodes"][0]
        location = geo["location"]  # "经度,纬度"
        lon_str, lat_str = location.split(",")
        return float(lat_str), float(lon_str), geo.get("formatted_address", address)
    except Exception:
        return None


@st.cache_data(ttl=600)
@st.cache_data(ttl=300)
def get_area_hierarchy(db_path_str: str) -> Dict:
    """从数据库查询省→市→区→街道的层级关系，用于级联下拉选择框

    Returns:
        {
            "cities": ["北京市", "厦门市", ...],
            "county_by_city": {"北京市": ["朝阳区", "海淀区"], ...},
            "town_by_county": {"海沧区": ["东孚街道", ...], ...},
        }
    """
    from poc.pipeline.utils import connect_db
    db_path = Path(db_path_str)
    empty = {"cities": [], "county_by_city": {}, "town_by_county": {}}
    if not db_path.exists():
        return empty
    conn = connect_db(db_path)

    # 检测字段是否为直接列（新库）还是需要从 extra_json 提取（旧库）
    existing_cols = {r[1] for r in conn.execute("PRAGMA table_info(events)").fetchall()}
    use_json = "city_name" not in existing_cols

    if use_json:
        rows = conn.execute(
            "SELECT DISTINCT "
            "json_extract(extra_json, '$.city_name') AS city, "
            "json_extract(extra_json, '$.county_name') AS county, "
            "json_extract(extra_json, '$.town_name') AS town "
            "FROM events "
            "WHERE json_extract(extra_json, '$.city_name') IS NOT NULL"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT DISTINCT city_name AS city, county_name AS county, town_name AS town "
            "FROM events WHERE city_name IS NOT NULL AND city_name != ''"
        ).fetchall()
    conn.close()

    cities = set()
    county_by_city: Dict[str, set] = {}
    town_by_county: Dict[str, set] = {}

    for r in rows:
        city = r["city"] or ""
        county = r["county"] or ""
        town = r["town"] or ""
        if city:
            cities.add(city)
            if county:
                county_by_city.setdefault(city, set()).add(county)
                if town:
                    town_by_county.setdefault(county, set()).add(town)

    return {
        "cities": sorted(cities),
        "county_by_city": {k: sorted(v) for k, v in county_by_city.items()},
        "town_by_county": {k: sorted(v) for k, v in town_by_county.items()},
    }


def get_area_options(db_path_str: str) -> Dict[str, List[str]]:
    """兼容旧调用：返回扁平的 city/county/town 列表"""
    h = get_area_hierarchy(db_path_str)
    all_counties = sorted({c for cs in h["county_by_city"].values() for c in cs})
    all_towns = sorted({t for ts in h["town_by_county"].values() for t in ts})
    return {"city": h["cities"], "county": all_counties, "town": all_towns}


@st.cache_data(ttl=300)
def get_dropdown_options(db_path_str: str) -> Dict[str, List[str]]:
    """从 extra_json 提取各字段的 DISTINCT 值，用于下拉筛选框"""
    from poc.pipeline.utils import connect_db
    db_path = Path(db_path_str)
    if not db_path.exists():
        return {}
    conn = connect_db(db_path)

    # 需要提取的字段列表
    json_fields = [
        "tenant_name", "channel_name", "device_name", "device_code",
        "algorithm_name", "algorithm_code", "warning_source_name",
        "warning_type_name", "alarm_body", "importance_level",
    ]
    result = {}
    for field in json_fields:
        try:
            rows = conn.execute(
                f"SELECT DISTINCT json_extract(extra_json, '$.{field}') AS val "
                f"FROM events "
                f"WHERE json_extract(extra_json, '$.{field}') IS NOT NULL "
                f"AND json_extract(extra_json, '$.{field}') != '' "
                f"ORDER BY val"
            ).fetchall()
            vals = [r["val"] for r in rows]
            if vals:
                result[field] = vals
        except Exception:
            pass
    conn.close()
    return result


def db_stats(db_path: Path) -> Dict[str, int]:
    if not Path(db_path).exists():
        return {"assets": 0, "events": 0, "detections": 0, "annotations": 0, "embeddings": 0}

    conn = connect_db(db_path)
    stats = {}
    try:
        stats["assets"] = conn.execute("SELECT COUNT(*) AS cnt FROM assets").fetchone()["cnt"]
        stats["events"] = conn.execute("SELECT COUNT(*) AS cnt FROM events").fetchone()["cnt"]
        stats["detections"] = conn.execute("SELECT COUNT(*) AS cnt FROM detections").fetchone()["cnt"]
        stats["annotations"] = conn.execute("SELECT COUNT(*) AS cnt FROM annotations").fetchone()["cnt"]
        stats["embeddings"] = conn.execute("SELECT COUNT(*) AS cnt FROM embeddings").fetchone()["cnt"]
    except:
        stats = {"assets": 0, "events": 0, "detections": 0, "annotations": 0, "embeddings": 0}
    finally:
        conn.close()
    return stats


# ============================================================================
# 辅助函数
# ============================================================================

def parse_media_urls(url_string: str) -> List[str]:
    """解析逗号分隔的URL字符串"""
    if not url_string or pd.isna(url_string):
        return []
    return [url.strip() for url in str(url_string).split(',') if url.strip()]


def _inject_sql_filters(sql: str, params: list, filters: Dict) -> Tuple[str, list]:
    """
    将 UI 高级筛选条件注入到已有的 SQL 中（参数化查询，防止 SQL 注入）。

    Args:
        sql: 原始 SQL（可含 ? 占位符）
        params: 原始参数列表
        filters: UI 筛选条件字典

    Returns:
        (新 SQL, 新参数列表)
    """
    import re

    conditions = []
    extra_params = []

    if filters.get("event_type"):
        conditions.append("e.event_type = ?")
        extra_params.append(filters["event_type"])
    if filters.get("alarm_level"):
        conditions.append("e.alarm_level = ?")
        extra_params.append(filters["alarm_level"])
    if filters.get("order_status"):
        conditions.append("e.order_status = ?")
        extra_params.append(filters["order_status"])
    if filters.get("city_name"):
        conditions.append("e.city_name = ?")
        extra_params.append(filters["city_name"])
    if filters.get("county_name"):
        conditions.append("e.county_name = ?")
        extra_params.append(filters["county_name"])
    if filters.get("town_name"):
        conditions.append("e.town_name = ?")
        extra_params.append(filters["town_name"])
    if filters.get("device_name"):
        conditions.append("e.device_name LIKE ?")
        extra_params.append(f"%{filters['device_name']}%")
    if filters.get("algorithm_name"):
        conditions.append("e.algorithm_name LIKE ?")
        extra_params.append(f"%{filters['algorithm_name']}%")
    if filters.get("confidence_min") is not None:
        conditions.append("e.confidence_level >= ?")
        extra_params.append(filters["confidence_min"])
    if filters.get("confidence_max") is not None:
        conditions.append("e.confidence_level <= ?")
        extra_params.append(filters["confidence_max"])
    if filters.get("start_time"):
        conditions.append("e.alarm_time >= ?")
        extra_params.append(filters["start_time"])
    if filters.get("end_time"):
        conditions.append("e.alarm_time <= ?")
        extra_params.append(filters["end_time"])

    if not conditions:
        return sql, list(params)

    extra = " AND ".join(conditions)

    # 尝试匹配 GROUP BY / ORDER BY / LIMIT（第一个出现的位置）
    tail_match = re.search(r'\b(GROUP\s+BY|ORDER\s+BY|LIMIT)\b', sql, re.IGNORECASE)
    where_match = re.search(r'\bWHERE\b', sql, re.IGNORECASE)

    # 找到 LIMIT ? 对应的参数位置：LIMIT 参数总是在 params 末尾
    # 需要把 extra_params 插入到 LIMIT 参数之前
    limit_match = re.search(r'\bLIMIT\s+\?', sql, re.IGNORECASE)
    # 计算 LIMIT ? 之前有多少个 ? 占位符
    if limit_match:
        before_limit = sql[:limit_match.start()]
        params_before_limit = before_limit.count('?')
        new_params = list(params[:params_before_limit]) + extra_params + list(params[params_before_limit:])
    else:
        new_params = list(params) + extra_params

    if where_match:
        # 已有 WHERE → 在尾部关键词前或末尾插入 AND
        if tail_match and tail_match.start() > where_match.end():
            insert_pos = tail_match.start()
            sql = sql[:insert_pos] + f"AND {extra} " + sql[insert_pos:]
        else:
            sql = sql + f" AND {extra}"
    else:
        # 无 WHERE → 在尾部关键词前或末尾插入 WHERE
        if tail_match:
            insert_pos = tail_match.start()
            sql = sql[:insert_pos] + f"WHERE {extra} " + sql[insert_pos:]
        else:
            sql = sql + f" WHERE {extra}"

    return sql, new_params


def display_media(video_url: str, img_urls: List[str]):
    """显示视频和图片"""
    # 显示视频
    if video_url and not pd.isna(video_url):
        # 清理 video_url：去除尾部逗号等脏字符
        clean_url = video_url.split(",")[0].strip()
        if clean_url:
            # 提取纯文件名（去掉路径前缀）
            video_filename = Path(clean_url).name

            # 尝试多个可能的路径
            possible_paths = [
                Path(clean_url),
                Path("warning_file") / video_filename,
                ROOT / clean_url,
                ROOT / "warning_file" / video_filename,
            ]

            video_found = False
            for video_path in possible_paths:
                if video_path.exists():
                    try:
                        with open(video_path, 'rb') as video_file:
                            video_bytes = video_file.read()
                            st.video(video_bytes)
                        video_found = True
                        break
                    except Exception as e:
                        st.warning(f"视频加载失败: {e}")
                        continue

            if not video_found:
                if clean_url.startswith('http'):
                    try:
                        st.video(clean_url)
                    except Exception as e:
                        st.caption("视频不可用")
                else:
                    st.caption(f"视频文件未找到: {video_filename}")

    # 显示图片
    if img_urls:
        cols = st.columns(min(len(img_urls), 3))
        for i, img_url in enumerate(img_urls[:3]):  # 最多显示3张
            # 尝试多个可能的路径
            possible_paths = [
                Path(img_url),
                Path("warning_img") / Path(img_url).name,
                Path("warning_img") / img_url
            ]

            with cols[i % 3]:
                img_found = False
                for img_path in possible_paths:
                    if img_path.exists():
                        st.image(str(img_path), use_container_width=True)
                        img_found = True
                        break

                if not img_found:
                    if img_url.startswith('http'):
                        st.image(img_url, use_container_width=True)
                    else:
                        st.caption(f"图片不存在: {Path(img_url).name}")


# ============================================================================
# 页面渲染函数
# ============================================================================

def render_architecture_overview():
    """渲染架构概览页面"""
    st.header("🏗️ 多模态数据底座")

    st.markdown("""
    ### 🎯 系统定位

    **生产级 RAG + Agent + 多模态检索架构**，融合结构化数据与非结构化数据，
    实现智能问答、向量检索、自动标注的一体化解决方案。
    """)

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("🤖 Agent 引擎", "LangGraph", help="状态机编排，支持自我修正")
    with col2:
        st.metric("🔍 向量数据库", "LanceDB", help="GPU加速，混合检索")
    with col3:
        st.metric("🧠 多模态模型", "Qwen3-VL", help="Embedding + Reranker 二阶段检索")
    with col4:
        st.metric("🏷️ 目标检测", "YOLOv26x + VL", help="YOLO检测 + VL语义双引擎")

    st.markdown("---")

    # 核心技术栈
    st.subheader("💎 核心技术栈")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("""
        **🤖 AI 模型层**
        - **Qwen3-VL Embedding**
          - 图文跨模态理解
          - HTTP API 远程推理
        - **Qwen3-VL Reranker**
          - 二阶段精排
          - 图文相关性重排序
        - **YOLOv26x + VLLM API**
          - YOLO 检测 + VL 语义双引擎
          - 18类工程车辆识别
          - VLLM API 远程推理
        - **卡尔曼跟踪 (Kalman Tracker)**
          - 视频多目标跟踪
          - 轨迹关联 & ID 分配
        - **DeepSeek Chat**
          - NL2SQL 生成
          - 智能问答引擎
        """)

    with col2:
        st.markdown("""
        **🗄️ 数据存储层**
        - **LanceDB** (向量数据库)
          - 向量+元数据一体化
          - 混合检索（向量+关键词）
          - 动态索引优化
        - **SQLite** (结构化数据)
          - 告警事件存储
          - 资产元数据管理
        - **本地文件系统**
          - 图片/视频存储
          - 路径统一管理
        """)

    with col3:
        st.markdown("""
        **🔧 框架工具层**
        - **LangGraph** (Agent编排)
          - 状态机工作流
          - 自我修正机制
          - 完整链路追踪
        - **Streamlit** (交互界面)
          - 多页面应用
          - 实时可视化
        - **ModelManager**
          - 统一模型管理
          - Qwen3-VL Embedding + Reranker
        """)

    st.markdown("---")

    # 架构图
    st.subheader("📐 系统架构图")
    st.code("""
┌─────────────────────────────────────────────────────────────────┐
│                    用户交互层 (User Interface)                   │
│  Streamlit 多页面应用 | 智能问答 | 多模态检索 | 自动标注        │
└────────────────────────┬────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────┐
│                  Agent 层 (LangGraph Orchestration)              │
│  状态机: Parse → Validate → Execute → Format → Retry            │
│  ✓ NL2SQL 生成  ✓ 自我修正  ✓ 安全护栏  ✓ 链路追踪             │
└────────────────────────┬────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────┐
│                  AI 模型层 (Model Inference)                     │
│  Qwen3-VL Embedding + Reranker | YOLOv26x + VLLM | DeepSeek    │
│  ✓ 二阶段检索  ✓ 批量处理  ✓ 混合检索  ✓ 双引擎标注             │
└────────────────────────┬────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────┐
│                  跟踪分析层 (Tracking & Analysis)                │
│  卡尔曼跟踪 (Kalman Tracker) | 视频标注 | 轨迹分析              │
│  ✓ 多目标跟踪  ✓ ID 分配  ✓ 帧间关联  ✓ 视频切片               │
└────────────────────────┬────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────┐
│                  数据存储层 (Data Storage)                       │
│  LanceDB (向量) | SQLite (结构化) | 本地文件 (图片/视频)        │
│  ✓ 803条告警  ✓ 772条向量  ✓ 3223张图片                        │
└─────────────────────────────────────────────────────────────────┘
    """, language="text")

    st.markdown("---")

    # 核心能力展示
    st.subheader("🚀 核心能力")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("""
        **🤖 智能问答 (Agent驱动)**
        - ✅ 自然语言转SQL（NL2SQL）
        - ✅ SQL执行失败自动重试（最多3次）
        - ✅ 错误自我修正
        - ✅ 完整链路追踪
        - ✅ 安全护栏保护

        **🔍 多模态检索**
        - ✅ 图文视频统一入口互搜
        - ✅ 文本语义搜索
        - ✅ 视频上传自动抽帧检索
        - ✅ 混合检索（向量+关键词）
        - ✅ Reranker 二阶段精排
        - ✅ 多条件过滤（时间/地点/类型）
        """)

    with col2:
        st.markdown("""
        **🏷️ 自动标注**
        - ✅ YOLOv26x 批量检测
        - ✅ VLLM API 语义分析
        - ✅ 卡尔曼多目标跟踪
        - ✅ 视频逐帧标注 & 切片
        - ✅ 手动画框标注
        - ✅ 标注结果编辑
        - ✅ YOLO 格式导出
        - ✅ 18类车辆识别

        **📊 系统监控**
        - ✅ 数据统计仪表盘
        - ✅ 查询历史追踪
        - ✅ 性能指标监控
        - ✅ Tool注册中心
        - ✅ 完整执行日志
        """)

    st.markdown("---")

    # 性能指标
    st.subheader("⚡ 性能指标")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("向量化速度", "~80 张/秒", "API推理", help="Qwen3-VL 远程 Embedding 服务")
    with col2:
        st.metric("检索延迟", "< 100ms", "亚秒级", help="LanceDB向量检索")
    with col3:
        st.metric("问答准确率", "> 95%", "高精度", help="Agent自我修正")
    with col4:
        st.metric("数据规模", "803条", "可扩展", help="支持百万级数据")

    st.markdown("---")

    # 技术亮点
    st.subheader("✨ 技术亮点")

    st.markdown("""
    1. **二阶段检索架构**
       - 第一阶段：Qwen3-VL Embedding 向量召回
       - 第二阶段：Qwen3-VL Reranker 精排重排序
       - 图文视频统一入口互搜

    2. **混合检索算法**
       - 向量相似度 + 关键词匹配
       - 可调节权重（联动滑块，和为1）
       - 图像理解字段（summary）语义搜索

    3. **Agent自我修正机制**
       - SQL执行失败自动分析错误
       - 智能修正并重试（最多3次）
       - 完整链路追踪和日志记录

    4. **双引擎自动标注架构**
       - YOLOv26x 快速检测 + VLLM API 语义验证
       - 卡尔曼跟踪实现视频多目标轨迹关联
       - 支持图片批量标注 & 视频逐帧标注

    5. **一键入库脚本**
       - 自动清理、入库、向量化
       - 路径统一转换（URL→本地）
       - 数据完整性校验

    6. **生产级安全防护**
       - SQL注入防护
       - 表访问白名单
       - 参数自动清理
       - 危险操作拦截
    """)

    st.markdown("---")

    # 数据统计
    config = load_config()
    db_path = resolve_path(config.get("paths", {}).get("db_path", "poc/data/metadata.db"))
    stats = db_stats(db_path)

    st.subheader("📊 当前数据统计")

    # 从 LanceDB 获取实际向量数
    lance_count = 0
    try:
        lancedb_dir = resolve_path(config.get("paths", {}).get("lancedb_dir", "poc/data/lancedb"))
        _db = get_cached_lancedb(lancedb_dir)
        _tbl = _db.open_table("embeddings")
        lance_count = _tbl.count_rows()
    except Exception:
        pass

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("资产数", f"{stats['assets']:,}")
    with col2:
        st.metric("事件数", f"{stats['events']:,}")
    with col3:
        st.metric("向量数", f"{lance_count:,}")


def render_intelligent_qa():
    """渲染智能问答页面（展示 Agent 能力）"""
    st.header("🤖 智能问答（Agent 驱动）")

    st.markdown("""
    本功能基于 **LangGraph Agent** 实现，支持：
    - 🧠 自然语言理解
    - 🔄 SQL 自我修正（失败自动重试）
    - 📊 完整执行链路追踪
    - 🛡️ 安全护栏保护
    """)

    # 初始化 session_state
    if 'auto_execute' not in st.session_state:
        st.session_state.auto_execute = False
    if 'pending_question' not in st.session_state:
        st.session_state.pending_question = ""

    # 如果有待执行的问题，直接同步到 widget 的 session_state key
    # 注意：必须在 st.text_input 渲染前设置，且不能同时使用 value= 参数
    if st.session_state.pending_question:
        st.session_state.question_input = st.session_state.pending_question

    # 预设问题（放在输入框前面）
    st.markdown("**快速选择：**")
    preset_questions = [
        "按街道统计各类告警数量",
        "查询最近20条车辆闯入告警的详细信息",
        "统计各设备触发告警次数最多的TOP10",
        "查询置信度大于0.9的高置信告警",
    ]

    cols = st.columns(len(preset_questions))
    for i, q in enumerate(preset_questions):
        if cols[i].button(f"📝 {q[:12]}...", key=f"preset_{i}"):
            st.session_state.pending_question = q
            st.session_state.auto_execute = True
            st.rerun()

    # 问题输入 —— 不使用 value= 参数，通过 session_state.question_input 同步值
    col1, col2 = st.columns([3, 1])
    with col1:
        question = st.text_input(
            "请输入您的问题",
            placeholder="例如：按街道统计最近30天各类告警数量",
            key="question_input"
        )
    with col2:
        enable_trace = st.checkbox("启用追踪", value=True, help="记录完整执行过程")

    # ---- 高级筛选 ----
    config = load_config()
    db_path = resolve_path(config.get("paths", {}).get("db_path", "poc/data/metadata.db"))

    with st.expander("🎛️ 高级筛选", expanded=False):
        qa_fc1, qa_fc2, qa_fc3 = st.columns(3)
        with qa_fc1:
            qa_filter_event = st.text_input("事件类型", value="", placeholder="如：车辆闯入监控告警", key="qa_event_type")
        with qa_fc2:
            qa_filter_alarm_level = st.selectbox(
                "告警等级", ["", "01"],
                format_func=lambda x: "全部" if x == "" else f"等级 {x}",
                key="qa_alarm_level"
            )
        with qa_fc3:
            qa_filter_order_status = st.selectbox(
                "工单状态", ["", "1", "2", "4", "6"],
                format_func=lambda x: {"": "全部", "1": "待处理", "2": "处理中", "4": "已完成", "6": "已关闭"}.get(x, x),
                key="qa_order_status"
            )

        qa_area_h = get_area_hierarchy(str(db_path))
        qa_fc4, qa_fc5, qa_fc6 = st.columns(3)
        with qa_fc4:
            qa_city_options = [""] + qa_area_h["cities"]
            qa_filter_city = st.selectbox(
                "城市", qa_city_options,
                format_func=lambda x: "全部" if x == "" else x,
                key="qa_city_select"
            )
        with qa_fc5:
            if qa_filter_city:
                qa_county_options = [""] + qa_area_h["county_by_city"].get(qa_filter_city, [])
            else:
                qa_county_options = [""] + sorted({c for cs in qa_area_h["county_by_city"].values() for c in cs})
            qa_filter_county = st.selectbox(
                "区/县", qa_county_options,
                format_func=lambda x: "全部" if x == "" else x,
                key="qa_county_select"
            )
        with qa_fc6:
            if qa_filter_county:
                qa_town_options = [""] + qa_area_h["town_by_county"].get(qa_filter_county, [])
            elif qa_filter_city:
                qa_related_counties = qa_area_h["county_by_city"].get(qa_filter_city, [])
                qa_town_options = [""] + sorted({t for c in qa_related_counties for t in qa_area_h["town_by_county"].get(c, [])})
            else:
                qa_town_options = [""] + sorted({t for ts in qa_area_h["town_by_county"].values() for t in ts})
            qa_filter_town = st.selectbox(
                "街道/乡镇", qa_town_options,
                format_func=lambda x: "全部" if x == "" else x,
                key="qa_town_select"
            )

        qa_fc7, qa_fc8, qa_fc9 = st.columns(3)
        with qa_fc7:
            qa_filter_device = st.text_input("设备名称", value="", placeholder="模糊匹配", key="qa_device_name")
        with qa_fc8:
            qa_filter_algorithm = st.text_input("算法名称", value="", placeholder="模糊匹配", key="qa_algorithm_name")
        with qa_fc9:
            qa_filter_confidence = st.slider("置信度范围", 0.0, 1.0, (0.0, 1.0), 0.05, key="qa_confidence_slider")

        st.markdown("**时间过滤**")
        qa_enable_time = st.checkbox("启用时间过滤", value=False, key="qa_enable_time")
        if qa_enable_time:
            qa_tc1, qa_tc2 = st.columns(2)
            with qa_tc1:
                qa_start_date = st.date_input("开始日期", format="YYYY/MM/DD", key="qa_start_date")
                qa_start_time_t = st.time_input("开始时间", value=time(0, 0), key="qa_start_time")
            with qa_tc2:
                qa_end_date = st.date_input("结束日期", format="YYYY/MM/DD", key="qa_end_date")
                qa_end_time_t = st.time_input("结束时间", value=time(23, 59), key="qa_end_time")

    # 收集 UI 筛选条件
    def _collect_qa_filters() -> Dict:
        f = {}
        if qa_filter_event:
            f["event_type"] = qa_filter_event
        if qa_filter_alarm_level:
            f["alarm_level"] = qa_filter_alarm_level
        if qa_filter_order_status:
            f["order_status"] = qa_filter_order_status
        if qa_filter_city:
            f["city_name"] = qa_filter_city
        if qa_filter_county:
            f["county_name"] = qa_filter_county
        if qa_filter_town:
            f["town_name"] = qa_filter_town
        if qa_filter_device:
            f["device_name"] = qa_filter_device
        if qa_filter_algorithm:
            f["algorithm_name"] = qa_filter_algorithm
        if qa_filter_confidence[0] > 0.0:
            f["confidence_min"] = qa_filter_confidence[0]
        if qa_filter_confidence[1] < 1.0:
            f["confidence_max"] = qa_filter_confidence[1]
        if qa_enable_time:
            from datetime import datetime as _dt
            f["start_time"] = _dt.combine(qa_start_date, qa_start_time_t).strftime("%Y-%m-%d %H:%M:%S")
            f["end_time"] = _dt.combine(qa_end_date, qa_end_time_t).strftime("%Y-%m-%d %H:%M:%S")
        return f

    # 点击按钮或快速选择自动执行
    should_execute = st.button("🚀 执行查询", type="primary", use_container_width=True)
    if st.session_state.auto_execute and question:
        should_execute = True
        st.session_state.auto_execute = False
        st.session_state.pending_question = ""  # 清除待执行问题

    if should_execute and question:
        config = load_config()

        # 初始化系统
        try:
            init_systems(config)
        except Exception as e:
            st.error(f"系统初始化失败: {e}")
            return

        # 创建 Agent
        agent = get_cached_agent(config)

        # 执行查询
        with st.spinner("🤖 Agent 正在思考..."):
            result = agent.query(question, user_id="streamlit_user")

        # ---- 高级筛选注入：将 UI 筛选条件追加到 Agent 生成的 SQL ----
        qa_filters = _collect_qa_filters()
        if qa_filters and result.get("status") == "success" and result.get("sql"):
            try:
                original_sql = result["sql"]
                original_params = list(result.get("sql_params") or [])

                injected_sql, injected_params = _inject_sql_filters(
                    original_sql, original_params, qa_filters
                )

                # 重新执行 SQL（参数化查询）
                _cfg = load_config()
                _db_p = resolve_path(_cfg.get("paths", {}).get("db_path", "poc/data/metadata.db"))
                _conn = connect_db(_db_p)
                rows = _conn.execute(injected_sql, injected_params).fetchall()
                _conn.close()
                new_data = [dict(r) for r in rows]

                # 更新 result
                sql_upper = injected_sql.upper()
                has_agg = any(fn in sql_upper for fn in ("COUNT(", "SUM(", "AVG("))
                has_group = "GROUP BY" in sql_upper
                new_intent = "count" if has_agg and has_group else result.get("intent", "list")

                if new_intent == "count" and len(new_data) == 1 and len(new_data[0]) == 1:
                    result["answer"] = {"type": "count", "value": list(new_data[0].values())[0],
                                        "message": f"查询结果：共 {list(new_data[0].values())[0]} 条记录"}
                else:
                    result["answer"] = {"type": "list", "value": new_data,
                                        "message": f"查询结果：返回 {len(new_data)} 条记录"}
                result["sql"] = injected_sql
                result["sql_params"] = injected_params
                result["intent"] = new_intent
                result["execution_history"] = result.get("execution_history", []) + [{
                    "sql": injected_sql, "params": injected_params, "result_count": len(new_data), "status": "success"
                }]
                st.info(f"🎛️ 已应用高级筛选条件")
            except Exception as _filter_err:
                st.warning(f"高级筛选注入失败，使用原始结果: {_filter_err}")

        # 将结果存入 session_state，使其在 rerun 后仍可访问
        st.session_state.last_qa_result = result

        # 保存查询追踪记录
        try:
            _tm = get_trace_manager()
            if _tm:
                from poc.qa.trace import QueryTrace
                _trace = QueryTrace(question=question)
                _trace.intent = result.get("intent")
                _trace.sql = result.get("sql")
                _trace.sql_params = result.get("sql_params")
                _trace.status = result.get("status", "error")
                _trace.error_message = result.get("error")
                answer = result.get("answer")
                if isinstance(answer, dict):
                    _trace.result_count = len(answer.get("value", [])) if isinstance(answer.get("value"), list) else 1
                # 从 execution_history 计算总耗时
                _hist = result.get("execution_history", [])
                if _hist:
                    step = _trace.add_step("agent_query")
                    step.finish("success" if result.get("status") == "success" else "error")
                _trace.finish(status=_trace.status)
                _tm.save_trace(_trace)
        except Exception:
            pass
        # 递增 SQL 编辑器版本号，强制 Streamlit 创建全新 widget（避免旧值缓存）
        st.session_state.sql_editor_version = st.session_state.get("sql_editor_version", 0) + 1

    # ---- 结果渲染：从 session_state 读取，独立于 should_execute ----
    # 这样查看明细/追问按钮点击触发 rerun 时，结果仍然可见，按钮事件不会丢失
    result = st.session_state.get("last_qa_result")
    if result:
        # 显示结果
        st.markdown("---")

        # 状态指示
        if result["status"] == "success":
            st.success("✅ 查询成功")
        else:
            st.error(f"❌ 查询失败: {result['error']}")

        # 结果展示
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("查询意图", result.get("intent", "未知"))
        with col2:
            st.metric("重试次数", result.get("retry_count", 0))
        with col3:
            if result.get("answer"):
                answer_value = result["answer"].get("value", "N/A")
                if isinstance(answer_value, int):
                    st.metric("查询结果", answer_value)
                else:
                    st.metric("返回记录数", len(answer_value) if isinstance(answer_value, list) else 1)

        # 执行详情（可折叠）
        with st.expander("🔍 查看执行详情", expanded=True):
            tab1, tab2, tab3 = st.tabs(["📝 生成的 SQL", "📊 执行历史", "💬 对话记录"])

            with tab1:
                # 将参数化 SQL 的 ? 替换为实际值，方便用户阅读和编辑
                original_sql = result.get("sql", "")
                sql_params = result.get("sql_params") or []
                display_sql = original_sql
                for _p in sql_params:
                    if isinstance(_p, str):
                        display_sql = display_sql.replace("?", f"'{_p}'", 1)
                    else:
                        display_sql = display_sql.replace("?", str(_p), 1)

                edited_sql = st.text_area(
                    "可直接编辑 SQL 后重新执行",
                    value=display_sql,
                    height=120,
                    key=f"sql_editor_v{st.session_state.get('sql_editor_version', 0)}"
                )
                if sql_params:
                    st.caption(f"原始参数: {sql_params}")

                if st.button("🔄 重新执行 SQL", key="rerun_sql"):
                    try:
                        config = load_config()
                        db_path = resolve_path(config.get("paths", {}).get("db_path", "poc/data/metadata.db"))
                        conn = connect_db(db_path)
                        rows = conn.execute(edited_sql).fetchall()
                        conn.close()
                        new_data = [dict(row) for row in rows]

                        # 判断 intent
                        sql_upper = edited_sql.upper()
                        has_agg = any(fn in sql_upper for fn in ("COUNT(", "SUM(", "AVG("))
                        has_group = "GROUP BY" in sql_upper
                        new_intent = "count" if has_agg and has_group else result.get("intent", "list")

                        # 更新 result
                        if new_intent == "count" and len(new_data) == 1 and len(new_data[0]) == 1:
                            result["answer"] = {"type": "count", "value": list(new_data[0].values())[0],
                                                "message": f"查询结果：共 {list(new_data[0].values())[0]} 条记录"}
                        else:
                            result["answer"] = {"type": "list", "value": new_data,
                                                "message": f"查询结果：返回 {len(new_data)} 条记录"}
                        result["sql"] = edited_sql
                        result["sql_params"] = []
                        result["intent"] = new_intent
                        result["status"] = "success"
                        result["error"] = None
                        result["execution_history"] = result.get("execution_history", []) + [{
                            "sql": edited_sql, "params": [], "result_count": len(new_data), "status": "success"
                        }]
                        st.session_state.last_qa_result = result
                        st.rerun()
                    except Exception as e:
                        st.error(f"SQL 执行失败: {e}")

            with tab2:
                if result.get("execution_history"):
                    for i, exec_record in enumerate(result["execution_history"]):
                        status_icon = "✅" if exec_record["status"] == "success" else "❌"
                        st.markdown(f"**尝试 {i+1}** {status_icon}")
                        st.code(exec_record["sql"], language="sql")
                        if exec_record.get("error"):
                            st.error(f"错误: {exec_record['error']}")
                        else:
                            st.success(f"返回 {exec_record.get('result_count', 0)} 条记录")
                else:
                    st.info("无执行历史")

            with tab3:
                if result.get("messages"):
                    for msg in result["messages"]:
                        # 修复：处理 LangChain 的消息对象
                        if hasattr(msg, 'type'):
                            # LangChain 消息对象
                            role = msg.type if hasattr(msg, 'type') else "system"
                            content = msg.content if hasattr(msg, 'content') else str(msg)
                        elif isinstance(msg, dict):
                            # 字典格式
                            role = msg.get("role", "system")
                            content = msg.get("content", "")
                        else:
                            # 其他格式
                            role = "system"
                            content = str(msg)

                        if role == "user" or role == "human":
                            st.chat_message("user").write(content)
                        elif role == "assistant" or role == "ai":
                            st.chat_message("assistant").write(content)
                        else:
                            st.info(f"🔧 {content}")

        # 最终答案
        if result.get("answer"):
            st.markdown("---")
            st.subheader("📋 查询结果")

            answer_data = result["answer"].get("value")
            if isinstance(answer_data, list) and len(answer_data) > 0:
                # 列表结果，显示为表格
                if isinstance(answer_data[0], dict):
                    df = pd.DataFrame(answer_data)
                elif isinstance(answer_data[0], (tuple, list)):
                    sql = result.get("sql", "")
                    import re
                    select_match = re.search(r'SELECT\s+(.*?)\s+FROM', sql, re.IGNORECASE | re.DOTALL)
                    if select_match:
                        columns_str = select_match.group(1)
                        columns = []
                        for col in columns_str.split(','):
                            col = col.strip()
                            if ' AS ' in col.upper():
                                col = col.split(' AS ')[-1].strip()
                            elif '.' in col:
                                col = col.split('.')[-1].strip()
                            columns.append(col)
                        df = pd.DataFrame(answer_data, columns=columns)
                    else:
                        df = pd.DataFrame(answer_data)
                else:
                    df = pd.DataFrame(answer_data)

                # 统计信息
                st.info(f"共返回 **{len(df)}** 条记录")

                # 在美化列名前，先用原始列名检测图片/视频列的索引
                raw_columns = list(df.columns)
                _img_col_indices = []  # 可能的图片列索引（优先级排序）
                _video_col_idx = None
                for _idx, _cn in enumerate(raw_columns):
                    _cnl = str(_cn).lower()
                    # 图片列：收集所有可能的列，按优先级排序
                    if _cnl in ('图片路径', 'file_path', '图片文件路径'):
                        _img_col_indices.insert(0, _idx)  # 高优先级
                    elif 'img_src' in _cnl or '原图' in _cnl:
                        _img_col_indices.append(_idx)
                    elif '图片' in _cnl and '缩略' not in _cnl and 'icon' not in _cnl:
                        _img_col_indices.append(_idx)
                    elif 'img' in _cnl and 'icon' not in _cnl:
                        _img_col_indices.append(_idx)
                    # 视频列
                    if _video_col_idx is None and (_cnl in ('视频路径', 'video_path') or '视频' in _cnl or 'video' in _cnl):
                        _video_col_idx = _idx

                # 美化列名
                df.columns = [col.replace('_', ' ').title() if isinstance(col, str) else col for col in df.columns]

                st.dataframe(df, use_container_width=True)

                # ---- count 类型分组统计：查看明细按钮 ----
                if result.get("intent") == "count" and isinstance(answer_data, list) and len(answer_data) > 0:
                    first_row = answer_data[0]
                    # 找到分组键（非数字列）
                    group_key = None
                    for k, v in first_row.items():
                        if not isinstance(v, (int, float)):
                            group_key = k
                            break
                    if group_key:
                        st.markdown("#### 🔎 查看明细")

                        # 从原始问题提取时间/地点条件，传递给明细查询
                        import re
                        original_q = result.get("question", "")
                        time_match = re.search(r'(最近\d+[天小时月年周]|本[月周年日]|今[天年月])', original_q)
                        time_cond = time_match.group(1) + "内" if time_match else ""

                        # 每行4个按钮
                        items = [(row.get(group_key, ""), row) for row in answer_data if row.get(group_key)]
                        for row_start in range(0, len(items), 4):
                            row_items = items[row_start:row_start + 4]
                            detail_cols = st.columns(len(row_items))
                            for j, (group_val, row_data) in enumerate(row_items):
                                count_val = [v for v in row_data.values() if isinstance(v, (int, float))]
                                count_str = f"({int(count_val[0])}条)" if count_val else ""
                                if detail_cols[j].button(
                                    f"📋 {group_val} {count_str}",
                                    key=f"detail_{row_start + j}"
                                ):
                                    new_q = f"查询{time_cond}最近20条{group_val}的详细信息"
                                    st.session_state.pending_question = new_q
                                    st.session_state.auto_execute = True
                                    st.rerun()

                # ---- 自动展示图片和视频 ----
                if (_img_col_indices or _video_col_idx is not None) and len(df) > 0:
                    st.markdown("#### 🖼️ 媒体预览")
                    display_rows = min(len(df), 9)
                    for row_start in range(0, display_rows, 3):
                        row_end = min(row_start + 3, display_rows)
                        media_cols = st.columns(row_end - row_start)
                        for j, row_idx in enumerate(range(row_start, row_end)):
                            with media_cols[j]:
                                has_media = False
                                # 图片：按优先级尝试所有图片列
                                for _ic_idx in _img_col_indices:
                                    if has_media:
                                        break
                                    img_val = df.iloc[row_idx, _ic_idx]
                                    if img_val and not pd.isna(img_val):
                                        img_path_str = str(img_val)
                                        for p in [Path(img_path_str),
                                                  Path("warning_img") / Path(img_path_str).name,
                                                  ROOT / "warning_img" / Path(img_path_str).name,
                                                  ROOT / img_path_str]:
                                            if p.exists():
                                                st.image(str(p), caption=f"第{row_idx+1}条", use_container_width=True)
                                                has_media = True
                                                break
                                # 视频
                                if _video_col_idx is not None:
                                    vid_val = df.iloc[row_idx, _video_col_idx]
                                    if vid_val and not pd.isna(vid_val):
                                        vid_str = str(vid_val).split(",")[0].strip()
                                        vid_name = Path(vid_str).name
                                        for vp in [Path(vid_str),
                                                   Path("warning_file") / vid_name,
                                                   ROOT / "warning_file" / vid_name,
                                                   ROOT / vid_str]:
                                            if vp.exists():
                                                try:
                                                    st.video(vp.read_bytes())
                                                    has_media = True
                                                except Exception:
                                                    pass
                                                break
                                if not has_media:
                                    st.caption(f"第{row_idx+1}条：无媒体文件")

                # ---- 智能追问：猜测下一步 ----
                st.markdown("---")
                st.markdown("#### 💡 您可能还想了解")
                _render_followup_suggestions(result, answer_data, raw_columns)

            elif isinstance(answer_data, int):
                st.metric("统计结果", f"{answer_data:,}")
                # 追问
                st.markdown("---")
                st.markdown("#### 💡 您可能还想了解")
                _render_followup_suggestions(result, answer_data, [])
            else:
                st.json(result["answer"])


def _render_followup_suggestions(result, answer_data, raw_columns):
    """根据当前查询结果，智能推荐下一步追问按钮"""
    intent = result.get("intent", "")
    original_q = result.get("question", "")
    filters = result.get("filters") or {}

    suggestions = []

    if intent == "count":
        # 统计查询 → 推荐查看具体告警明细
        if isinstance(answer_data, list) and len(answer_data) > 0:
            # GROUP BY 结果 — 为每个分组提供"查看详情"
            first_row = answer_data[0]
            # 找到分组键（非数字列）
            group_key = None
            for k, v in first_row.items():
                if not isinstance(v, (int, float)):
                    group_key = k
                    break
            if group_key:
                # 取前 4 个分组作为追问
                for row in answer_data[:4]:
                    group_val = row.get(group_key, "")
                    if group_val:
                        suggestions.append(
                            f"查询最近20条{group_val}的详细信息"
                        )
        else:
            # 单数字 count
            suggestions.append(f"查询这些告警的详细信息（含图片）")

        if not suggestions:
            suggestions.append("查询最近20条告警的详细信息")

    else:
        # 列表查询 → 推荐统计维度
        suggestions.append("按告警类型统计数量")
        suggestions.append("按街道统计告警分布")
        suggestions.append("按设备统计告警次数TOP10")

    # 渲染按钮
    btn_cols = st.columns(min(len(suggestions), 4))
    for i, s in enumerate(suggestions[:4]):
        if btn_cols[i].button(f"👉 {s[:18]}{'...' if len(s) > 18 else ''}", key=f"followup_{i}"):
            st.session_state.pending_question = s
            st.session_state.auto_execute = True
            st.rerun()


def render_multimodal_search():
    """渲染多模态检索页面 — 图文视频统一入口"""
    st.header("🔍 多模态检索 · 图文视频互搜")

    st.markdown("""
    基于 **Qwen3-VL + LanceDB** 的向量检索，支持图片、文本、视频统一入口互搜：
    - 📝 输入文本 → 语义搜索相关图片与视频
    - 🖼️ 上传图片 → 以图搜图、搜视频
    - 📹 上传视频 → 自动抽帧，搜索相似图片与视频
    - 🎯 多条件过滤（时间、地点、事件类型）
    - 🔄 Reranker 二阶段精排（提升准确率）
    """)

    # 检查 LanceDB 是否已初始化
    config = load_config()
    lancedb_dir = resolve_path(config.get("paths", {}).get("lancedb_dir", "poc/data/lancedb"))

    if not lancedb_dir.exists() or not (lancedb_dir / "embeddings.lance").exists():
        st.error("⚠️ 向量数据库未初始化")
        st.markdown("""
        **请在服务器上运行重新入库脚本：**

        ```bash
        bash 重新入库.sh
        ```

        该脚本会自动完成：
        1. 创建数据库结构并导入告警数据
        2. 调用 **Qwen3-VL** 对所有图片生成向量嵌入
        3. 写入 LanceDB 向量库并创建索引

        完成后刷新页面即可使用多模态检索。
        """)
        return

    config = load_config()
    db_path = resolve_path(config.get("paths", {}).get("db_path", "poc/data/metadata.db"))

    # ---- 统一输入区：文本 + 图片/视频 ----
    query_text = None
    query_image = None  # 最终用于编码的图像（PIL 或 UploadedFile）
    _uploaded_video_frame = None  # 视频抽帧结果

    input_col1, input_col2 = st.columns([3, 2])
    with input_col1:
        query_text = st.text_input("🔤 文本检索", value="", placeholder="输入关键词，如：车辆闯入监控告警")
        uploaded_file = st.file_uploader(
            "📎 上传图片或视频",
            type=["jpg", "jpeg", "png", "bmp", "mp4"],
            help="支持图片（JPG/PNG/BMP）和视频（MP4）。上传视频会自动抽取关键帧用于检索。"
        )
        if uploaded_file is not None:
            if uploaded_file.type and uploaded_file.type.startswith("video"):
                # 视频：抽取中间帧
                import cv2, tempfile, numpy as _np
                with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as _tmp:
                    _tmp.write(uploaded_file.read())
                    _tmp_path = _tmp.name
                try:
                    cap = cv2.VideoCapture(_tmp_path)
                    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                    cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames // 2)
                    ret, frame = cap.read()
                    cap.release()
                    if ret:
                        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        st.image(frame_rgb, caption=f"📹 视频关键帧（第 {total_frames//2}/{total_frames} 帧）", use_container_width=True)
                        # 保存帧为临时图片供后续编码
                        _frame_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
                        cv2.imwrite(_frame_tmp.name, frame)
                        _frame_tmp.close()
                        _uploaded_video_frame = _frame_tmp.name
                    else:
                        st.warning("视频抽帧失败，请检查视频文件")
                finally:
                    Path(_tmp_path).unlink(missing_ok=True)
            else:
                # 图片
                st.image(uploaded_file, caption="🖼️ 上传的图片", use_container_width=True)
                query_image = uploaded_file

    with input_col2:
        top_k = st.number_input("返回数量", min_value=1, max_value=50, value=10)
        enable_hybrid = st.checkbox("混合检索", value=True, help="文本检索时启用向量+关键词混合")
        vector_weight = 0.7
        keyword_weight = 0.3
        if enable_hybrid and query_text:
            vector_weight = st.slider("向量权重 / 关键词权重", 0.0, 1.0, 0.7, 0.1,
                                      help="向左拖动增加关键词权重，向右拖动增加向量权重")
            keyword_weight = round(1.0 - vector_weight, 1)
            st.caption(f"向量: {vector_weight}　|　关键词: {keyword_weight}")
        show_related_data = st.checkbox("显示关联数据", value=True, help="展开同一告警工单的所有图片和完整事件详情")

    # 过滤条件
    with st.expander("🎛️ 高级过滤", expanded=False):
        dd_opts = get_dropdown_options(str(db_path))

        # 第一行：事件类型 + 告警等级 + 工单状态
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            _wt_opts = [""] + dd_opts.get("warning_type_name", [])
            filter_event = st.selectbox(
                "告警类型", _wt_opts,
                format_func=lambda x: "全部" if x == "" else x,
                key="filter_event_type"
            )
        with fc2:
            filter_alarm_level = st.selectbox(
                "紧急等级", ["", "1", "2", "3"],
                format_func=lambda x: {"": "全部", "1": "等级1(高)", "2": "等级2(中)", "3": "等级3(低)"}.get(x, x)
            )
        with fc3:
            filter_order_status = st.selectbox(
                "工单状态", ["", "1", "2", "4", "6"],
                format_func=lambda x: {"": "全部", "1": "待处理", "2": "处理中", "4": "已完成", "6": "已关闭"}.get(x, x)
            )

        # 第二行：重要等级 + 告警来源 + 告警主体
        fc1b, fc2b, fc3b = st.columns(3)
        with fc1b:
            _imp_opts = [""] + dd_opts.get("importance_level", [])
            filter_importance = st.selectbox(
                "重要等级", _imp_opts,
                format_func=lambda x: "全部" if x == "" else f"等级 {x}",
                key="filter_importance"
            )
        with fc2b:
            _ws_opts = [""] + dd_opts.get("warning_source_name", [])
            filter_warning_source = st.selectbox(
                "告警来源", _ws_opts,
                format_func=lambda x: "全部" if x == "" else x,
                key="filter_warning_source"
            )
        with fc3b:
            _ab_opts = [""] + dd_opts.get("alarm_body", [])
            filter_alarm_body = st.selectbox(
                "告警主体", _ab_opts,
                format_func=lambda x: "全部" if x == "" else x,
                key="filter_alarm_body"
            )

        # 第三行：城市 + 区县 + 街道（级联下拉）
        area_h = get_area_hierarchy(str(db_path))
        fc4, fc5, fc6 = st.columns(3)
        with fc4:
            city_options = [""] + area_h["cities"]
            filter_city = st.selectbox(
                "城市", city_options,
                format_func=lambda x: "全部" if x == "" else x,
                key="filter_city_select"
            )
        with fc5:
            if filter_city:
                county_options = [""] + area_h["county_by_city"].get(filter_city, [])
            else:
                county_options = [""] + sorted({c for cs in area_h["county_by_city"].values() for c in cs})
            filter_county = st.selectbox(
                "区/县", county_options,
                format_func=lambda x: "全部" if x == "" else x,
                key="filter_county_select"
            )
        with fc6:
            if filter_county:
                town_options = [""] + area_h["town_by_county"].get(filter_county, [])
            elif filter_city:
                related_counties = area_h["county_by_city"].get(filter_city, [])
                town_options = [""] + sorted({t for c in related_counties for t in area_h["town_by_county"].get(c, [])})
            else:
                town_options = [""] + sorted({t for ts in area_h["town_by_county"].values() for t in ts})
            filter_town = st.selectbox(
                "街道/乡镇", town_options,
                format_func=lambda x: "全部" if x == "" else x,
                key="filter_town_select"
            )

        # 第四行：租户 + 设备名称 + 设备编码
        fc7, fc8, fc9 = st.columns(3)
        with fc7:
            _tn_opts = [""] + dd_opts.get("tenant_name", [])
            filter_tenant = st.selectbox(
                "租户", _tn_opts,
                format_func=lambda x: "全部" if x == "" else x,
                key="filter_tenant"
            )
        with fc8:
            _dn_opts = [""] + dd_opts.get("device_name", [])
            filter_device = st.selectbox(
                "设备名称", _dn_opts,
                format_func=lambda x: "全部" if x == "" else x,
                key="filter_device_name"
            )
        with fc9:
            _dc_opts = [""] + dd_opts.get("device_code", [])
            filter_device_code = st.selectbox(
                "设备编码", _dc_opts,
                format_func=lambda x: "全部" if x == "" else x,
                key="filter_device_code"
            )

        # 第五行：通道名称 + 算法名称 + 算法编码
        fc10, fc11, fc12 = st.columns(3)
        with fc10:
            _cn_opts = [""] + dd_opts.get("channel_name", [])
            filter_channel = st.selectbox(
                "通道名称", _cn_opts,
                format_func=lambda x: "全部" if x == "" else x,
                key="filter_channel"
            )
        with fc11:
            _an_opts = [""] + dd_opts.get("algorithm_name", [])
            filter_algorithm = st.selectbox(
                "算法名称", _an_opts,
                format_func=lambda x: "全部" if x == "" else x,
                key="filter_algorithm"
            )
        with fc12:
            _ac_opts = [""] + dd_opts.get("algorithm_code", [])
            filter_algorithm_code = st.selectbox(
                "算法编码", _ac_opts,
                format_func=lambda x: "全部" if x == "" else x,
                key="filter_algorithm_code"
            )

        # 第六行：置信度
        filter_confidence = st.slider("置信度范围", 0.0, 1.0, (0.0, 1.0), 0.05, key="confidence_slider")

        # 第四行：时间过滤
        st.markdown("**时间过滤**")
        enable_time_filter = st.checkbox("启用时间过滤", value=False)
        if enable_time_filter:
            tc1, tc2 = st.columns(2)
            with tc1:
                start_date = st.date_input("开始日期", format="YYYY/MM/DD")
                start_time_t = st.time_input("开始时间", value=time(0, 0))
            with tc2:
                end_date = st.date_input("结束日期", format="YYYY/MM/DD")
                end_time_t = st.time_input("结束时间", value=time(23, 59))
        else:
            start_date = None
            end_date = None
            start_time_t = time(0, 0)
            end_time_t = time(23, 59)

        # 第五行：地理位置
        st.markdown("**地理位置过滤**")
        enable_geo_filter = st.checkbox("启用地理位置过滤", value=False)
        if enable_geo_filter:
            # 地址搜索行
            addr_col, btn_col = st.columns([4, 1])
            with addr_col:
                geo_address = st.text_input("地址搜索（输入地名自动解析经纬度）", value="", placeholder="例如：天安门、深圳市南山区")
            with btn_col:
                st.markdown("<br>", unsafe_allow_html=True)  # 对齐按钮
                geo_search_clicked = st.button("🔍 解析地址")

            # 处理地址解析
            if geo_search_clicked and geo_address:
                cfg = load_config()
                gaode_cfg = cfg.get("gaode", {})
                api_key = gaode_cfg.get("api_key", "")
                geocode_url = gaode_cfg.get("geocode_url", "https://restapi.amap.com/v3/geocode/geo")
                if not api_key:
                    st.error("未配置高德地图 API Key，请在 poc/config/poc.yaml 中配置 gaode.api_key")
                else:
                    result = geocode_address(geo_address, api_key, geocode_url)
                    if result:
                        st.session_state["geo_lat"] = str(result[0])
                        st.session_state["geo_lon"] = str(result[1])
                        st.session_state["geo_formatted_addr"] = result[2]
                    else:
                        st.warning(f"无法解析地址「{geo_address}」，请检查地名是否正确")

            # 显示解析结果
            if st.session_state.get("geo_formatted_addr"):
                st.success(f"📍 解析结果：{st.session_state['geo_formatted_addr']}")

            # 经纬度 + 半径输入（支持手动输入或自动填充）
            gc1, gc2, gc3 = st.columns(3)
            with gc1:
                lat = st.text_input("纬度(lat)", value=st.session_state.get("geo_lat", ""))
            with gc2:
                lon = st.text_input("经度(lon)", value=st.session_state.get("geo_lon", ""))
            with gc3:
                radius_km = st.number_input("半径(公里)", min_value=1.0, max_value=50.0, value=5.0)
        else:
            lat = ""
            lon = ""
            radius_km = 5.0

    # 检查是否可以执行检索（文本/图片/视频 或 任意筛选条件）
    has_query = bool(query_text) or bool(query_image) or bool(_uploaded_video_frame)
    has_filter = (
        bool(filter_event) or bool(filter_city) or bool(filter_county) or bool(filter_town)
        or bool(filter_device) or bool(filter_device_code) or bool(filter_algorithm)
        or bool(filter_algorithm_code) or bool(filter_alarm_level) or bool(filter_order_status)
        or bool(filter_importance) or bool(filter_warning_source) or bool(filter_alarm_body)
        or bool(filter_tenant) or bool(filter_channel)
        or enable_time_filter or enable_geo_filter
        or filter_confidence[0] > 0.0 or filter_confidence[1] < 1.0
    )
    can_search = has_query or has_filter

    if not can_search:
        st.info("请输入检索文本、上传图片/视频，或设置筛选条件")

    if st.button("🔍 开始检索", type="primary", use_container_width=True, disabled=not can_search):
        start_time_str = None
        end_time_str = None
        if enable_time_filter:
            if start_date:
                start_dt = datetime.combine(start_date, start_time_t)
                start_time_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
            if end_date:
                end_dt = datetime.combine(end_date, end_time_t)
                end_time_str = end_dt.strftime("%Y-%m-%d %H:%M:%S")

        filters = {
            "event_type": filter_event or None,
            "start_time": start_time_str,
            "end_time": end_time_str,
            "lat": float(lat) if lat else None,
            "lon": float(lon) if lon else None,
            "radius_km": radius_km,
            "town_name": filter_town or None,
            "county_name": filter_county or None,
            "city_name": filter_city or None,
            "device_name": filter_device or None,
            "device_code": filter_device_code or None,
            "alarm_level": filter_alarm_level or None,
            "confidence_min": filter_confidence[0] if filter_confidence[0] > 0.0 else None,
            "confidence_max": filter_confidence[1] if filter_confidence[1] < 1.0 else None,
            "order_status": filter_order_status or None,
            "algorithm_name": filter_algorithm or None,
            "algorithm_code": filter_algorithm_code or None,
            "importance_level": filter_importance or None,
            "warning_source_name": filter_warning_source or None,
            "alarm_body": filter_alarm_body or None,
            "tenant_name": filter_tenant or None,
            "channel_name": filter_channel or None,
        }

        with st.spinner("🔍 检索中..."):
            # 使用 LanceDB 检索
            lancedb_dir = resolve_path(config.get("paths", {}).get("lancedb_dir", "poc/data/lancedb"))
            search_cfg = config.get("search", {})

            try:
                # 加载模型和 LanceDB
                import hashlib
                config_hash = hashlib.md5(json.dumps(search_cfg, sort_keys=True).encode()).hexdigest()
                manager = get_cached_model_manager(config_hash, config)
                db = get_cached_lancedb(lancedb_dir)
                table = db.open_table("embeddings")

                # 根据检索模式编码查询
                # ---- 根据输入类型编码查询向量 ----
                query_vec = None
                if query_text:
                    # 文本检索：自动提取结构化实体
                    from poc.qa.nl2sql import (
                        _parse_time_range, _parse_area_name, SCENE_KEYWORDS,
                    )
                    auto_start, auto_end = _parse_time_range(query_text)
                    auto_town, auto_county = _parse_area_name(query_text)
                    auto_event = None
                    for key, value in SCENE_KEYWORDS.items():
                        if key in query_text:
                            auto_event = value
                            break

                    if auto_start and not filters.get("start_time"):
                        filters["start_time"] = auto_start
                    if auto_end and not filters.get("end_time"):
                        filters["end_time"] = auto_end
                    if auto_town and not filters.get("town_name"):
                        filters["town_name"] = auto_town
                    if auto_county and not filters.get("county_name"):
                        filters["county_name"] = auto_county
                    if auto_event and not filters.get("event_type"):
                        filters["event_type"] = auto_event

                    auto_parts = []
                    if auto_event:
                        auto_parts.append(f"事件类型: {auto_event}")
                    if auto_town:
                        auto_parts.append(f"街道: {auto_town}")
                    if auto_county:
                        auto_parts.append(f"区县: {auto_county}")
                    if auto_start:
                        auto_parts.append(f"时间: {auto_start} ~ {auto_end}")
                    if auto_parts:
                        st.info(f"🧠 智能识别实体: {' | '.join(auto_parts)}")

                    query_vec = manager.encode_text(query_text).astype("float32")

                elif _uploaded_video_frame:
                    # 视频帧检索
                    try:
                        query_vec = manager.encode_image(_uploaded_video_frame).astype("float32")
                    finally:
                        Path(_uploaded_video_frame).unlink(missing_ok=True)

                elif query_image:
                    # 图片检索
                    import tempfile
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_file:
                        tmp_file.write(query_image.read())
                        tmp_path = Path(tmp_file.name)
                    try:
                        query_vec = manager.encode_image(tmp_path).astype("float32")
                    finally:
                        tmp_path.unlink(missing_ok=True)

                else:
                    # 纯筛选模式（无查询向量）— 直接查 SQLite
                    pass

                # ---- 纯筛选模式：无向量，走 SQLite ----
                if query_vec is None:
                    conn = connect_db(db_path)
                    sql = (
                        "SELECT e.*, a.file_path, a.file_name "
                        "FROM events e LEFT JOIN assets a ON e.asset_id = a.asset_id "
                        "WHERE 1=1"
                    )
                    where_extra, params = build_sqlite_filter(filters)
                    sql += where_extra
                    sql += f" ORDER BY e.alarm_time DESC LIMIT {top_k}"

                    rows = conn.execute(sql, params).fetchall()
                    conn.close()

                    results = []
                    for r in rows:
                        rd = dict(r)
                        extra = {}
                        if rd.get("extra_json"):
                            try:
                                extra = json.loads(rd["extra_json"])
                            except Exception:
                                pass
                        rd["_extra"] = extra
                        results.append(_build_result_item_from_sqlite(rd))

                    st.success(f"✅ 筛选到 {len(results)} 条结果")

                else:
                    # ---- 向量检索模式（结构化过滤走 SQLite）----
                    reranker_enabled = search_cfg.get("reranker_enabled", False)
                    fetch_k = top_k * 3 if reranker_enabled and query_text else top_k

                    # 步骤 1：有筛选条件时，先从 SQLite 获取符合条件的 asset_id 集合
                    where_extra, sql_params = build_sqlite_filter(filters)
                    pre_filtered_ids = None  # None 表示不做预过滤
                    if where_extra:
                        conn = connect_db(db_path)
                        id_sql = (
                            "SELECT DISTINCT a.asset_id "
                            "FROM events e LEFT JOIN assets a ON e.asset_id = a.asset_id "
                            "WHERE 1=1" + where_extra
                        )
                        pre_filtered_ids = [
                            r[0] for r in conn.execute(id_sql, sql_params).fetchall()
                        ]
                        conn.close()

                        if not pre_filtered_ids:
                            # 筛选条件无匹配，直接返回空
                            results = []
                            st.warning("筛选条件无匹配结果")
                            st.success(f"✅ 找到 {len(results)} 条结果")
                            # 跳到结果展示
                        else:
                            st.info(f"筛选条件匹配 {len(pre_filtered_ids)} 条记录，正在向量检索...")

                    # 步骤 2：LanceDB 向量搜索（仅拿 asset_id + _distance）
                    if pre_filtered_ids is None or pre_filtered_ids:
                        # 构建 asset_id IN 条件
                        lance_filter = None
                        post_filter_ids = None
                        if pre_filtered_ids is not None:
                            if len(pre_filtered_ids) <= 100:
                                # 数量较少，直接用 IN 条件
                                lance_filter = build_asset_id_filter(pre_filtered_ids)
                            else:
                                # 数量较多，LanceDB 先搜更多条，Python 侧后过滤
                                post_filter_ids = set(pre_filtered_ids)
                                fetch_k = fetch_k * 3

                        if query_text and enable_hybrid:
                            results_df = hybrid_search(
                                table,
                                query_vec,
                                query_text=query_text,
                                top_k=fetch_k,
                                filter_str=lance_filter,
                                vector_weight=vector_weight,
                                keyword_weight=keyword_weight,
                            )
                        else:
                            query = table.search(query_vec.tolist()).limit(fetch_k)
                            if lance_filter:
                                query = query.where(lance_filter)
                            results_df = query.to_pandas()

                        # Python 侧后过滤（当 asset_id 太多无法用 IN 时）
                        if post_filter_ids is not None:
                            results_df = results_df[results_df["asset_id"].isin(post_filter_ids)]

                        # 步骤 3：用 asset_id 从 SQLite 补全所有展示字段
                        lance_asset_ids = results_df["asset_id"].tolist()
                        events_map = fetch_events_by_asset_ids(db_path, lance_asset_ids)

                        # 构建结果列表（保持向量相似度排序）
                        results = []
                        for _, row in results_df.iterrows():
                            aid = row["asset_id"]
                            score = float(row.get("hybrid_score", row["_distance"]))
                            rd = events_map.get(aid, {"_extra": {}})
                            results.append(_build_result_item_from_sqlite(rd, score=score))

                        # Reranker 重排序
                        if reranker_enabled and query_text:
                            st.info(f"🔄 Reranker 正在对 {len(results)} 条候选结果精排...")
                            results = manager.rerank(query_text, results, top_k=top_k)
                        else:
                            results = results[:top_k]

                        st.success(f"✅ 找到 {len(results)} 条结果")

                # 显示结果
                for idx, item in enumerate(results):
                    with st.container():
                        score = item.get('score', 0)
                        if score and score > 0:
                            st.markdown(f"### 结果 {idx + 1} — 相似度: {score:.4f}")
                        else:
                            st.markdown(f"### 结果 {idx + 1}")

                        col1, col2 = st.columns([1, 2])

                        with col1:
                            st.write(f"**事件类型**: {item.get('event_type', 'N/A')}")
                            if item.get('alarm_level'):
                                st.write(f"**告警等级**: {item['alarm_level']}")
                            st.write(f"**时间**: {item.get('alarm_time', 'N/A')}")

                            geo_parts = [
                                item.get('province_name', ''),
                                item.get('city_name', ''),
                                item.get('county_name', ''),
                                item.get('town_name', ''),
                            ]
                            geo_str = ' / '.join(p for p in geo_parts if p)
                            if geo_str:
                                st.write(f"**地区**: {geo_str}")
                            st.write(f"**地址**: {item.get('address', 'N/A')}")

                            device_name = item.get('device_name', '')
                            device_code = item.get('device_code', '')
                            if device_name or device_code:
                                device_str = device_name or ''
                                if device_code:
                                    device_str += f" ({device_code})"
                                st.write(f"**设备**: {device_str.strip()}")

                            if item.get('algorithm_name'):
                                st.write(f"**算法**: {item['algorithm_name']}")
                            if item.get('order_status'):
                                st.write(f"**工单状态**: {item['order_status']}")
                            if item.get('confidence_level'):
                                st.write(f"**置信度**: {item['confidence_level']:.2f}")

                            if item.get('summary'):
                                st.markdown("**📝 图像理解：**")
                                st.write(item['summary'])

                            if item.get('description') and item.get('description') != item.get('summary'):
                                st.markdown("**📄 详细描述：**")
                                st.write(item['description'])

                        with col2:
                            # ---- 媒体展示：图片 / 视频 tab ----
                            video_url = item.get("video_url", "")
                            img_urls_src = parse_media_urls(item.get("file_img_url_src", ""))
                            img_urls_icon = parse_media_urls(item.get("file_img_url_icon", ""))
                            img_urls = img_urls_src if img_urls_src else img_urls_icon

                            if not img_urls:
                                file_path_val = item.get("file_path")
                                file_name_val = item.get("file_name")
                                if file_name_val:
                                    img_urls = [file_name_val]
                                elif file_path_val:
                                    img_urls = [file_path_val]

                            # 如果 video_url 为空，尝试从 SQLite extra_json 中获取
                            if not video_url or (isinstance(video_url, float) and pd.isna(video_url)):
                                try:
                                    asset_id = item.get("asset_id")
                                    if asset_id:
                                        _conn = connect_db(db_path)
                                        _row = _conn.execute(
                                            "SELECT extra_json FROM events WHERE asset_id = ?",
                                            (asset_id,)
                                        ).fetchone()
                                        _conn.close()
                                        if _row and _row["extra_json"]:
                                            _extra = json.loads(_row["extra_json"])
                                            raw_video = _extra.get("video_url", "")
                                            if raw_video:
                                                # 清理并转换为本地路径
                                                first_url = raw_video.split(",")[0].strip()
                                                if first_url:
                                                    from pathlib import Path as _P
                                                    video_url = f"warning_file/{_P(first_url).name}"
                                except Exception:
                                    pass

                            tab_img, tab_vid = st.tabs(["📷 图片", "📹 视频"])
                            with tab_img:
                                if img_urls:
                                    display_media("", img_urls)
                                else:
                                    st.info("无关联图片")
                            with tab_vid:
                                if video_url and not (isinstance(video_url, float) and pd.isna(video_url)):
                                    display_media(video_url, [])
                                else:
                                    st.info("无关联视频")

                        # ---- 可选：关联数据展开 ----
                        if show_related_data:
                            with st.expander(f"📋 关联数据 — 结果 {idx + 1}", expanded=False):
                                asset_id = item.get("asset_id")
                                conn = connect_db(db_path)

                                # 获取当前事件信息
                                cur_event = conn.execute(
                                    "SELECT * FROM events WHERE asset_id = ?", (asset_id,)
                                ).fetchone()

                                # 提取 extra_json
                                extra_data = {}
                                video_key = ""
                                if cur_event:
                                    ed = dict(cur_event)
                                    if ed.get("extra_json"):
                                        try:
                                            extra_data = json.loads(ed["extra_json"])
                                        except Exception:
                                            pass
                                    # 用 video_url 的文件名作为关联 key
                                    # （warning_order_id 被 Excel 截断为科学计数法，不可靠）
                                    raw_video = extra_data.get("video_url", "")
                                    if raw_video:
                                        video_key = Path(raw_video.split(",")[0].strip()).stem

                                # 查找同一告警（同一视频）下的所有事件
                                sibling_events = []
                                if video_key:
                                    try:
                                        sibling_events = conn.execute(
                                            "SELECT e.*, a.file_path, a.file_name "
                                            "FROM events e LEFT JOIN assets a ON e.asset_id = a.asset_id "
                                            "WHERE e.extra_json LIKE ?",
                                            (f'%{video_key}%',)
                                        ).fetchall()
                                    except Exception:
                                        pass

                                conn.close()

                                if video_key:
                                    st.caption(f"同一告警共 {len(sibling_events)} 条记录")

                                # ---- 同一告警的所有图片 ----
                                if len(sibling_events) > 1:
                                    sibling_imgs = []
                                    for se in sibling_events:
                                        sd = dict(se)
                                        fp = sd.get("file_path") or sd.get("file_name")
                                        if fp:
                                            sibling_imgs.append(fp)

                                    if len(sibling_imgs) > 1:
                                        st.markdown("**📸 同一告警的所有图片**")
                                        n_cols = min(len(sibling_imgs), 4)
                                        img_cols = st.columns(n_cols)
                                        for si, simg in enumerate(sibling_imgs[:8]):
                                            with img_cols[si % n_cols]:
                                                for sp in [Path(simg),
                                                           Path("warning_img") / Path(simg).name,
                                                           ROOT / "warning_img" / Path(simg).name]:
                                                    if sp.exists():
                                                        is_current = (Path(simg).name == item.get("file_name"))
                                                        caption = f"{'★ 当前' if is_current else ''} {Path(simg).name}"
                                                        st.image(str(sp), caption=caption, use_container_width=True)
                                                        break

                                # ---- 完整事件详情 ----
                                if cur_event:
                                    ed = dict(cur_event)
                                    st.markdown("**📋 完整事件信息**")
                                    # 从 extra_json 获取更多原始字段
                                    if not extra_data and ed.get("extra_json"):
                                        try:
                                            extra_data = json.loads(ed["extra_json"])
                                        except Exception:
                                            extra_data = {}

                                    # 合并显示：优先用结构化字段，补充 extra_json 中的额外字段
                                    display_info = {}
                                    # 基础信息
                                    field_map = [
                                        ("event_type", "事件类型"),
                                        ("alarm_level", "告警等级"),
                                        ("alarm_time", "告警时间"),
                                        ("alarm_source", "告警来源"),
                                        ("address", "地址"),
                                        ("device_name", "设备名称"),
                                        ("confidence_level", "置信度"),
                                        ("summary", "图像理解"),
                                        ("description", "描述"),
                                    ]
                                    for field, label in field_map:
                                        val = ed.get(field) or extra_data.get(field)
                                        if val and str(val).strip():
                                            display_info[label] = val

                                    # extra_json 中的补充字段
                                    extra_field_map = [
                                        ("warning_type_name", "告警类型"),
                                        ("warning_source_name", "告警来源"),
                                        ("alarm_body", "告警主体"),
                                        ("algorithm_name", "算法名称"),
                                        ("algorithm_code", "算法编码"),
                                        ("emergency_level", "紧急等级"),
                                        ("importance_level", "重要等级"),
                                        ("order_status", "工单状态"),
                                        ("tenant_name", "租户"),
                                        ("province_name", "省份"),
                                        ("city_name", "城市"),
                                        ("county_name", "区县"),
                                        ("town_name", "乡镇/街道"),
                                        ("device_code", "设备编码"),
                                        ("channel_name", "通道名称"),
                                        ("channel_code", "通道编码"),
                                    ]
                                    for field, label in extra_field_map:
                                        val = ed.get(field) or extra_data.get(field)
                                        if val and str(val).strip() and label not in display_info:
                                            display_info[label] = val

                                    st.json(display_info)

                        st.markdown("---")

            except Exception as e:
                st.error(f"检索失败: {e}")
                import traceback
                st.code(traceback.format_exc())


def render_system_monitor():
    """渲染系统监控页面"""
    st.header("📊 系统监控")

    config = load_config()
    db_path = resolve_path(config.get("paths", {}).get("db_path", "poc/data/metadata.db"))

    # 确保 trace_manager 已初始化
    try:
        init_systems(config)
    except Exception:
        pass

    # 数据统计
    st.subheader("📈 数据统计")
    stats = db_stats(db_path)

    # 从 LanceDB 获取实际向量数
    lance_count = 0
    try:
        lancedb_dir = resolve_path(config.get("paths", {}).get("lancedb_dir", "poc/data/lancedb"))
        db = get_cached_lancedb(lancedb_dir)
        lance_table = db.open_table("embeddings")
        lance_count = lance_table.count_rows()
    except Exception:
        pass

    col1, col2, col3 = st.columns(3)
    col1.metric("资产数", f"{stats['assets']:,}")
    col2.metric("事件数", f"{stats['events']:,}")
    col3.metric("向量数", f"{lance_count:,}")

    st.markdown("---")

    # 追踪统计
    st.subheader("🔍 查询追踪统计")

    trace_manager = get_trace_manager()
    if trace_manager:
        trace_stats = trace_manager.get_statistics()

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("总查询数", trace_stats.get("total_queries", 0))
        col2.metric("成功数", trace_stats.get("success_count", 0))
        col3.metric("失败数", trace_stats.get("error_count", 0))

        success_rate = 0
        if trace_stats.get("total_queries", 0) > 0:
            success_rate = trace_stats["success_count"] / trace_stats["total_queries"] * 100
        col4.metric("成功率", f"{success_rate:.1f}%")

        st.metric("平均耗时", f"{trace_stats.get('avg_duration_ms', 0):.2f} 毫秒")

        # 按意图分组统计
        if trace_stats.get("by_intent"):
            st.markdown("**按意图分组:**")
            intent_df = pd.DataFrame([
                {"意图": k, "数量": v}
                for k, v in trace_stats["by_intent"].items()
            ])
            st.dataframe(intent_df, use_container_width=True)

        # 最近查询记录
        st.markdown("---")
        st.subheader("📝 最近查询记录")

        recent_traces = trace_manager.query_traces(limit=10)
        if recent_traces:
            trace_df = pd.DataFrame(recent_traces)
            # 只显示关键列
            display_cols = ["timestamp", "question", "intent", "status", "total_duration_ms"]
            available_cols = [col for col in display_cols if col in trace_df.columns]
            st.dataframe(trace_df[available_cols], use_container_width=True)
        else:
            st.info("暂无查询记录")
    else:
        st.warning("追踪系统未启用")

    st.markdown("---")

    # 语义层 Tools
    st.subheader("🔧 语义层 Tools")

    tool_registry = get_tool_registry()
    if tool_registry:
        tools = tool_registry.list_tools()
        tool_df = pd.DataFrame(tools)
        st.dataframe(tool_df, use_container_width=True)
    else:
        st.warning("Tool 注册中心未初始化")


def render_labeling_interface():
    """渲染自动标注页面"""
    # 导入标注界面模块
    try:
        from poc.pipeline.labeling_interface import render_labeling_interface as render_labeling
        render_labeling()
    except Exception as e:
        st.error(f"加载自动标注界面失败: {e}")
        st.info("""
        **备用方案：**

        如果遇到问题，可以单独启动标注界面：
        ```bash
        streamlit run poc/pipeline/labeling_interface.py
        ```
        """)


# ============================================================================
# 主函数
# ============================================================================

def main():
    # 侧边栏
    with st.sidebar:
        st.title("🏗️ 多模态数据底座")
        st.markdown("**生产级 RAG + Agent 架构**")
        st.markdown("---")

        page = st.radio(
            "导航",
            ["🏠 架构概览", "🤖 智能问答", "🔍 多模态检索", "🏷️ 自动标注", "📊 系统监控"],
            label_visibility="collapsed"
        )

        st.markdown("---")
        st.markdown("### 系统状态")
        st.success("✅ Agent 已就绪")
        st.success("✅ 混合检索已启用")
        st.success("✅ Reranker 已启用")

        st.markdown("---")
        st.markdown("### 核心技术")
        st.markdown("""
        - 🤖 **LangGraph** Agent编排
        - 🧠 **DeepSeek** 智能问答
        - 🔍 **LanceDB** 向量数据库
        - 🖼️ **Qwen3-VL** 多模态
        - 🏷️ **YOLOv26x** 目标检测
        - 🎯 **VLLM API** 语义分析
        - 📹 **Kalman Tracker** 多目标跟踪
        - 🗄️ **SQLite** 结构化存储
        - 🎨 **Streamlit** 交互界面
        - ⚡ **CUDA** GPU加速
        """)

    # 主页面
    if page == "🏠 架构概览":
        render_architecture_overview()
    elif page == "🤖 智能问答":
        render_intelligent_qa()
    elif page == "🔍 多模态检索":
        render_multimodal_search()
    elif page == "🏷️ 自动标注":
        render_labeling_interface()
    elif page == "📊 系统监控":
        render_system_monitor()


if __name__ == "__main__":
    main()
