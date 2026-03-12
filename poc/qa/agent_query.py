"""
使用 LangGraph Agent 进行智能查询的示例脚本

用法：
    python -m poc.qa.agent_query --question "近7天车辆闯入监控告警有多少条？"
    python -m poc.qa.agent_query --question "查询最近的10条告警" --visualize
"""

import argparse
import json
from pathlib import Path

from poc.pipeline.utils import load_yaml, resolve_path
from poc.qa.agent import create_agent
from poc.qa.trace import init_trace_manager


def main():
    parser = argparse.ArgumentParser(description="使用 LangGraph Agent 进行智能查询")
    parser.add_argument("--config", default="poc/config/poc.yaml", help="配置文件路径")
    parser.add_argument("--question", required=True, help="用户问题")
    parser.add_argument("--user-id", help="用户ID（用于追踪）")
    parser.add_argument("--session-id", help="会话ID（用于追踪）")
    parser.add_argument("--max-retries", type=int, default=3, help="最大重试次数")
    parser.add_argument("--visualize", action="store_true", help="可视化状态图")
    parser.add_argument("--enable-trace", action="store_true", help="启用追踪记录")
    args = parser.parse_args()

    # 加载配置
    config = load_yaml(args.config)

    # 初始化追踪管理器（可选）
    if args.enable_trace:
        paths_cfg = config.get("paths", {})
        trace_db_path = resolve_path(paths_cfg.get("trace_db_path", "data/traces.db"))
        log_dir = resolve_path(paths_cfg.get("log_dir", "logs")) / "traces"
        trace_db_path.parent.mkdir(parents=True, exist_ok=True)
        init_trace_manager(
            db_path=trace_db_path,
            enable_file_log=True,
            log_dir=log_dir,
        )
        print(f"[OK] 追踪系统已启用，数据库: {trace_db_path}")

    # 创建 Agent
    agent = create_agent(config, max_retries=args.max_retries)

    # 可视化状态图（可选）
    if args.visualize:
        try:
            agent.visualize()
            print("[OK] 状态图已生成")
        except Exception as e:
            print(f"⚠ 状态图生成失败: {e}")

    # 执行查询
    print(f"\n{'='*80}")
    print(f"问题: {args.question}")
    print(f"{'='*80}\n")

    result = agent.query(
        question=args.question,
        user_id=args.user_id,
        session_id=args.session_id
    )

    # 输出结果
    print(f"\n{'='*80}")
    print("查询结果:")
    print(f"{'='*80}\n")

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    # 输出摘要
    print(f"\n{'='*80}")
    print("执行摘要:")
    print(f"{'='*80}")
    print(f"状态: {'[OK] 成功' if result['status'] == 'success' else '✗ 失败'}")
    print(f"意图: {result['intent']}")
    print(f"SQL: {result['sql']}")
    print(f"重试次数: {result['retry_count']}")
    if result['error']:
        print(f"错误: {result['error']}")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    main()

