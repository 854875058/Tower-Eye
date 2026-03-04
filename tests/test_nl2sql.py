"""
NL2SQL 准确率测试

测试 NL2SQL 模块的意图识别和 SQL 生成准确率
"""

import json
import re
import sys
from pathlib import Path
from typing import Dict, List

# 添加项目根目录到路径
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from poc.pipeline.utils import load_yaml
from poc.qa.nl2sql import build_query_plan


def load_golden_set(path: str = "tests/data/qa_golden_set.json") -> List[Dict]:
    """加载测试数据集"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_intent_accuracy(config: Dict, golden_set: List[Dict]) -> Dict:
    """测试意图识别准确率"""
    total = len(golden_set)
    correct = 0
    errors = []

    for item in golden_set:
        question = item["question"]
        expected_intent = item["expected_intent"]

        try:
            plan = build_query_plan(question, config)
            actual_intent = plan.intent

            if actual_intent == expected_intent:
                correct += 1
            else:
                errors.append({
                    "id": item["id"],
                    "question": question,
                    "expected": expected_intent,
                    "actual": actual_intent
                })
        except Exception as e:
            errors.append({
                "id": item["id"],
                "question": question,
                "expected": expected_intent,
                "error": str(e)
            })

    accuracy = correct / total if total > 0 else 0

    return {
        "total": total,
        "correct": correct,
        "accuracy": accuracy,
        "errors": errors
    }


def test_sql_generation(config: Dict, golden_set: List[Dict]) -> Dict:
    """测试 SQL 生成质量"""
    total = 0
    passed = 0
    errors = []

    for item in golden_set:
        # 跳过视觉搜索（不生成 SQL）
        if item["expected_intent"] == "search":
            continue

        total += 1
        question = item["question"]
        expected_pattern = item.get("expected_sql_pattern")
        expected_has_time = item.get("expected_has_time_filter", False)

        try:
            plan = build_query_plan(question, config)
            sql = plan.sql

            if not sql:
                errors.append({
                    "id": item["id"],
                    "question": question,
                    "error": "SQL 为空"
                })
                continue

            # 检查 SQL 模式匹配
            pattern_match = True
            if expected_pattern:
                pattern_match = bool(re.search(expected_pattern, sql, re.IGNORECASE))

            # 检查时间过滤
            has_time_filter = "alarm_time" in sql.lower() or "date(" in sql.lower()
            time_match = has_time_filter == expected_has_time

            if pattern_match and time_match:
                passed += 1
            else:
                errors.append({
                    "id": item["id"],
                    "question": question,
                    "sql": sql,
                    "pattern_match": pattern_match,
                    "time_match": time_match,
                    "expected_pattern": expected_pattern,
                    "expected_has_time": expected_has_time
                })

        except Exception as e:
            errors.append({
                "id": item["id"],
                "question": question,
                "error": str(e)
            })

    accuracy = passed / total if total > 0 else 0

    return {
        "total": total,
        "passed": passed,
        "accuracy": accuracy,
        "errors": errors
    }


def run_nl2sql_tests():
    """运行 NL2SQL 测试套件"""
    print("=" * 60)
    print("NL2SQL 准确率测试")
    print("=" * 60)

    # 加载配置
    config = load_yaml("poc/config/poc.yaml")

    # 加载测试数据
    golden_set = load_golden_set()
    print(f"\n加载测试数据集: {len(golden_set)} 条")

    # 测试意图识别
    print("\n[1/2] 测试意图识别...")
    intent_result = test_intent_accuracy(config, golden_set)
    print(f"  总数: {intent_result['total']}")
    print(f"  正确: {intent_result['correct']}")
    print(f"  准确率: {intent_result['accuracy']:.2%}")

    if intent_result['errors']:
        print(f"  错误数: {len(intent_result['errors'])}")
        for err in intent_result['errors'][:3]:  # 只显示前3个
            print(f"    - ID {err['id']}: {err['question']}")
            if 'error' in err:
                print(f"      错误: {err['error']}")
            else:
                print(f"      期望: {err['expected']}, 实际: {err['actual']}")

    # 测试 SQL 生成
    print("\n[2/2] 测试 SQL 生成...")
    sql_result = test_sql_generation(config, golden_set)
    print(f"  总数: {sql_result['total']}")
    print(f"  通过: {sql_result['passed']}")
    print(f"  准确率: {sql_result['accuracy']:.2%}")

    if sql_result['errors']:
        print(f"  错误数: {len(sql_result['errors'])}")
        for err in sql_result['errors'][:3]:  # 只显示前3个
            print(f"    - ID {err['id']}: {err['question']}")
            if 'error' in err:
                print(f"      错误: {err['error']}")
            else:
                print(f"      SQL: {err.get('sql', 'N/A')[:100]}")

    # 总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    print(f"意图识别准确率: {intent_result['accuracy']:.2%}")
    print(f"SQL 生成准确率: {sql_result['accuracy']:.2%}")

    overall_accuracy = (intent_result['accuracy'] + sql_result['accuracy']) / 2
    print(f"综合准确率: {overall_accuracy:.2%}")

    return {
        "intent": intent_result,
        "sql": sql_result,
        "overall_accuracy": overall_accuracy
    }


if __name__ == "__main__":
    run_nl2sql_tests()
