from __future__ import annotations

from app.api.queries import _build_query_response_data
from app.api.queries import _infer_chart_suggestion
from app.services import nl2sql as nl2sql_module


def test_count_sql_parameter_placeholders_ignores_literals_and_comments():
    sql = """
    SELECT *
    FROM ds1_events
    WHERE summary = ?
      AND note = '?'
      AND description = "?"
      -- comment ?
      /* block ? */
      AND extra_json LIKE ?
    """

    assert nl2sql_module._count_sql_parameter_placeholders(sql) == 2


def test_sql_cache_plan_skips_placeholder_mismatch_and_invalidates_cache(monkeypatch):
    class FakeTraceManager:
        def __init__(self):
            self.invalidated = []

        def lookup_sql_cache(self, q_text, table_scope=None, mark_hit=False):
            return {
                "intent": "list",
                "sql": "SELECT * FROM ds1_events WHERE event_type = ?",
                "sql_params": [],
                "question_hash": "bad-cache",
                "question_sample": q_text,
                "hit_count": 1,
            }

        def invalidate_sql_cache(self, question_hash_value: str):
            self.invalidated.append(question_hash_value)

        def mark_sql_cache_hit(self, question_hash_value: str):
            raise AssertionError("placeholder mismatch cache should not be marked as hit")

    fake_manager = FakeTraceManager()

    monkeypatch.setattr("app.services.trace.get_trace_manager", lambda: fake_manager)

    plan = nl2sql_module._try_build_sql_cache_plan(
        question="查询最近20条告警",
        parsed_intent="list",
        candidate_tables=["ds1_events"],
    )

    assert plan is None
    assert fake_manager.invalidated == ["bad-cache"]


def test_build_query_response_data_exposes_semantic_enhance_fields():
    state = {
        "intent": "list",
        "sql": "SELECT * FROM ds1_events LIMIT 20",
        "sql_params": [],
        "sql_result": [{"file_path": "/tmp/a.jpg", "summary": "red vehicle"}],
        "final_answer": {
            "type": "list",
            "value": [{"file_path": "/tmp/a.jpg", "summary": "red vehicle"}],
            "message": "查询结果：返回 1 条记录",
            "semantic_scores": {"a.jpg": 0.91},
            "vector_only_results": [{"file_name": "b.jpg", "hybrid_score": 0.87}],
        },
        "execution_history": [],
        "filters": {"plan_source": "llm", "confidence": 0.88},
        "logs": [],
    }

    data = _build_query_response_data(
        question="查找红色车辆",
        dataset=None,
        trace_id="trace-demo",
        audit_id="audit-demo",
        state=state,
        warnings=[],
    )

    assert data["semantic_scores"] == {"a.jpg": 0.91}
    assert data["vector_only_results"] == [{"file_name": "b.jpg", "hybrid_score": 0.87}]
    assert data["plan_source"] == "llm"
    assert data["confidence"] == 0.88


def test_infer_chart_suggestion_prefers_line_for_time_trend_questions():
    rows = [
        {"alarm_date": "2025-11-16", "count": 3},
        {"alarm_date": "2025-11-17", "count": 7},
        {"alarm_date": "2025-11-18", "count": 5},
    ]
    result_schema = [
        {"name": "alarm_date", "type": "string"},
        {"name": "count", "type": "number"},
    ]

    suggestion = _infer_chart_suggestion(
        question="查询海沧区最近三天告警趋势变化",
        intent="count",
        rows=rows,
        result_schema=result_schema,
    )

    assert suggestion == "line"


def test_build_tower_rule_plan_supports_trend_queries_without_llm():
    plan = nl2sql_module._try_build_tower_rule_plan(
        question="查询海沧区告警趋势变化",
        parsed_intent="list",
        candidate_tables=["ds1_tower_warning_events_cleaned"],
        default_table="ds1_tower_warning_events_cleaned",
    )

    assert plan is not None
    assert plan.intent == "count"
    assert "substr(alarm_time, 1, 10)" in plan.sql
    assert plan.filters.get("chart_suggestion") == "line"


def test_extract_tower_area_does_not_treat_distribution_keywords_as_specific_area():
    town_name, county_name = nl2sql_module._extract_tower_area("统计最近30天各区县告警数量分布")
    assert town_name is None
    assert county_name is None


def test_build_tower_rule_plan_uses_dataset_relative_time_for_recent_days():
    plan = nl2sql_module._try_build_tower_rule_plan(
        question="统计最近30天各区县告警数量分布",
        parsed_intent="count",
        candidate_tables=["ds1_tower_warning_events_cleaned"],
        default_table="ds1_tower_warning_events_cleaned",
    )

    assert plan is not None
    assert "MAX(CAST(alarm_time AS TIMESTAMP)) - INTERVAL '30 days'" in plan.sql
    assert plan.filters.get("chart_suggestion") == "bar"
