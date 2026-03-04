"""
Ray 集群初始化与状态管理
- init_ray(config)  — 初始化 Ray（单机 or 连接已有集群）
- shutdown_ray()    — 关闭 Ray
- get_ray_status()  — 获取集群状态（用于监控页面展示）
- create_actors(config) — 创建 GPU Actor 实例
"""
import signal

try:
    import ray
    _RAY_AVAILABLE = True
except ImportError:
    ray = None
    _RAY_AVAILABLE = False


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


def init_ray(config: dict) -> bool:
    """
    初始化 Ray 集群。
    - 如果 Ray 已在运行，连接现有集群
    - 如果 Ray 未运行，启动新的本地集群

    Args:
        config: poc.yaml 完整配置字典

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

    address = ray_cfg.get("address", "auto")
    namespace = ray_cfg.get("namespace", "multimodal")
    num_gpus = ray_cfg.get("num_gpus", None)
    dashboard_port = ray_cfg.get("dashboard_port", 8265)

    # 如果是 auto 模式，需要判断是启动新集群还是连接现有集群
    if address == "auto":
        # 检查是否有现有集群正在运行
        import subprocess
        try:
            result = subprocess.run(
                ["ray", "status"],
                capture_output=True,
                text=True,
                timeout=2
            )
            cluster_exists = result.returncode == 0
        except:
            cluster_exists = False

        if cluster_exists:
            # 连接现有集群（不能传 num_gpus）
            print("[Ray] 检测到现有 Ray 集群，正在连接...")
            try:
                init_kwargs = {
                    "address": "auto",
                    "namespace": namespace,
                    "ignore_reinit_error": True,
                }
                ray.init(**init_kwargs)
                _restore_sigterm()
                print(f"[Ray] 已连接到现有集群 (namespace={namespace})")
                return True
            except Exception as e:
                print(f"[Ray] 连接现有集群失败: {e}")
                return False
        else:
            # 启动新的本地集群
            print("[Ray] 未检测到现有集群，启动新的本地 Ray 集群...")
            try:
                init_kwargs = {
                    "namespace": namespace,
                    "ignore_reinit_error": True,
                    "num_gpus": num_gpus,
                }

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
                print(f"[Ray] 本地集群启动成功 (namespace={namespace}, num_gpus={num_gpus})")
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
        print(f"[Ray] 已连接到远程集群 -- address={address}, namespace={namespace}")
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

    # YOLODetectorActor — 需要 GPU
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
    try:
        ray.get_actor("embedding")
        print("[Ray] EmbeddingActor 已存在，跳过创建")
    except ValueError:
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
