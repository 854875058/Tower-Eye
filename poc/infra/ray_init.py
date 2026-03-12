"""
Ray 集群初始化与状态管理
- init_ray(config)  — 初始化 Ray（单机 or 连接已有集群）
- shutdown_ray()    — 关闭 Ray
- get_ray_status()  — 获取集群状态（用于监控页面展示）
- create_actors(config) — 创建 GPU Actor 实例
"""
import importlib.util
import json
import os
import signal
from pathlib import Path
from typing import Optional, Tuple

try:
    import ray
    _RAY_AVAILABLE = True
except ImportError:
    ray = None
    _RAY_AVAILABLE = False


ROOT = Path(__file__).resolve().parents[2]
RAY_BOOTSTRAP_FILE = ROOT / "logs" / "ray_bootstrap.json"
RAY_ADDRESS_ENV = "TOWER_EYE_RAY_ADDRESS"


def _restore_sigterm():
    """Ray 会注册自己的 SIGTERM handler (sys.exit(15))，
    在 Web 进程中需要恢复默认行为，否则 Ray 集群波动会杀掉 NiceGUI。"""
    try:
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
    except (OSError, ValueError):
        pass  # Windows 主线程限制等


def _get_ray_config(config: dict) -> dict:
    """从 poc.yaml 提取 ray 配置段"""
    return config.get("ray", {})


def write_ray_bootstrap_info(address: str, source: str = "manage.py") -> None:
    """记录本地 Ray bootstrap 地址，供 Web 进程 connect-only 使用。"""
    RAY_BOOTSTRAP_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"address": address, "source": source}
    RAY_BOOTSTRAP_FILE.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


