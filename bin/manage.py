#!/usr/bin/env python3
"""
多模态检索系统 - 统一跨平台运维脚本

用法:
    python bin/manage.py start          # 启动 NiceGUI Web 应用
    python bin/manage.py stop           # 停止服务
    python bin/manage.py restart        # 重启服务
    python bin/manage.py status         # 查看运行状态
    python bin/manage.py check          # 检查环境/依赖/数据/远程服务
    python bin/manage.py ingest         # 全量入库
    python bin/manage.py ingest --quick # 仅重新生成向量
    python bin/manage.py ingest --incremental  # 增量入库
"""
import argparse
import os
import platform
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from poc.infra.ray_init import (
    clear_ray_bootstrap_info,
    get_ray_bootstrap_info,
    write_ray_bootstrap_info,
)

IS_WIN = platform.system() == "Windows"
APP_PORT = int(os.environ.get("APP_PORT", 8080))
PID_FILE = ROOT / "logs" / "app.pid"
LOG_FILE = ROOT / "logs" / "app.log"
APP_ENTRY = ROOT / "poc" / "app" / "app_ui.py"
CONFIG = ROOT / "poc" / "config" / "poc.yaml"

# ── helpers ──────────────────────────────────────────────

def info(msg):
    print(f"  {msg}")

def ok(msg):
    print(f"  [OK] {msg}")

def warn(msg):
    print(f"  [!] {msg}")

def fail(msg):
    print(f"  [X] {msg}")

def banner(title):
    print("=" * 48)
    print(f"  多模态检索系统 - {title}")
    print("=" * 48)
    print()


