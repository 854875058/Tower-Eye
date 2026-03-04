"""
自动化评估脚本

运行所有测试并生成评估报告
"""

import json
import sys
from datetime import datetime
from pathlib import Path

# 添加项目根目录到路径
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.test_nl2sql import run_nl2sql_tests


def generate_report(results: dict, output_path: str = "tests/reports/evaluation_report.json"):
    """生成评估报告"""
    report = {
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "intent_accuracy": results["intent"]["accuracy"],
            "sql_accuracy": results["sql"]["accuracy"],
            "overall_accuracy": results["overall_accuracy"]
        },
        "details": {
            "intent_recognition": {
                "total": results["intent"]["total"],
                "correct": results["intent"]["correct"],
                "errors": results["intent"]["errors"]
            },
            "sql_generation": {
                "total": results["sql"]["total"],
                "passed": results["sql"]["passed"],
                "errors": results["sql"]["errors"]
            }
        }
    }

    # 保存报告
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n评估报告已保存: {output_file}")

    # 生成 Markdown 报告
    md_path = output_file.with_suffix(".md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# NL2SQL 评估报告\n\n")
        f.write(f"**生成时间**: {report['timestamp']}\n\n")
        f.write(f"## 总结\n\n")
        f.write(f"- **意图识别准确率**: {report['summary']['intent_accuracy']:.2%}\n")
        f.write(f"- **SQL 生成准确率**: {report['summary']['sql_accuracy']:.2%}\n")
        f.write(f"- **综合准确率**: {report['summary']['overall_accuracy']:.2%}\n\n")

        f.write(f"## 详细结果\n\n")
        f.write(f"### 意图识别\n\n")
        f.write(f"- 总数: {report['details']['intent_recognition']['total']}\n")
        f.write(f"- 正确: {report['details']['intent_recognition']['correct']}\n")
        f.write(f"- 错误数: {len(report['details']['intent_recognition']['errors'])}\n\n")

        if report['details']['intent_recognition']['errors']:
            f.write(f"#### 错误案例\n\n")
            for err in report['details']['intent_recognition']['errors'][:5]:
                f.write(f"- **ID {err['id']}**: {err['question']}\n")
                if 'error' in err:
                    f.write(f"  - 错误: {err['error']}\n")
                else:
                    f.write(f"  - 期望: {err['expected']}, 实际: {err['actual']}\n")
                f.write("\n")

        f.write(f"### SQL 生成\n\n")
        f.write(f"- 总数: {report['details']['sql_generation']['total']}\n")
        f.write(f"- 通过: {report['details']['sql_generation']['passed']}\n")
        f.write(f"- 错误数: {len(report['details']['sql_generation']['errors'])}\n\n")

        if report['details']['sql_generation']['errors']:
            f.write(f"#### 错误案例\n\n")
            for err in report['details']['sql_generation']['errors'][:5]:
                f.write(f"- **ID {err['id']}**: {err['question']}\n")
                if 'error' in err:
                    f.write(f"  - 错误: {err['error']}\n")
                else:
                    f.write(f"  - SQL: `{err.get('sql', 'N/A')[:100]}`\n")
                f.write("\n")

    print(f"Markdown 报告已保存: {md_path}")


def main():
    """主函数"""
    print("开始自动化评估...\n")

    # 运行 NL2SQL 测试
    results = run_nl2sql_tests()

    # 生成报告
    generate_report(results)

    print("\n评估完成！")

    # 返回退出码（准确率低于80%时返回1）
    if results["overall_accuracy"] < 0.8:
        print("\n警告: 综合准确率低于80%")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