def clear_ray_bootstrap_info() -> None:
    """清理本地 Ray bootstrap 地址记录。"""
    try:
        RAY_BOOTSTRAP_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def get_ray_bootstrap_info() -> dict:
    """读取本地 Ray bootstrap 地址记录。"""
    if not RAY_BOOTSTRAP_FILE.exists():
        return {}
    try:
        data = json.loads(RAY_BOOTSTRAP_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def resolve_ray_target(
    config: dict,
    mode: str = "bootstrap",
    env_address: Optional[str] = None,
    bootstrap_address: Optional[str] = None,
) -> Tuple[Optional[str], str]:
    """解析当前进程应该 bootstrap 还是 connect 到哪个 Ray 地址。"""
    ray_cfg = _get_ray_config(config)
    configured_address = str(ray_cfg.get("address", "auto") or "auto").strip()

    if configured_address == "local":
        return "local", "config.local"

    if configured_address != "auto":
        return configured_address, "config.address"

    if env_address is None:
        env_address = os.environ.get(RAY_ADDRESS_ENV)
    if env_address:
        return env_address, "env.bootstrap"

    if bootstrap_address is None:
        bootstrap_address = get_ray_bootstrap_info().get("address")
    if bootstrap_address:
        return bootstrap_address, "bootstrap.file"

    if mode == "bootstrap":
        return "local", "bootstrap.local"

    return None, "connect_only.missing_address"


def _expected_embedding_runtime(config: dict) -> dict:
    from poc.pipeline.utils import resolve_path

    search_cfg = config.get("search", {})
    model_type = search_cfg.get("embedding_model", "clip")
    info = {"model_type": model_type}
    if model_type == "clip":
        info["clip_model"] = search_cfg.get("clip_model", "clip-ViT-L-14")
    elif model_type == "qwen":
        dummy_image = search_cfg.get("qwen_dummy_image") or config.get("paths", {}).get("raw_images_dir", "data/warning_img")
        info["qwen_api_url"] = search_cfg.get("qwen_api_url", "http://10.132.19.82:8010")
        info["dummy_image"] = str(resolve_path(dummy_image))
    return info


def init_ray(config: dict, mode: str = "bootstrap") -> bool:
    """
    初始化 Ray 集群。
    - bootstrap: 允许当前进程自行拉起本地 Ray
    - connect_only: 只连接外部已存在的 Ray，不自行 bootstrap

    Args:
        config: poc.yaml 完整配置字典
        mode: "bootstrap" 或 "connect_only"

    Returns:
        True 表示初始化成功，False 表示跳过或失败
    """
    if not _RAY_AVAILABLE:
        print("[Ray] ray 模块未安装，跳过初始化")
        return False

    ray_cfg = _get_ray_config(config)

    if not ray_cfg.get("enabled", False):
        print("[Ray] ray.enabled=false，跳过 Ray 初始化")
        return False

    if ray.is_initialized():
        print("[Ray] 已连接到 Ray 集群，跳过重复初始化")
        return True

    address, source = resolve_ray_target(config, mode=mode)
    namespace = ray_cfg.get("namespace", "multimodal")
    num_gpus = ray_cfg.get("num_gpus", None)
    dashboard_port = ray_cfg.get("dashboard_port", 8265)

    if address is None:
        print(
            "[Ray] connect_only 模式下未找到可连接地址。"
            "请先执行 `python bin/manage.py start` 或显式配置 ray.address。"
        )
        return False

    # `auto` 在本项目里表示“优先连接外部 bootstrap 地址”。
    # 只有 bootstrap 模式下，才允许退回到本地单机 Ray。
    if address == "auto":
        address = "local"

    if address == "local":
        print(f"[Ray] 启动本地单机 Ray 集群... (source={source})")
        try:
            init_kwargs = {
                "address": "local",
                "namespace": namespace,
                "ignore_reinit_error": True,
            }
            if num_gpus is not None:
                init_kwargs["num_gpus"] = num_gpus

            # dashboard 需要额外依赖，缺失时自动跳过
            try:
                import importlib
                importlib.import_module("ray.dashboard")
                init_kwargs["dashboard_port"] = dashboard_port
                init_kwargs["include_dashboard"] = True
            except (ImportError, ModuleNotFoundError):
                init_kwargs["include_dashboard"] = False

            ray.init(**init_kwargs)
            _restore_sigterm()
            print(
                f"[Ray] 本地集群启动成功 "
                f"(namespace={namespace}, num_gpus={num_gpus}, source={source})"
            )
            return True
        except Exception as e:
            print(f"[Ray] 本地集群启动失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    # 连接远程集群
    try:
        init_kwargs = {
            "address": address,
            "namespace": namespace,
            "ignore_reinit_error": True,
        }

        ray.init(**init_kwargs)
        _restore_sigterm()
        print(
            f"[Ray] 已连接到 Ray 集群 -- "
            f"address={address}, namespace={namespace}, source={source}"
        )
        return True

    except Exception as e:
        print(f"[Ray] 初始化失败: {e}")
        return False


def shutdown_ray():
    """关闭 Ray 集群连接"""
    if not _RAY_AVAILABLE:
        return
    if ray.is_initialized():
        ray.shutdown()
        print("[Ray] 已关闭")


def get_ray_status() -> dict:
    """
    获取 Ray 集群状态信息（用于监控页面展示）。

    Returns:
        dict: 包含 nodes, total_gpus, total_cpus, actors 等信息
    """
    if not _RAY_AVAILABLE:
        return {"initialized": False, "error": "Ray 模块未安装 (pip install ray)"}

    if not ray.is_initialized():
        return {"initialized": False, "error": "Ray 未初始化"}

    try:
        nodes = ray.nodes()
        alive_nodes = [n for n in nodes if n.get("Alive")]

        total_cpus = sum(n.get("Resources", {}).get("CPU", 0) for n in alive_nodes)
        total_gpus = sum(n.get("Resources", {}).get("GPU", 0) for n in alive_nodes)

        # 获取命名 Actor 列表
        named_actors = []
        for name in ["yolo_detector", "embedding", "vl_analyzer"]:
            try:
                ray.get_actor(name)
                named_actors.append(name)
            except ValueError:
                pass

        return {
            "initialized": True,
            "num_nodes": len(alive_nodes),
            "total_cpus": total_cpus,
            "total_gpus": total_gpus,
            "actors": named_actors,
            "nodes": [
                {
                    "node_id": n.get("NodeID", "")[:8],
                    "address": n.get("NodeManagerAddress", ""),
                    "cpu": n.get("Resources", {}).get("CPU", 0),
                    "gpu": n.get("Resources", {}).get("GPU", 0),
                }
                for n in alive_nodes
            ],
        }
    except Exception as e:
        return {"initialized": True, "error": str(e)}


def create_actors(config: dict):
    """
    创建所有 Ray Actor 实例（命名 Actor，全局单例）。

    Args:
        config: poc.yaml 完整配置字典
    """
    if not _RAY_AVAILABLE or not ray.is_initialized():
        print("[Ray] 未初始化，跳过 Actor 创建")
        return

    ray_cfg = _get_ray_config(config)
    num_gpus = ray_cfg.get("num_gpus", 1)

    from poc.infra.ray_actors import YOLODetectorActor, EmbeddingActor, VLAnalyzerActor

    # YOLODetectorActor 依赖 ultralytics。当前环境缺少依赖时直接跳过，
    # 避免 Actor 异步初始化失败后把 Ray/raylet 拖崩，影响主应用启动。
    if importlib.util.find_spec("ultralytics") is None:
        print("[Ray] 跳过 YOLODetectorActor：未安装 ultralytics")
    else:
        try:
            ray.get_actor("yolo_detector")
            print("[Ray] YOLODetectorActor 已存在，跳过创建")
        except ValueError:
            try:
                YOLODetectorActor.options(
                    name="yolo_detector",
                    num_gpus=min(num_gpus, 1),
                    lifetime="detached",
                ).remote(config)
                print("[Ray] YOLODetectorActor 创建成功")
            except Exception as e:
                print(f"[Ray] YOLODetectorActor 创建失败: {e}")

    # EmbeddingActor — CLIP 需要 GPU，Qwen 纯 HTTP 不需要
    embedding_model = config.get("search", {}).get("embedding_model", "clip")
    embed_gpus = min(num_gpus, 1) if embedding_model == "clip" else 0
    actor = None
    try:
        actor = ray.get_actor("embedding")
        expected_info = _expected_embedding_runtime(config)
        recreate_reason = None
        try:
            actual_info = ray.get(actor.get_runtime_info.remote(), timeout=10)
            if actual_info.get("model_type") != expected_info.get("model_type"):
                recreate_reason = f"model_type {actual_info.get('model_type')} -> {expected_info.get('model_type')}"
            elif expected_info.get("model_type") == "clip":
                if actual_info.get("clip_model") != expected_info.get("clip_model"):
                    recreate_reason = f"clip_model {actual_info.get('clip_model')} -> {expected_info.get('clip_model')}"
            elif expected_info.get("model_type") == "qwen":
                if actual_info.get("qwen_api_url") != expected_info.get("qwen_api_url"):
                    recreate_reason = f"qwen_api_url {actual_info.get('qwen_api_url')} -> {expected_info.get('qwen_api_url')}"
                elif actual_info.get("dummy_image") != expected_info.get("dummy_image"):
                    recreate_reason = f"dummy_image {actual_info.get('dummy_image')} -> {expected_info.get('dummy_image')}"
        except Exception as e:
            recreate_reason = f"无法校验现有 Actor 配置: {e}"

        if recreate_reason:
            print(f"[Ray] EmbeddingActor 需要重建: {recreate_reason}")
            try:
                ray.kill(actor, no_restart=True)
            except Exception as e:
                print(f"[Ray] EmbeddingActor 销毁失败: {e}")
            actor = None
        else:
            print("[Ray] EmbeddingActor 已存在且配置一致，跳过创建")
    except ValueError:
        actor = None

    if actor is None:
        try:
            EmbeddingActor.options(
                name="embedding",
                num_gpus=embed_gpus,
                lifetime="detached",
            ).remote(config)
            print("[Ray] EmbeddingActor 创建成功")
        except Exception as e:
            print(f"[Ray] EmbeddingActor 创建失败: {e}")

    # VLAnalyzerActor — 纯 HTTP 调用，不需要 GPU
    try:
        ray.get_actor("vl_analyzer")
        print("[Ray] VLAnalyzerActor 已存在，跳过创建")
    except ValueError:
        try:
            VLAnalyzerActor.options(
                name="vl_analyzer",
                num_gpus=0,
                lifetime="detached",
            ).remote(config)
            print("[Ray] VLAnalyzerActor 创建成功")
        except Exception as e:
            print(f"[Ray] VLAnalyzerActor 创建失败: {e}")