def safe_console_text(text: str) -> str:
    """将文本转换为当前终端可安全输出的编码。"""
    encoding = sys.stdout.encoding or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def load_runtime_config():
    """读取运行配置，缺失时返回空字典。"""
    if not CONFIG.exists():
        return {}
    try:
        import yaml
        with open(CONFIG, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def resolve_config_path(config: dict, key: str, default: str) -> Path:
    """按配置解析路径，默认相对仓库根目录。"""
    value = config.get("paths", {}).get(key, default)
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    return path

def get_python():
    """返回当前应该使用的 Python 解释器路径"""
    if IS_WIN:
        venv_py = ROOT / ".venv" / "Scripts" / "python.exe"
        if venv_py.exists():
            return str(venv_py)
    return sys.executable


def get_ray_cli():
    """返回 ray CLI 可执行文件路径（优先 venv 内的 ray）"""
    if IS_WIN:
        venv_ray = ROOT / ".venv" / "Scripts" / "ray.exe"
        if venv_ray.exists():
            return str(venv_ray)
    else:
        venv_ray = ROOT / ".venv" / "bin" / "ray"
        if venv_ray.exists():
            return str(venv_ray)
    # fallback: 依赖 PATH 中的 ray
    return "ray"


def get_local_ray_address(ray_cfg: dict) -> str:
    """返回本地 Ray head 的 connect 地址。"""
    port = int(ray_cfg.get("port", 6379))
    return f"127.0.0.1:{port}"


def stop_ray():
    """停止 Ray 集群（如果正在运行）"""
    clear_ray_bootstrap_info()
    try:
        import ray
        if ray.is_initialized():
            ray.shutdown()
            ok("Ray runtime 已关闭")
    except ImportError:
        pass
    # 同时用 CLI 停止后台 Ray 进程
    try:
        r = subprocess.run(
            [get_ray_cli(), "stop"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0:
            ok("Ray 后台进程已停止")
        else:
            # ray stop 在没有运行时也返回 0，忽略
            pass
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    except Exception as e:
        warn(f"Ray 停止异常: {e}")


def start_ray():
    """启动或解析 Ray 集群连接地址。"""
    clear_ray_bootstrap_info()
    try:
        import yaml
        cfg_path = ROOT / "poc" / "config" / "poc.yaml"
        if cfg_path.exists():
            with open(cfg_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            ray_cfg = cfg.get("ray", {})
            if not ray_cfg.get("enabled", False):
                info("Ray 未启用（poc.yaml ray.enabled=false），跳过")
                return
        else:
            return
    except Exception:
        return None

    ray_address = str(ray_cfg.get("address", "auto") or "auto").strip()
    namespace = ray_cfg.get("namespace", "multimodal")
    num_gpus = ray_cfg.get("num_gpus", 0)
    info(f"启动 Ray (address={ray_address}, namespace={namespace})...")

    if ray_address not in {"auto", "local"}:
        info(f"Ray 使用外部地址: {ray_address}")
        return ray_address

    local_address = get_local_ray_address(ray_cfg)
    cmd = [
        get_ray_cli(), "start", "--head",
        "--port", str(ray_cfg.get("port", 6379)),
        "--num-gpus", str(num_gpus),
    ]
    if ray_cfg.get("dashboard_port") is not None:
        cmd.extend(["--dashboard-port", str(ray_cfg.get("dashboard_port", 8265))])

    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode == 0:
            ok("Ray head node 已启动")
            write_ray_bootstrap_info(local_address)
            ok(f"Ray bootstrap 地址: {local_address}")
            return local_address
        if "already" in r.stderr.lower() or "already" in r.stdout.lower():
            info("Ray head node 已在运行")
            write_ray_bootstrap_info(local_address)
            ok(f"Ray bootstrap 地址: {local_address}")
            return local_address
        warn(f"Ray head node 启动异常: {r.stderr.strip()[:160]}")
    except subprocess.TimeoutExpired:
        warn("Ray head node 启动超时")
    except FileNotFoundError:
        warn("ray CLI 不可用")
    except Exception as e:
        warn(f"Ray 启动失败: {e}")

    return None
# PLACEHOLDER_1

def is_port_in_use(port):
    """检查端口是否被占用"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def pid_alive(pid):
    """检查 PID 对应的进程是否存活"""
    try:
        if IS_WIN:
            r = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True, text=True,
            )
            return str(pid) in r.stdout
        else:
            os.kill(pid, 0)
            return True
    except (OSError, ProcessLookupError):
        return False


def kill_pid(pid, force=False):
    """杀掉指定 PID"""
    try:
        if IS_WIN:
            subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"],
                           capture_output=True)
        else:
            os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
        return True
    except Exception:
        return False


def find_app_pids():
    """查找所有 app_ui.py 相关进程的 PID"""
    pids = []
    try:
        if IS_WIN:
            r = subprocess.run(
                ["wmic", "process", "where",
                 "commandline like '%app_ui.py%'",
                 "get", "processid", "/value"],
                capture_output=True, text=True,
            )
            for line in r.stdout.splitlines():
                if line.startswith("ProcessId="):
                    p = line.split("=")[1].strip()
                    if p and p != str(os.getpid()):
                        pids.append(int(p))
        else:
            r = subprocess.run(
                ["pgrep", "-f", "app_ui.py"],
                capture_output=True, text=True,
            )
            for line in r.stdout.splitlines():
                p = line.strip()
                if p and int(p) != os.getpid():
                    pids.append(int(p))
    except Exception:
        pass
    return pids


def health_check(port, timeout=15):
    """轮询 localhost:port 直到可达或超时"""
    for _ in range(timeout):
        time.sleep(1)
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    return True
        except Exception:
            pass
    return False


def find_listener_pids(port):
    """查找监听指定端口的 PID。"""
    pids = []
    try:
        r = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
        )
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            local_addr = parts[1]
            state = parts[3] if IS_WIN else parts[-2]
            pid = parts[-1]
            if local_addr.endswith(f":{port}") and state.upper() == "LISTENING":
                try:
                    pids.append(int(pid))
                except ValueError:
                    continue
    except Exception:
        pass
    return sorted(set(pids))

# PLACEHOLDER_2

# ── commands ─────────────────────────────────────────────

REQUIRED_PACKAGES = {
    "nicegui": "nicegui",
    "yaml": "pyyaml",
    "requests": "requests",
    "numpy": "numpy",
    "PIL": "pillow",
    "lancedb": "lancedb",
    "langgraph": "langgraph",
    "cv2": "opencv-python",
}


def ensure_deps():
    """检查并自动安装缺失依赖"""
    missing = []
    for mod, pkg in REQUIRED_PACKAGES.items():
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if not missing:
        return
    info(f"安装缺失依赖: {', '.join(missing)}")
    python = get_python()
    subprocess.run(
        [python, "-m", "pip", "install", "-q"] + missing,
        cwd=str(ROOT),
    )

def cmd_start(args):
    """启动 NiceGUI Web 应用"""
    banner("启动")
    os.chdir(ROOT)
    (ROOT / "logs").mkdir(exist_ok=True)
    ensure_deps()
    cfg = load_runtime_config()
    ray_cfg = cfg.get("ray", {}) if cfg else {}
    ray_enabled = ray_cfg.get("enabled", False)

    # 检查是否已在运行
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text().strip())
            if pid_alive(old_pid):
                info(f"服务已在运行 (PID={old_pid})，如需重启请用 restart")
                return
        except (ValueError, OSError):
            pass
        PID_FILE.unlink(missing_ok=True)

    # 检查端口
    if is_port_in_use(APP_PORT):
        warn(f"端口 {APP_PORT} 已被占用")
        if IS_WIN:
            resp = input("  是否仍然尝试启动? (y/N): ").strip().lower()
            if resp != "y":
                return
        else:
            info("尝试释放端口...")
            for pid in find_app_pids():
                kill_pid(pid, force=True)
            time.sleep(1)

    python = get_python()
    info(f"Python: {python}")
    info(f"端口: {APP_PORT}")
    info(f"入口: {APP_ENTRY}")
    print()

    # 启动 Ray（在启动 Web 应用之前）
    ray_connect_address = start_ray()
    print()

    child_env = os.environ.copy()
    if ray_enabled and ray_connect_address:
        child_env["TOWER_EYE_RAY_ADDRESS"] = ray_connect_address
        info(f"应用将以 connect-only 模式连接 Ray: {ray_connect_address}")
        print()

    if IS_WIN:
        # Windows: 后台运行，日志写入 logs/app.log
        info("后台启动中...")
        with open(LOG_FILE, "a", encoding="utf-8") as log:
            proc = subprocess.Popen(
                [python, str(APP_ENTRY)],
                cwd=str(ROOT),
                stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW,
                env=child_env,
            )
        PID_FILE.write_text(str(proc.pid))

        # 健康检查
        info("等待启动...")
        if not pid_alive(proc.pid):
            fail("进程退出，启动失败！")
            info(f"查看日志: type {LOG_FILE}")
            PID_FILE.unlink(missing_ok=True)
            sys.exit(1)

        if health_check(APP_PORT):
            ok("启动成功")
            webbrowser.open(f"http://localhost:{APP_PORT}")
        else:
            warn("暂未响应，可能还在加载...")

        print()
        info(f"PID:  {proc.pid}")
        info(f"端口: {APP_PORT}")
        info(f"日志: {LOG_FILE}")
        info(f"地址: http://localhost:{APP_PORT}")
        print()
        info("停止: python bin/manage.py stop")
        info("状态: python bin/manage.py status")
    else:
        # Linux: 后台运行
        info("后台启动中...")
        with open(LOG_FILE, "a") as log:
            proc = subprocess.Popen(
                [python, str(APP_ENTRY)],
                cwd=str(ROOT),
                stdout=log, stderr=log,
                start_new_session=True,
                env=child_env,
            )
        PID_FILE.write_text(str(proc.pid))

        # 健康检查
        info("等待启动...")
        if not pid_alive(proc.pid):
            fail("进程退出，启动失败！")
            info(f"查看日志: tail -f {LOG_FILE}")
            PID_FILE.unlink(missing_ok=True)
            sys.exit(1)

        if health_check(APP_PORT):
            ok("启动成功")
        else:
            warn("暂未响应，可能还在加载...")

        print()
        info(f"PID:  {proc.pid}")
        info(f"端口: {APP_PORT}")
        info(f"日志: {LOG_FILE}")
        info(f"地址: http://localhost:{APP_PORT}")
        print()
        info("停止: python bin/manage.py stop")
        info("状态: python bin/manage.py status")

# PLACEHOLDER_3

def cmd_stop(args):
    """停止服务"""
    banner("停止")
    stopped = False

    # 0. 停止 Ray（在杀进程之前，优雅关闭）
    info("停止 Ray...")
    stop_ray()

    # 1. 通过 PID 文件
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            if pid_alive(pid):
                info(f"停止进程 PID={pid}...")
                kill_pid(pid)
                time.sleep(2)
                if pid_alive(pid):
                    warn("进程仍在运行，强制结束...")
                    kill_pid(pid, force=True)
                ok(f"已停止 (PID: {pid})")
                stopped = True
            else:
                info(f"PID {pid} 对应的进程不存在")
        except (ValueError, OSError):
            pass
        PID_FILE.unlink(missing_ok=True)

    # 2. 兜底：按进程名查杀
    for pid in find_app_pids():
        kill_pid(pid, force=True)
        ok(f"已清理 app_ui.py 残留进程 {pid}")
        stopped = True

    if not stopped:
        info("没有发现运行中的服务")

    print()
    info("停止完成。")


def cmd_restart(args):
    """重启服务"""
    cmd_stop(args)
    print()
    time.sleep(1)
    cmd_start(args)


def cmd_status(args):
    """查看运行状态"""
    banner("状态检查")
    cfg = load_runtime_config()
    ray_meta = get_ray_bootstrap_info()

    # [1] 进程状态
    print("[1] 进程状态")
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            if pid_alive(pid) or pid in find_listener_pids(APP_PORT):
                ok(f"运行中 (PID: {pid})")
            else:
                warn("PID 文件存在但进程不在运行")
        except (ValueError, OSError):
            warn("PID 文件内容异常")
    else:
        info("未找到 PID 文件")

    app_pids = find_app_pids()
    if app_pids:
        info(f"app_ui.py 进程: {app_pids}")

    # [2] 端口 & 连通性
    print()
    print("[2] 端口 & 连通性")
    if is_port_in_use(APP_PORT):
        ok(f"端口 {APP_PORT} 有服务监听")
        try:
            import urllib.request
            code = urllib.request.urlopen(
                f"http://127.0.0.1:{APP_PORT}", timeout=3
            ).getcode()
            ok(f"http://127.0.0.1:{APP_PORT} 响应正常 (HTTP {code})")
        except Exception:
            warn(f"http://127.0.0.1:{APP_PORT} 无法访问")
    else:
        info(f"端口 {APP_PORT} 未被占用")

    # [3] Ray Bootstrap
    print()
    print("[3] Ray Bootstrap")
    if ray_meta.get("address"):
        ok(f"connect-only 地址: {ray_meta['address']}")
        info(f"来源: {ray_meta.get('source', 'unknown')}")
    else:
        info("未发现本地 Ray bootstrap 记录")

    # [4] Python 环境
    print()
    print("[4] Python 环境")
    info(f"Python: {sys.version.split()[0]} ({sys.executable})")
    info(f"平台: {platform.system()} {platform.release()}")
    for mod in ["nicegui", "lancedb", "numpy", "requests"]:
        try:
            __import__(mod)
            ok(mod)
        except ImportError:
            warn(f"{mod} 未安装")

    # [5] 数据文件
    print()
    print("[5] 数据文件")
    db_path = resolve_config_path(cfg, "db_path", "data/metadata.db")
    lance_dir = resolve_config_path(cfg, "lancedb_dir", "data/lancedb")
    if db_path.exists():
        size_mb = db_path.stat().st_size / 1024 / 1024
        ok(f"metadata.db ({size_mb:.1f} MB)")
    else:
        warn("metadata.db 不存在")
    if lance_dir.exists() and any(lance_dir.iterdir()):
        ok("LanceDB 目录非空")
    else:
        warn("LanceDB 目录为空或不存在")

    # [6] 最近日志
    print()
    print("[6] 最近日志")
    if LOG_FILE.exists():
        lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines[-10:]:
            print(f"  {safe_console_text(line)}")
    else:
        info("日志文件不存在")
    print()

# PLACEHOLDER_4

def cmd_check(args):
    """检查环境、依赖、数据、远程服务"""
    banner("环境检查")
    cfg = load_runtime_config()

    # [1] Python 环境
    print("[1/4] Python 环境")
    python = get_python()
    info(f"解释器: {python}")
    r = subprocess.run([python, "--version"], capture_output=True, text=True)
    info(f"版本: {r.stdout.strip()}")
    if IS_WIN:
        venv = ROOT / ".venv"
        if venv.exists():
            ok(".venv 虚拟环境存在")
        else:
            warn(".venv 不存在，运行: python -m venv .venv")
    print()

    # [2] 依赖
    print("[2/4] 依赖检查")
    deps = ["nicegui", "yaml", "requests", "numpy", "PIL", "lancedb", "cv2"]
    dep_names = ["nicegui", "pyyaml", "requests", "numpy", "pillow", "lancedb", "opencv-python"]
    missing = []
    for mod, name in zip(deps, dep_names):
        try:
            __import__(mod)
            ok(name)
        except ImportError:
            warn(f"{name} 未安装")
            missing.append(name)
    if missing:
        print()
        info(f"安装缺失依赖: pip install {' '.join(missing)}")
    print()

    # [3] 数据文件
    print("[3/4] 数据文件")
    db_path = resolve_config_path(cfg, "db_path", "data/metadata.db")
    lance_dir = resolve_config_path(cfg, "lancedb_dir", "data/lancedb")
    if db_path.exists():
        ok("metadata.db 存在")
    else:
        warn("metadata.db 不存在")
        info("从服务器同步: scp -r root@服务器IP:.../data ./data/")
        info("或本地入库: python bin/manage.py ingest")
    if lance_dir.exists() and any(lance_dir.iterdir()):
        ok("LanceDB 向量数据存在")
    else:
        warn("LanceDB 为空，需要运行 embed")
    print()

    # [4] 远程服务
    print("[4/4] 远程模型服务")
    search_cfg = cfg.get("search", {}) if cfg else {}

    services = [
        ("Embedding", search_cfg.get("qwen_api_url", "http://10.132.19.82:8010")),
        ("Reranker", search_cfg.get("reranker_api_url", "http://10.132.19.82:8011")),
    ]
    for name, url in services:
        try:
            import urllib.request
            urllib.request.urlopen(f"{url}/docs", timeout=5)
            ok(f"{name} ({url}) 可达")
        except Exception:
            warn(f"{name} ({url}) 不可达")
    print()

# PLACEHOLDER_5

def cmd_ingest(args):
    """入库：数据导入 + 向量化"""
    banner("数据入库")
    os.chdir(ROOT)
    python = get_python()
    cfg = load_runtime_config()
    db_path = resolve_config_path(cfg, "db_path", "data/metadata.db")
    lance_dir = resolve_config_path(cfg, "lancedb_dir", "data/lancedb")
    data_root = db_path.parent

    mode = "full"
    if args.incremental:
        mode = "incremental"
    elif args.quick:
        mode = "quick"

    mode_labels = {
        "full": "完整入库（清理 → 导入 → 向量化）",
        "quick": "快速模式（仅重新生成向量）",
        "incremental": "增量模式（只处理新增图片）",
    }
    info(f"模式: {mode_labels[mode]}")
    info(f"Python: {python}")
    print()

    step = 0
    total = 2 if mode != "full" else 4
    start_time = time.time()

    # Step 1: 清理旧数据（仅 full 模式）
    if mode == "full":
        step += 1
        print(f"[{step}/{total}] 清理旧数据...")
        # 备份
        if lance_dir.exists() and any(lance_dir.iterdir()):
            import shutil
            backup = data_root / f"backup_{int(time.time())}"
            backup.mkdir(parents=True, exist_ok=True)
            if lance_dir.exists():
                shutil.copytree(lance_dir, backup / "lancedb", dirs_exist_ok=True)
            if db_path.exists():
                shutil.copy2(db_path, backup / "metadata.db")
            info(f"备份到: {backup}")
        # 清理
        if lance_dir.exists():
            shutil.rmtree(lance_dir, ignore_errors=True)
            lance_dir.mkdir(parents=True, exist_ok=True)
        db_path.unlink(missing_ok=True)
        ok("清理完成")
        print()

    # Step 2: 创建数据库结构（仅 full 模式）
    if mode == "full":
        step += 1
        print(f"[{step}/{total}] 创建数据库结构...")
        r = subprocess.run(
            [python, "-m", "poc.pipeline.ingest", "--config", str(CONFIG)],
            cwd=str(ROOT),
        )
        if r.returncode != 0:
            fail("数据库结构创建失败")
            sys.exit(1)
        ok("数据库结构创建完成")
        print()

    # Step 3: 导入告警数据（仅 full 模式）
    if mode == "full":
        step += 1
        print(f"[{step}/{total}] 导入告警数据...")
        r = subprocess.run(
            [python, str(ROOT / "import_warning_data.py")],
            cwd=str(ROOT),
        )
        if r.returncode != 0:
            fail("告警数据导入失败")
            sys.exit(1)
        ok("告警数据导入完成")
        print()

    # Step 4: 清理旧向量（非增量模式）
    step += 1
    if mode == "incremental":
        print(f"[{step}/{total}] 保留已有向量数据（增量模式）")
    else:
        print(f"[{step}/{total}] 清理旧向量数据...")
        if lance_dir.exists():
            import shutil
            shutil.rmtree(lance_dir, ignore_errors=True)
            lance_dir.mkdir(parents=True, exist_ok=True)
        ok("向量数据清理完成")
    print()

    # Step 5: 生成向量嵌入
    step += 1
    print(f"[{step}/{total}] 生成向量嵌入...")
    embed_cmd = [python, "-m", "poc.pipeline.embed", "--config", str(CONFIG)]
    if mode == "incremental":
        embed_cmd.append("--incremental")
    r = subprocess.run(embed_cmd, cwd=str(ROOT))
    if r.returncode != 0:
        fail("向量嵌入失败")
        sys.exit(1)

    elapsed = time.time() - start_time
    print()
    ok(f"入库完成！总耗时: {int(elapsed)}秒 ({int(elapsed//60)}分{int(elapsed%60)}秒)")
    print()

# PLACEHOLDER_6

# ── main ─────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="多模态检索系统 - 统一运维工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python bin/manage.py start            启动 Web 应用
  python bin/manage.py stop             停止服务
  python bin/manage.py restart          重启服务
  python bin/manage.py status           查看运行状态
  python bin/manage.py check            检查环境/依赖/数据
  python bin/manage.py ingest           全量入库
  python bin/manage.py ingest --quick   仅重新生成向量
  python bin/manage.py ingest --incremental  增量入库
""",
    )
    sub = parser.add_subparsers(dest="command", help="子命令")

    sub.add_parser("start", help="启动 NiceGUI Web 应用")
    sub.add_parser("stop", help="停止服务")
    sub.add_parser("restart", help="重启服务")
    sub.add_parser("status", help="查看运行状态")
    sub.add_parser("check", help="检查环境/依赖/数据/远程服务")

    p_ingest = sub.add_parser("ingest", help="数据入库")
    p_ingest.add_argument("--quick", action="store_true",
                          help="快速模式：跳过数据导入，仅重新生成向量")
    p_ingest.add_argument("--incremental", action="store_true",
                          help="增量模式：只处理新增图片")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    commands = {
        "start": cmd_start,
        "stop": cmd_stop,
        "restart": cmd_restart,
        "status": cmd_status,
        "check": cmd_check,
        "ingest": cmd_ingest,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
