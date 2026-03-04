"""
对话历史管理模块

功能：
1. 维护多轮对话上下文
2. 支持上下文追问（省略主语、代词指代等）
3. 对话历史压缩（避免上下文过长）
4. 会话管理（多用户、多会话隔离）
"""

import json
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class ConversationTurn:
    """单轮对话"""
    turn_id: int
    timestamp: str
    user_question: str  # 用户原始问题
    resolved_question: str  # 解析后的完整问题（补全上下文）
    intent: str  # 查询意图
    sql: Optional[str] = None  # 生成的SQL
    result_count: int = 0  # 结果数量
    status: str = "success"  # success/error
    error: Optional[str] = None


@dataclass
class Conversation:
    """对话会话"""
    session_id: str
    user_id: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_active: str = field(default_factory=lambda: datetime.now().isoformat())
    turns: List[ConversationTurn] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)  # 上下文信息（实体、时间范围等）

    def add_turn(self, turn: ConversationTurn):
        """添加一轮对话"""
        self.turns.append(turn)
        self.last_active = datetime.now().isoformat()

    def get_recent_turns(self, n: int = 3) -> List[ConversationTurn]:
        """获取最近N轮对话"""
        return list(self.turns[-n:]) if len(self.turns) > 0 else []

    def get_last_turn(self) -> Optional[ConversationTurn]:
        """获取上一轮对话"""
        return self.turns[-1] if self.turns else None

    def update_context(self, key: str, value: Any):
        """更新上下文信息"""
        self.context[key] = value

    def get_context(self, key: str, default: Any = None) -> Any:
        """获取上下文信息"""
        return self.context.get(key, default)

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "turns": [asdict(t) for t in self.turns],
            "context": self.context
        }


class ConversationManager:
    """对话管理器"""

    def __init__(self, max_sessions: int = 100, max_turns_per_session: int = 50):
        """
        初始化对话管理器

        Args:
            max_sessions: 最大会话数（超过后清理最旧的）
            max_turns_per_session: 每个会话最大轮数（超过后压缩历史）
        """
        self.max_sessions = max_sessions
        self.max_turns_per_session = max_turns_per_session
        self.sessions: Dict[str, Conversation] = {}
        self.session_queue = deque(maxlen=max_sessions)  # 用于LRU清理

    def get_or_create_session(self, session_id: str, user_id: str) -> Conversation:
        """获取或创建会话"""
        if session_id not in self.sessions:
            conv = Conversation(session_id=session_id, user_id=user_id)
            self.sessions[session_id] = conv
            self.session_queue.append(session_id)

            # 清理超出限制的会话
            if len(self.sessions) > self.max_sessions:
                oldest_sid = self.session_queue.popleft()
                if oldest_sid in self.sessions:
                    del self.sessions[oldest_sid]

        return self.sessions[session_id]

    def add_turn(self, session_id: str, user_id: str, turn: ConversationTurn):
        """添加一轮对话"""
        conv = self.get_or_create_session(session_id, user_id)
        conv.add_turn(turn)

        # 压缩历史（保留最近的轮次）
        if len(conv.turns) > self.max_turns_per_session:
            conv.turns = conv.turns[-self.max_turns_per_session:]

    def get_session(self, session_id: str) -> Optional[Conversation]:
        """获取会话"""
        return self.sessions.get(session_id)

    def clear_session(self, session_id: str):
        """清除会话"""
        if session_id in self.sessions:
            del self.sessions[session_id]
            if session_id in self.session_queue:
                self.session_queue.remove(session_id)


def resolve_context_question(question: str, conversation: Conversation) -> str:
    """
    解析上下文追问，补全省略的信息

    Args:
        question: 用户问题
        conversation: 对话会话

    Returns:
        补全后的完整问题
    """
    # 获取上一轮对话
    last_turn = conversation.get_last_turn()
    if not last_turn:
        return question  # 首轮对话，无需补全

    # 检测是否为追问（省略主语、使用代词等）
    follow_up_patterns = [
        "那", "这些", "它们", "他们", "那些",
        "呢", "还有", "另外", "其他",
        "详细", "明细", "具体", "更多"
    ]

    is_follow_up = any(pattern in question for pattern in follow_up_patterns)

    if not is_follow_up:
        return question  # 不是追问，直接返回

    # 补全上下文
    resolved = question

    # 1. 补全主语（如果问题以"那"、"这些"开头）
    if question.startswith(("那", "这些", "它们", "他们", "那些")):
        # 从上一轮提取主语
        last_question = last_turn.resolved_question
        # 简单提取：假设主语在问题开头
        import re
        match = re.search(r'^(查询|查看|统计|搜索|找)(.+?)(的|告警|事件|设备)', last_question)
        if match:
            subject = match.group(2).strip()
            resolved = resolved.replace("那", subject, 1)
            resolved = resolved.replace("这些", subject, 1)
            resolved = resolved.replace("它们", subject, 1)

    # 2. 补全时间范围（如果上一轮有时间限制）
    time_range = conversation.get_context("time_range")
    if time_range and "最近" not in resolved and "时间" not in resolved:
        # 如果当前问题没有时间限制，继承上一轮的时间范围
        resolved = f"{time_range}的{resolved}"

    # 3. 补全筛选条件（如果上一轮有筛选条件）
    filters = conversation.get_context("filters")
    if filters and isinstance(filters, dict):
        # 如果当前问题没有明确筛选条件，继承上一轮的
        for key, value in filters.items():
            if key == "event_type" and "告警" not in resolved and "事件" not in resolved:
                resolved = f"{value}{resolved}"
            elif key == "city_name" and value not in resolved:
                resolved = f"{value}{resolved}"

    return resolved


def extract_context_from_question(question: str, intent: str, filters: Dict) -> Dict[str, Any]:
    """
    从问题中提取上下文信息

    Args:
        question: 用户问题
        intent: 查询意图
        filters: 筛选条件

    Returns:
        上下文信息字典
    """
    context = {}

    # 提取时间范围
    import re
    time_patterns = [
        (r'最近(\d+)天', lambda m: f"最近{m.group(1)}天"),
        (r'最近(\d+)小时', lambda m: f"最近{m.group(1)}小时"),
        (r'(\d{4}年\d{1,2}月)', lambda m: m.group(1)),
        (r'今天', lambda m: "今天"),
        (r'昨天', lambda m: "昨天"),
        (r'本月', lambda m: "本月"),
    ]

    for pattern, extractor in time_patterns:
        match = re.search(pattern, question)
        if match:
            context["time_range"] = extractor(match)
            break

    # 提取筛选条件
    if filters:
        context["filters"] = filters

    # 提取事件类型
    if "event_type" in filters:
        context["event_type"] = filters["event_type"]

    # 提取地点
    if "city_name" in filters:
        context["city"] = filters["city_name"]
    if "county_name" in filters:
        context["county"] = filters["county_name"]
    if "town_name" in filters:
        context["town"] = filters["town_name"]

    return context


# 全局单例
_conversation_manager: Optional[ConversationManager] = None


def init_conversation_manager(max_sessions: int = 100, max_turns_per_session: int = 50):
    """初始化全局对话管理器"""
    global _conversation_manager
    _conversation_manager = ConversationManager(
        max_sessions=max_sessions,
        max_turns_per_session=max_turns_per_session
    )


def get_conversation_manager() -> Optional[ConversationManager]:
    """获取全局对话管理器"""
    return _conversation_manager
