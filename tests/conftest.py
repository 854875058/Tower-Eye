"""
pytest fixtures for Tower-Eye tests
"""

import json
import sys
from pathlib import Path
from typing import Dict, List

import pytest

# 添加项目根目录到路径
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from poc.pipeline.utils import load_yaml


@pytest.fixture(scope="session")
def config() -> Dict:
    """
    加载 POC 配置文件
    
    优先使用 poc/config/poc.yaml，如果不存在则使用 poc.yaml.example
    """
    config_path = ROOT / "poc" / "config" / "poc.yaml"
    example_path = ROOT / "poc" / "config" / "poc.yaml.example"
    
    if config_path.exists():
        return load_yaml(str(config_path))
    elif example_path.exists():
        return load_yaml(str(example_path))
    else:
        pytest.skip("配置文件不存在: poc/config/poc.yaml 或 poc.yaml.example")


@pytest.fixture(scope="session")
def golden_set() -> List[Dict]:
    """
    加载 NL2SQL 测试黄金数据集
    
    从 tests/data/qa_golden_set.json 加载测试用例
    """
    golden_set_path = ROOT / "tests" / "data" / "qa_golden_set.json"
    
    if not golden_set_path.exists():
        pytest.skip(f"测试数据集不存在: {golden_set_path}")
    
    with open(golden_set_path, "r", encoding="utf-8") as f:
        return json.load(f)
