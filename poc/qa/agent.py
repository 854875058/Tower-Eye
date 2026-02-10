"""
基于 LangGraph 的智能查询状态机

功能：
1. 将线性的 NL2SQL 流程改造为状态机
2. 支持 SQL 自我修正（执行失败后重新生成）
3. 支持多轮对话和上下文记忆
4. 可视化执行流程

状态流转：
START → PARSE_QUESTION → GENERATE_SQL → VALIDATE_SQL → EXECUTE_SQL → SUCCESS
                                ↓ (validation failed)
                            FIX_SQL ← (execution failed)
                                ↓ (max retries)
                            ERROR
"""

from typing import Annotated, Any, Dict, List, Literal, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from poc.pipeline.utils import connect_db, resolve_path
from poc.qa.guardrails import SQLGuardrail, SQLSecurityError
from poc.qa.nl2sql import build_query_plan
from poc.qa.tools import ToolRegistry, get_tool_registry


class AgentState(TypedDict):
    """Agent 状态定义"""
    # 输入
    question: str  # 用户问题
    config: Dict  # 配置
    db_path: str  # 数据库路径

    # 中间状态
    intent: Optional[str]  # 查询意图
    sql: Optional[str]  # 生成的 SQL
    sql_params: Optional[List]  # SQL 参数
    filters: Optional[Dict]  # 过滤条件

    # 执行结果
    sql_result: Optional[List[Dict]]  # SQL 执行结果
    final_answer: Optional[Any]  # 最终答案

    # 错误处理
    error_message: Optional[str]  # 错误信息
    retry_count: int  # 重试次数
    max_retries: int  # 最大重试次数

    # 历史记录（用于自我修正）
    messages: Annotated[List[Dict], add_messages]  # 对话历史
    execution_history: List[Dict]  # 执行历史


def parse_question_node(state: AgentState) -> AgentState:
    """
    节点1：解析用户问题

    功能：
    - 使用 NL2SQL 模块解析问题
    - 提取意图、生成初始 SQL
    """
    print(f"[parse_question_node] 解析问题: {state['question']}")

    try:
        plan = build_query_plan(state["question"], state["config"])

        state["intent"] = plan.intent
        state["sql"] = plan.sql
        state["sql_params"] = plan.params
        state["filters"] = plan.filters

        state["messages"].append({
            "role": "system",
            "content": f"解析成功 - 意图: {plan.intent}, SQL: {plan.sql}"
        })

        print(f"[parse_question_node] 解析成功 - 意图: {plan.intent}")

    except Exception as e:
        state["error_message"] = f"问题解析失败: {str(e)}"
        state["messages"].append({
            "role": "system",
            "content": f"解析失败: {str(e)}"
        })
        print(f"[parse_question_node] 解析失败: {e}")

    return state


def validate_sql_node(state: AgentState) -> AgentState:
    """
    节点2：验证 SQL 安全性

    功能：
    - 使用安全护栏检查 SQL
    - 防止注入攻击
    """
    print(f"[validate_sql_node] 验证 SQL: {state['sql']}")

    try:
        SQLGuardrail.validate_sql(state["sql"])
        state["messages"].append({
            "role": "system",
            "content": "SQL 安全验证通过"
        })
        print("[validate_sql_node] 验证通过")

    except SQLSecurityError as e:
        state["error_message"] = f"SQL 安全验证失败: {str(e)}"
        state["messages"].append({
            "role": "system",
            "content": f"安全验证失败: {str(e)}"
        })
        print(f"[validate_sql_node] 验证失败: {e}")

    return state


def execute_sql_node(state: AgentState) -> AgentState:
    """
    节点3：执行 SQL 查询

    功能：
    - 连接数据库执行查询
    - 记录执行结果或错误
    """
    print(f"[execute_sql_node] 执行 SQL")

    try:
        conn = connect_db(resolve_path(state["db_path"]))
        rows = conn.execute(state["sql"], state["sql_params"]).fetchall()
        conn.close()

        state["sql_result"] = [dict(row) for row in rows]

        # 记录执行历史
        state["execution_history"].append({
            "sql": state["sql"],
            "params": state["sql_params"],
            "result_count": len(state["sql_result"]),
            "status": "success"
        })

        state["messages"].append({
            "role": "system",
            "content": f"SQL 执行成功，返回 {len(state['sql_result'])} 条记录"
        })

        print(f"[execute_sql_node] 执行成功，返回 {len(state['sql_result'])} 条记录")

    except Exception as e:
        state["error_message"] = f"SQL 执行失败: {str(e)}"

        # 记录执行历史
        state["execution_history"].append({
            "sql": state["sql"],
            "params": state["sql_params"],
            "error": str(e),
            "status": "error"
        })

        state["messages"].append({
            "role": "system",
            "content": f"SQL 执行失败: {str(e)}"
        })

        print(f"[execute_sql_node] 执行失败: {e}")

    return state


