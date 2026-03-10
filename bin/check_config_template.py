#!/usr/bin/env python3
"""
配置模板完整性检查脚本

检查 poc/config/poc.yaml.example 是否包含代码实际需要的所有配置项。
用于 CI 或本地测试，确保配置模板与代码保持同步。

用法:
    python bin/check_config_template.py
    python bin/check_config_template.py --strict  # 严格模式，发现缺失项立即退出
"""

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

import yaml


def repo_root() -> Path:
    """获取仓库根目录"""
    return Path(__file__).resolve().parents[1]


def load_config_template() -> Dict[str, Any]:
    """加载配置模板文件"""
    template_path = repo_root() / "poc/config/poc.yaml.example"
    if not template_path.exists():
        print(f"❌ 配置模板文件不存在: {template_path}")
        sys.exit(1)
    
    with template_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_required_config_keys() -> Dict[str, List[str]]:
    """
    定义代码中实际使用的配置项路径
    
    基于代码分析结果，提取所有 config.get() 调用中使用的配置项。
    格式: {顶层key: [子key列表]}
    """
    return {
        "paths": [
            "raw_images_dir",
            "raw_videos_dir",
            "structured_dir",
            "db_path",
            "schema_path",
            "lancedb_dir",
            "trace_db_path",
            "log_dir",
            "embeddings_dir",
            "index_dir",
            # "metrics_db_path",  # 可选项，代码中有默认值
        ],
        "ingest": [
            "asset_id_strategy",
            "structured_files",
            "default_source",
            "default_region",
        ],
        "search": [
            "embedding_model",
            "clip_model",
            "model_cache_dir",
            "model_source",
            "hf_mirror",
            "qwen_api_url",
            "qwen_timeout",
            "qwen_dummy_image",
            "reranker_enabled",
            "reranker_api_url",
            "reranker_timeout",
            "reranker_top_k",
            "vector_weight",
            "keyword_weight",
            "top_k",
            "device",
            "batch_size",
            "auto_batch_size",
        ],
        "llm": [
            "enabled",
            "provider",
            "base_url",
            "model",
            "api_key_env",
            "mode",
            "api_key",
        ],
        "agent": [
            "enabled",
            "max_retries",
            "enable_trace",
            "enable_security",
        ],
        "security": [
            "allowed_tables",
            "sensitive_tables",
        ],
        "train": [
            "yolo_model",
            "epochs",
            "imgsz",
        ],
        "gaode": [
            "api_key",
            "geocode_url",
        ],
        "ray": [
            "enabled",
            "address",
            "num_gpus",
            "dashboard_port",
            "namespace",
        ],
    }


def check_config_completeness(
    template: Dict[str, Any],
    required: Dict[str, List[str]],
    strict: bool = False
) -> bool:
    """
    检查配置模板是否包含所有必需的配置项
    
    Args:
        template: 配置模板字典
        required: 必需的配置项字典
        strict: 严格模式，发现缺失项立即返回 False
    
    Returns:
        True 如果所有配置项都存在，否则 False
    """
    all_ok = True
    missing_items: List[str] = []
    
    for section, keys in required.items():
        if section not in template:
            print(f"❌ 缺失顶层配置节: {section}")
            missing_items.append(section)
            all_ok = False
            if strict:
                return False
            continue
        
        section_data = template[section]
        if not isinstance(section_data, dict):
            print(f"⚠️  配置节 {section} 不是字典类型")
            continue
        
        for key in keys:
            if key not in section_data:
                print(f"❌ 缺失配置项: {section}.{key}")
                missing_items.append(f"{section}.{key}")
                all_ok = False
                if strict:
                    return False
    
    if all_ok:
        print("✅ 配置模板完整性检查通过")
        print(f"   检查了 {len(required)} 个配置节，共 {sum(len(v) for v in required.values())} 个配置项")
    else:
        print(f"\n⚠️  发现 {len(missing_items)} 个缺失的配置项")
        print("   请更新 poc/config/poc.yaml.example 文件")
    
    return all_ok


def main():
    parser = argparse.ArgumentParser(
        description="检查配置模板完整性",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="严格模式：发现缺失项立即退出（返回非零状态码）"
    )
    args = parser.parse_args()
    
    print("🔍 开始检查配置模板完整性...")
    print(f"   模板文件: poc/config/poc.yaml.example")
    print()
    
    template = load_config_template()
    required = get_required_config_keys()
    
    is_complete = check_config_completeness(template, required, args.strict)
    
    if not is_complete:
        sys.exit(1)
    
    sys.exit(0)


if __name__ == "__main__":
    main()
