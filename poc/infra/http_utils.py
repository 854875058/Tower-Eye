"""
公共 HTTP 工具 + 日志配置
提供带重试的 HTTP 请求、服务健康检查、统一日志
"""
import logging
import time
import requests
from typing import Optional

# ── 统一日志 ──────────────────────────────────────────────────────────────

def get_logger(name: str) -> logging.Logger:
    """获取统一格式的 logger"""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(
            "[%(asctime)s] %(name)s %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


# ── 带重试的 HTTP POST ────────────────────────────────────────────────────

def post_with_retry(
    url: str,
    json: dict,
    timeout: int = 30,
    max_retries: int = 3,
    backoff_base: float = 1.0,
    logger: Optional[logging.Logger] = None,
) -> requests.Response:
    """
    带指数退避重试的 HTTP POST 请求。

    仅对网络错误和 5xx 重试，4xx 直接抛出。
    """
    log = logger or get_logger("http")
    last_exc = None

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(url, json=json, timeout=timeout)
            if resp.status_code < 500:
                resp.raise_for_status()
                return resp
            # 5xx: 可重试
            last_exc = requests.exceptions.HTTPError(
                f"HTTP {resp.status_code}", response=resp
            )
        except requests.exceptions.ConnectionError as e:
            last_exc = e
        except requests.exceptions.Timeout as e:
            last_exc = e
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code < 500:
                raise  # 4xx 不重试
            last_exc = e

        if attempt < max_retries:
            wait = backoff_base * (2 ** (attempt - 1))
            log.warning("POST %s 失败 (第%d次), %.1fs 后重试: %s", url, attempt, wait, last_exc)
            time.sleep(wait)

    log.error("POST %s 最终失败 (共%d次): %s", url, max_retries, last_exc)
    raise last_exc


# ── 服务健康检查 ──────────────────────────────────────────────────────────

def check_service_health(url: str, timeout: int = 5) -> dict:
    """
    检查远程服务是否可达。

    Returns:
        {"available": bool, "latency_ms": float, "error": str|None}
    """
    try:
        start = time.time()
        resp = requests.get(url, timeout=timeout)
        latency = (time.time() - start) * 1000
        return {"available": True, "latency_ms": round(latency, 1), "error": None}
    except requests.exceptions.ConnectionError:
        return {"available": False, "latency_ms": 0, "error": "连接被拒绝"}
    except requests.exceptions.Timeout:
        return {"available": False, "latency_ms": 0, "error": "连接超时"}
    except Exception as e:
        return {"available": False, "latency_ms": 0, "error": str(e)}


def check_all_services(config: dict) -> dict:
    """检查所有外部服务的健康状态"""
    results = {}
    search_cfg = config.get("search", {})

    # Qwen Embedding
    qwen_url = search_cfg.get("qwen_api_url", "")
    if qwen_url:
        results["qwen_embedding"] = check_service_health(qwen_url)

    # Qwen Reranker
    reranker_url = search_cfg.get("reranker_api_url", "")
    if reranker_url and search_cfg.get("reranker_enabled"):
        results["qwen_reranker"] = check_service_health(reranker_url)

    # VLLM (VL 检测)
    results["vllm"] = check_service_health("http://10.132.19.82:50100")

    # DeepSeek LLM
    llm_cfg = config.get("llm", {})
    if llm_cfg.get("enabled"):
        results["deepseek"] = check_service_health(
            llm_cfg.get("base_url", "https://api.deepseek.com")
        )

    return results