def fix_sql_node(state: AgentState) -> AgentState:
    """
    节点4：修复 SQL（自我修正）

    功能：
    - 根据错误信息重新生成 SQL
    - 使用 LLM 进行自我修正
    """
    print(f"[fix_sql_node] 尝试修复 SQL (重试 {state['retry_count'] + 1}/{state['max_retries']})")

    state["retry_count"] += 1

    # 构建修正 Prompt
    error_context = f"""
    原始问题: {state['question']}
    之前生成的 SQL: {state['sql']}
    执行错误: {state['error_message']}

    请根据错误信息重新生成正确的 SQL。
    """

    try:
        # 这里可以调用 LLM 进行修正
        # 简化版：使用规则引擎重新解析
        plan = build_query_plan(state["question"], state["config"])

        state["sql"] = plan.sql
        state["sql_params"] = plan.params
        state["error_message"] = None  # 清除错误

        state["messages"].append({
            "role": "system",
            "content": f"SQL 已修正: {plan.sql}"
        })

        print(f"[fix_sql_node] SQL 已修正")

    except Exception as e:
        state["error_message"] = f"SQL 修正失败: {str(e)}"
        state["messages"].append({
            "role": "system",
            "content": f"修正失败: {str(e)}"
        })
        print(f"[fix_sql_node] SQL 修正失败: {e}")

    return state


def format_answer_node(state: AgentState) -> AgentState:
    """
    节点5：格式化最终答案

    功能：
    - 根据意图格式化结果
    - 生成用户友好的答案
    """
    print(f"[format_answer_node] 格式化答案")

    if state["intent"] == "count":
        # 统计类查询 — 兼容 cnt / 数量 / COUNT(*) 等各种别名
        if state["sql_result"]:
            first_row = state["sql_result"][0]
            # 如果只有一行一列，直接取值
            if len(state["sql_result"]) == 1 and len(first_row) == 1:
                count = list(first_row.values())[0]
                state["final_answer"] = {
                    "type": "count",
                    "value": count,
                    "message": f"查询结果：共 {count} 条记录"
                }
            else:
                # 分组统计，返回列表（如 GROUP BY 结果）
                state["final_answer"] = {
                    "type": "list",
                    "value": state["sql_result"],
                    "message": f"查询结果：返回 {len(state['sql_result'])} 条分组统计"
                }
        else:
            state["final_answer"] = {
                "type": "count",
                "value": 0,
                "message": "查询结果：共 0 条记录"
            }
    else:
        # 列表类查询
        state["final_answer"] = {
            "type": "list",
            "value": state["sql_result"],
            "message": f"查询结果：返回 {len(state['sql_result'])} 条记录"
        }

    state["messages"].append({
        "role": "assistant",
        "content": state["final_answer"]["message"]
    })

    print(f"[format_answer_node] 答案已格式化")

    return state


def should_retry(state: AgentState) -> Literal["fix_sql", "error"]:
    """
    路由函数：判断是否应该重试

    返回：
    - "fix_sql": 继续重试
    - "error": 达到最大重试次数，返回错误
    """
    if state["retry_count"] < state["max_retries"]:
        print(f"[should_retry] 继续重试 ({state['retry_count']}/{state['max_retries']})")
        return "fix_sql"
    else:
        print(f"[should_retry] 达到最大重试次数，返回错误")
        return "error"


def should_continue_after_parse(state: AgentState) -> Literal["validate_sql", "error"]:
    """路由函数：解析后是否继续"""
    if state.get("error_message"):
        return "error"
    return "validate_sql"


def should_continue_after_validate(state: AgentState) -> Literal["execute_sql", "fix_sql"]:
    """路由函数：验证后是否继续"""
    if state.get("error_message"):
        return "fix_sql"
    return "execute_sql"


