"""验证 DuckDB 引擎功能"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[0]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from poc.search.duckdb_engine import get_duckdb_engine
from poc.pipeline.utils import resolve_path, load_yaml

config = load_yaml("poc/config/poc.yaml")
lancedb_dir = resolve_path(config.get("paths", {}).get("lancedb_dir", "poc/data/lancedb"))
engine = get_duckdb_engine(str(lancedb_dir))

passed = 0
failed = 0

def test(name, fn):
    global passed, failed
    try:
        fn()
        print(f"  [OK] {name}")
        passed += 1
    except Exception as e:
        print(f"  [FAIL] {name}: {e}")
        failed += 1

# Test 1: COUNT
def t1():
    r = engine.execute("SELECT COUNT(*) AS cnt FROM events")
    assert r[0]["cnt"] > 0, f"Expected > 0, got {r[0]['cnt']}"
test("COUNT total rows", t1)

# Test 2: GROUP BY
def t2():
    r = engine.execute("SELECT event_type, COUNT(*) AS cnt FROM events GROUP BY event_type ORDER BY cnt DESC LIMIT 5")
    assert len(r) > 0, "No results"
    assert "event_type" in r[0], "Missing event_type column"
test("GROUP BY event_type", t2)

# Test 3: WHERE with param
def t3():
    r = engine.execute("SELECT event_type, alarm_time, town_name FROM events WHERE town_name <> '' ORDER BY alarm_time DESC LIMIT 3")
    assert len(r) > 0, "No results"
test("WHERE filter", t3)

# Test 4: distinct_values
def t4():
    towns = engine.distinct_values("town_name")
    assert len(towns) > 0, "No towns"
test("distinct_values(town_name)", t4)

# Test 5: table_info
def t5():
    info = engine.table_info()
    assert len(info) >= 40, f"Expected >= 40 columns, got {len(info)}"
test("table_info columns", t5)

# Test 6: parameterized query
def t6():
    r = engine.execute("SELECT COUNT(*) AS cnt FROM events WHERE event_type = ?", ["车辆闯入监控告警"])
    assert r[0]["cnt"] >= 0
test("Parameterized query with ?", t6)

# Test 7: schema_meta
def t7():
    from poc.qa.schema_meta import build_schema_prompt
    prompt = build_schema_prompt(str(lancedb_dir))
    assert "event_type" in prompt, "Missing event_type in schema prompt"
    assert len(prompt) > 100, f"Schema prompt too short: {len(prompt)}"
test("schema_meta.build_schema_prompt", t7)

# Test 8: NL2SQL parse_question
def t8():
    from poc.qa.nl2sql import parse_question
    plan = parse_question("查询最近20条车辆闯入告警")
    assert plan.intent == "list"
    assert "LIMIT" in plan.sql
    assert "events" in plan.sql.lower() or "events" in plan.sql
test("NL2SQL parse_question", t8)

# Test 9: execute parsed SQL via DuckDB
def t9():
    from poc.qa.nl2sql import parse_question
    plan = parse_question("按街道统计告警数量")
    r = engine.execute(plan.sql, plan.params)
    assert len(r) > 0, "No results from parsed SQL"
test("Execute parsed SQL via DuckDB", t9)

# Test 10: shared.py helpers
def t10():
    from poc.app.pages.shared import db_stats, lance_count, get_area_hierarchy
    stats = db_stats(None)
    assert stats["events"] > 0, f"events count = {stats['events']}"
    lc = lance_count()
    assert lc > 0, f"lance_count = {lc}"
    hier = get_area_hierarchy("")
    assert "cities" in hier
test("shared.py db_stats/lance_count/get_area_hierarchy", t10)

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed == 0:
    print("[OK] All tests passed!")
else:
    print("[WARN] Some tests failed")
    sys.exit(1)
