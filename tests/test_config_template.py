"""
配置模板完整性测试

用于 pytest 或 CI 集成，确保配置模板与代码保持同步。
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bin.check_config_template import (
    load_config_template,
    get_required_config_keys,
    check_config_completeness,
)


def test_config_template_exists():
    """测试配置模板文件是否存在"""
    template_path = Path(__file__).resolve().parents[1] / "poc/config/poc.yaml.example"
    assert template_path.exists(), f"配置模板文件不存在: {template_path}"


def test_config_template_completeness():
    """测试配置模板是否包含所有必需的配置项"""
    template = load_config_template()
    required = get_required_config_keys()
    
    is_complete = check_config_completeness(template, required, strict=True)
    assert is_complete, "配置模板缺失必需的配置项"


def test_all_sections_present():
    """测试所有顶层配置节是否存在"""
    template = load_config_template()
    required = get_required_config_keys()
    
    for section in required.keys():
        assert section in template, f"缺失顶层配置节: {section}"


if __name__ == "__main__":
    # 支持直接运行测试
    test_config_template_exists()
    print("✅ 配置模板文件存在")
    
    test_all_sections_present()
    print("✅ 所有顶层配置节存在")
    
    test_config_template_completeness()
    print("✅ 配置模板完整性测试通过")
