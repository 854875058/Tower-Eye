"""
多模态检索系统 - FastAPI 后端
提供 RESTful API 接口
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import sqlite3
import json
from datetime import datetime
import numpy as np

from poc.pipeline.utils import load_yaml, resolve_path, connect_db
from poc.search.query import load_model, encode_query

app = FastAPI(
    title="多模态检索系统 API",
    description="支持多模态、空间、时序的统一检索接口",
    version="1.0.0"
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应该限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局配置和模型
config = None
model = None
lancedb_conn = None


# ============================================================================
# 数据模型
# ============================================================================

class SearchRequest(BaseModel):
    """检索请求"""
    text: Optional[str] = None
    event_type: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    radius_km: float = 5.0
    top_k: int = 20
    hybrid: bool = False
    vector_weight: float = 0.7
    keyword_weight: float = 0.3


class StatisticsRequest(BaseModel):
    """统计请求"""
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    group_by: str = "event_type"  # event_type, region, date


# ============================================================================
# 启动和关闭事件
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """启动时加载配置和模型"""
    global config, model, lancedb_conn

    # 加载配置
    config_path = ROOT / "poc" / "config" / "poc.yaml"
    config = load_yaml(str(config_path))

    # 加载 CLIP 模型
    search_cfg = config.get("search", {})
    model_name = search_cfg.get("clip_model", "clip-ViT-B-32")
    cache_dir = search_cfg.get("model_cache_dir")
    hf_mirror = search_cfg.get("hf_mirror")

    print(f"正在加载模型: {model_name}...")
    model = load_model(model_name, cache_dir=cache_dir, hf_mirror=hf_mirror)
    print("模型加载完成！")

    # 连接 LanceDB
    try:
        import lancedb
        paths_cfg = config.get("paths", {})
        lancedb_dir = resolve_path(paths_cfg.get("lancedb_dir", "poc/data/lancedb"))
        lancedb_conn = lancedb.connect(str(lancedb_dir))
        print(f"LanceDB 连接成功: {lancedb_dir}")
    except Exception as e:
        print(f"LanceDB 连接失败: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    """关闭时清理资源"""
    pass


# ============================================================================
# API 路由
# ============================================================================

@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "多模态检索系统 API",
        "version": "1.0.0",
        "docs": "/docs"
    }


@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "model_loaded": model is not None,
        "lancedb_connected": lancedb_conn is not None
    }


@app.post("/api/search")
async def search(request: SearchRequest):
    """
    多维度检索接口
    支持：文本检索 + 事件类型 + 时间范围 + 地理位置
    """
    try:
        if not model or not lancedb_conn:
            raise HTTPException(status_code=500, detail="模型或数据库未初始化")

        # 打开 LanceDB 表
        table = lancedb_conn.open_table("embeddings")

        # 生成查询向量
        if request.text:
            query_vec = model.encode(
                request.text,
                convert_to_numpy=True,
                normalize_embeddings=True
            ).astype("float32")
        else:
            # 如果没有文本，使用随机向量（仅用于过滤）
            sample = table.to_pandas().head(1)
            dims = len(sample['vector'].iloc[0])
            query_vec = np.random.rand(dims).astype("float32")
            query_vec /= max(1e-12, float(np.linalg.norm(query_vec)))

        # 执行向量检索（LanceDB 只返回 asset_id + _distance）
        query_builder = table.search(query_vec).limit(request.top_k)
        results_df = query_builder.to_pandas()

        # 从 SQLite 补全展示字段
        db_path = resolve_path(config.get("paths", {}).get("db_path", "poc/data/metadata.db"))
        asset_ids = results_df["asset_id"].tolist()
        distances = {row["asset_id"]: float(row.get("_distance", 0)) for _, row in results_df.iterrows()}

        events_map = {}
        if asset_ids:
            conn = connect_db(str(db_path))
            placeholders = ", ".join("?" for _ in asset_ids)
            sql = (
                "SELECT e.*, a.file_path, a.file_name "
                "FROM events e LEFT JOIN assets a ON e.asset_id = a.asset_id "
                f"WHERE a.asset_id IN ({placeholders})"
            )
            for row in conn.execute(sql, asset_ids).fetchall():
                rd = dict(row)
                events_map[rd["asset_id"]] = rd
            conn.close()

        # 转换结果为 JSON 格式（保持向量排序）
        results_list = []
        for aid in asset_ids:
            rd = events_map.get(aid, {})
            extra = {}
            if rd.get("extra_json"):
                try:
                    extra = json.loads(rd["extra_json"])
                except Exception:
                    pass
            result = {
                "asset_id": aid,
                "event_type": rd.get("event_type", ""),
                "alarm_time": rd.get("alarm_time", ""),
                "captured_at": rd.get("alarm_time", ""),
                "lat": rd.get("lat") if rd.get("lat") else None,
                "lon": rd.get("lon") if rd.get("lon") else None,
                "summary": rd.get("summary", ""),
                "file_path": rd.get("file_path", ""),
                "distance": distances.get(aid, 0),
                "address": rd.get("address", ""),
                "device_name": rd.get("device_name", ""),
                "city_name": extra.get("city_name", ""),
                "algorithm_name": extra.get("algorithm_name", ""),
            }
            results_list.append(result)

        return {
            "success": True,
            "total": len(results_list),
            "results": results_list,
            "query": {
                "text": request.text,
                "event_type": request.event_type,
                "time_range": [request.start_time, request.end_time],
                "location": [request.lat, request.lon] if request.lat and request.lon else None,
                "radius_km": request.radius_km,
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"检索失败: {str(e)}")


@app.get("/api/statistics/overview")
async def get_statistics_overview(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None
):
    """
    获取数据统计概览
    """
    try:
        db_path = resolve_path(config.get("paths", {}).get("db_path", "poc/data/metadata.db"))
        conn = connect_db(str(db_path))
        cursor = conn.cursor()

        # 构建时间过滤条件
        time_filter = ""
        params = []
        if start_time and end_time:
            time_filter = "WHERE alarm_time BETWEEN ? AND ?"
            params = [start_time, end_time]
        elif start_time:
            time_filter = "WHERE alarm_time >= ?"
            params = [start_time]
        elif end_time:
            time_filter = "WHERE alarm_time <= ?"
            params = [end_time]

        # 总数统计
        cursor.execute(f"SELECT COUNT(*) FROM events {time_filter}", params)
        total_events = cursor.fetchone()[0]

        # 按事件类型统计
        cursor.execute(f"""
            SELECT event_type, COUNT(*) as count
            FROM events {time_filter}
            GROUP BY event_type
            ORDER BY count DESC
        """, params)
        event_type_stats = [{"type": row[0], "count": row[1]} for row in cursor.fetchall()]

        # 按区域统计
        cursor.execute(f"""
            SELECT region, COUNT(*) as count
            FROM events {time_filter}
            GROUP BY region
            ORDER BY count DESC
            LIMIT 10
        """, params)
        region_stats = [{"region": row[0], "count": row[1]} for row in cursor.fetchall()]

        # 按日期统计（最近30天）
        cursor.execute(f"""
            SELECT DATE(alarm_time) as date, COUNT(*) as count
            FROM events {time_filter}
            GROUP BY DATE(alarm_time)
            ORDER BY date DESC
            LIMIT 30
        """, params)
        date_stats = [{"date": row[0], "count": row[1]} for row in cursor.fetchall()]

        conn.close()

        return {
            "success": True,
            "total_events": total_events,
            "event_type_stats": event_type_stats,
            "region_stats": region_stats,
            "date_stats": date_stats,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"统计失败: {str(e)}")


@app.get("/api/statistics/map")
async def get_map_statistics(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    event_type: Optional[str] = None
):
    """
    获取地图统计数据（用于热力图和标记点）
    """
    try:
        db_path = resolve_path(config.get("paths", {}).get("db_path", "poc/data/metadata.db"))
        conn = connect_db(str(db_path))
        cursor = conn.cursor()

        # 构建查询条件
        conditions = []
        params = []

        if start_time and end_time:
            conditions.append("alarm_time BETWEEN ? AND ?")
            params.extend([start_time, end_time])
        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        # 查询所有带坐标的事件
        cursor.execute(f"""
            SELECT lat, lon, event_type, region, COUNT(*) as count
            FROM events
            {where_clause}
            AND lat IS NOT NULL AND lon IS NOT NULL
            GROUP BY lat, lon, event_type, region
        """, params)

        map_data = []
        for row in cursor.fetchall():
            map_data.append({
                "lat": row[0],
                "lon": row[1],
                "event_type": row[2],
                "region": row[3],
                "count": row[4],
            })

        conn.close()

        return {
            "success": True,
            "total": len(map_data),
            "data": map_data,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"地图统计失败: {str(e)}")


@app.get("/api/events/{event_id}")
async def get_event_detail(event_id: str):
    """
    获取单个事件的详细信息
    """
    try:
        db_path = resolve_path(config.get("paths", {}).get("db_path", "poc/data/metadata.db"))
        conn = connect_db(str(db_path))
        cursor = conn.cursor()

        # 查询事件信息
        cursor.execute("""
            SELECT e.*, a.file_path, a.media_type, a.width, a.height, a.duration_sec
            FROM events e
            LEFT JOIN assets a ON e.asset_id = a.asset_id
            WHERE e.event_id = ?
        """, (event_id,))

        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="事件不存在")

        columns = [desc[0] for desc in cursor.description]
        event_detail = dict(zip(columns, row))

        conn.close()

        return {
            "success": True,
            "data": event_detail,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


@app.get("/api/media/{asset_id}")
async def get_media_file(asset_id: str):
    """
    获取媒体文件（图片或视频）
    """
    try:
        db_path = resolve_path(config.get("paths", {}).get("db_path", "poc/data/metadata.db"))
        conn = connect_db(str(db_path))
        cursor = conn.cursor()

        cursor.execute("SELECT file_path, media_type FROM assets WHERE asset_id = ?", (asset_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            raise HTTPException(status_code=404, detail="媒体文件不存在")

        file_path = resolve_path(row[0])
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="文件不存在")

        return FileResponse(str(file_path))

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取媒体文件失败: {str(e)}")


@app.get("/api/config")
async def get_config():
    """
    获取前端配置信息
    """
    return {
        "success": True,
        "config": {
            "event_types": ["车辆闯入监控告警", "烟火告警", "人员闯入告警"],  # 可以从数据库动态获取
            "regions": ["福建省", "河南省", "北京市", "天津市"],  # 可以从数据库动态获取
            "map_center": [39.9, 116.4],  # 默认地图中心（北京）
            "map_zoom": 5,
        }
    }


if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.getenv("PORT", "8001"))  # 默认使用 8001 端口
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)