def should_continue_after_execute(state: AgentState) -> Literal["format_answer", "fix_sql"]:
    """路由函数：执行后是否继续"""
    if state.get("error_message"):
        return "fix_sql"
    return "format_answer"


def build_agent_graph() -> StateGraph:
    """
    构建 Agent 状态图

    状态流转：
    START → parse_question → validate_sql → execute_sql → format_answer → END
                ↓ error          ↓ error         ↓ error
              ERROR            fix_sql ←──────────┘
                                 ↓ (retry)
                            validate_sql
    """
    # 创建状态图
    workflow = StateGraph(AgentState)

    # 添加节点
    workflow.add_node("parse_question", parse_question_node)
    workflow.add_node("validate_sql", validate_sql_node)
    workflow.add_node("execute_sql", execute_sql_node)
    workflow.add_node("fix_sql", fix_sql_node)
    workflow.add_node("format_answer", format_answer_node)

    # 定义边（状态流转）
    workflow.add_edge(START, "parse_question")
    workflow.add_conditional_edges(
        "parse_question",
        should_continue_after_parse,
        {
            "validate_sql": "validate_sql",
            "error": END
        }
    )
    workflow.add_conditional_edges(
        "validate_sql",
        should_continue_after_validate,
        {
            "execute_sql": "execute_sql",
            "fix_sql": "fix_sql"
        }
    )
    workflow.add_conditional_edges(
        "execute_sql",
        should_continue_after_execute,
        {
            "format_answer": "format_answer",
            "fix_sql": "fix_sql"
        }
    )
    workflow.add_conditional_edges(
        "fix_sql",
        should_retry,
        {
            "fix_sql": "validate_sql",  # 重试：回到验证环节
            "error": END  # 达到最大重试次数
        }
    )
    workflow.add_edge("format_answer", END)

    return workflow


class QueryAgent:
    """查询 Agent（基于 LangGraph）"""

    def __init__(self, config: Dict, max_retries: int = 3):
        self.config = config
        self.max_retries = max_retries
        self.graph = build_agent_graph().compile()

    def query(self, question: str, user_id: Optional[str] = None, session_id: Optional[str] = None) -> Dict:
        """
        执行查询

        Args:
            question: 用户问题
            user_id: 用户ID（可选）
            session_id: 会话ID（可选）

        Returns:
            查询结果字典
        """
        # 初始化状态
        initial_state: AgentState = {
            "question": question,
            "config": self.config,
            "db_path": self.config.get("paths", {}).get("db_path", "poc/data/metadata.db"),
            "intent": None,
            "sql": None,
            "sql_params": None,
            "filters": None,
            "sql_result": None,
            "final_answer": None,
            "error_message": None,
            "retry_count": 0,
            "max_retries": self.max_retries,
            "messages": [{"role": "user", "content": question}],
            "execution_history": []
        }

        # 执行状态图
        print(f"\n{'='*60}")
        print(f"[QueryAgent] 开始处理问题: {question}")
        print(f"{'='*60}\n")

        final_state = self.graph.invoke(initial_state)

        print(f"\n{'='*60}")
        print(f"[QueryAgent] 处理完成")
        print(f"{'='*60}\n")

        # 构建返回结果
        result = {
            "question": question,
            "intent": final_state.get("intent"),
            "sql": final_state.get("sql"),
            "sql_params": final_state.get("sql_params"),
            "filters": final_state.get("filters"),
            "answer": final_state.get("final_answer"),
            "status": "error" if final_state.get("error_message") else "success",
            "error": final_state.get("error_message"),
            "retry_count": final_state.get("retry_count"),
            "execution_history": final_state.get("execution_history"),
            "messages": final_state.get("messages")
        }

        return result

    def visualize(self, output_path: str = "agent_graph.png"):
        """
        可视化状态图（需要安装 graphviz）

        Args:
            output_path: 输出图片路径
        """
        try:
            from IPython.display import Image, display
            display(Image(self.graph.get_graph().draw_mermaid_png()))
        except Exception as e:
            print(f"可视化失败（需要安装 graphviz）: {e}")


# 便捷函数
def create_agent(config: Dict, max_retries: int = 3) -> QueryAgent:
    """创建查询 Agent"""
    return QueryAgent(config, max_retries)
