# 问题修复说明

## 修复的三个问题

### ✅ 问题1：查询追踪统计一直是0

**原因**：
- `logs/` 目录不存在，导致追踪数据库无法创建
- 追踪功能虽然初始化了，但数据没有真正保存

**修复方案**：
1. 已创建 `logs/traces/` 目录
2. 追踪数据库会在首次查询时自动创建

**验证方法**：
```bash
# 查看追踪数据库
sqlite3 data/traces.db "SELECT COUNT(*) FROM query_traces;"

# 查看最近的查询记录
sqlite3 data/traces.db "SELECT question, status, timestamp FROM query_traces ORDER BY timestamp DESC LIMIT 5;"
```

---

### ✅ 问题2：图片显示"不存在"

**原因**：
- 数据库中存储的是相对路径（如 `sample1.png`）
- 实际图片在 `data/warning_img/` 目录下
- 代码直接使用数据库路径，没有尝试 `data/warning_img/` 目录

**修复方案**：
修改 `display_media()` 函数，尝试多个可能的路径：

```python
# 对于图片
possible_paths = [
    Path(img_url),                      # 原始路径
    Path("data/warning_img") / Path(img_url).name,  # data/warning_img/文件名
    Path("data/warning_img") / img_url       # data/warning_img/相对路径
]

# 对于视频
possible_paths = [
    Path(video_url),
    Path("data/warning_file") / Path(video_url).name,
    Path("data/warning_file") / video_url
]
```

**支持的路径格式**：
- ✅ 绝对路径：`/path/to/data/warning_img/sample1.png`
- ✅ 相对路径：`sample1.png`（自动在 `data/warning_img/` 中查找）
- ✅ 子目录：`subdir/sample1.png`（自动在 `data/warning_img/` 中查找）
- ✅ HTTP URL：`https://example.com/image.jpg`

---

### ✅ 问题3：快速选择按钮不能用

**原因**：
- 使用了 `st.rerun()` 导致页面刷新，但输入框的值没有更新
- Streamlit 的状态管理问题

**修复方案**：
使用 `st.session_state` 保存选中的问题：

```python
# 初始化 session_state
if 'selected_question' not in st.session_state:
    st.session_state.selected_question = question

# 按钮点击时更新 session_state
if cols[i].button(f"📝 {q[:10]}...", key=f"preset_{i}"):
    st.session_state.selected_question = q
    question = q

# 输入框使用 session_state 的值
default_question = st.session_state.get('selected_question', "近7天车辆闯入监控告警有多少条？")
question = st.text_input(
    "请输入您的问题",
    value=default_question,
    key="question_input"
)
```

**现在的行为**：
1. 点击快速选择按钮
2. 问题自动填充到输入框
3. 可以直接点击"执行查询"

---

## 测试验证

### 1. 测试图片显示

```bash
# 确保图片在正确的目录
ls data/warning_img/ | head -5

# 启动应用
streamlit run poc/app/app_v2.py

# 在"多模态检索"页面搜索，应该能看到图片
```

### 2. 测试追踪统计

```bash
# 在"智能问答"页面执行几次查询

# 然后进入"系统监控"页面，应该能看到：
# - 总查询数 > 0
# - 成功数 > 0
# - 平均耗时 > 0
# - 最近查询记录列表
```

### 3. 测试快速选择

```bash
# 在"智能问答"页面
# 1. 点击任意快速选择按钮
# 2. 输入框应该自动填充问题
# 3. 点击"执行查询"应该正常工作
```

---

## 额外优化

### 图片路径优先级

系统会按以下顺序尝试查找图片：

1. **数据库原始路径**（如果是绝对路径）
2. **data/warning_img/文件名**（最常用）
3. **data/warning_img/相对路径**（支持子目录）
4. **HTTP URL**（远程图片）

### 追踪数据持久化

追踪数据保存在两个地方：

1. **SQLite 数据库**：`data/traces.db`
   - 结构化存储
   - 支持 SQL 查询
   - 用于统计分析

2. **JSONL 日志文件**：`logs/traces/trace_YYYYMMDD.jsonl`
   - 每日一个文件
   - 完整的 JSON 数据
   - 方便导出和备份

---

## 启动命令

```bash
# 启动修复后的应用
streamlit run poc/app/app_v2.py

# 如果要替换原应用
mv poc/app/app.py poc/app/app_old.py
mv poc/app/app_v2.py poc/app/app.py
streamlit run poc/app/app.py
```

---

## 常见问题

### Q: 图片还是显示不出来？

**A**: 检查以下几点：
1. 图片文件确实在 `data/warning_img/` 目录下
2. 文件名大小写是否匹配（Linux 区分大小写）
3. 文件权限是否正确

```bash
# 检查图片文件
ls -lh data/warning_img/sample1.png

# 检查数据库中的文件名
sqlite3 data/metadata.db "SELECT file_name FROM assets LIMIT 5;"
```

### Q: 追踪统计还是0？

**A**: 确保：
1. `logs/` 目录已创建
2. 执行过至少一次查询
3. 追踪功能已启用（`enable_trace=True`）

```bash
# 手动创建目录
mkdir -p logs/traces

# 检查追踪数据库
sqlite3 data/traces.db "SELECT * FROM query_traces;"
```

### Q: 快速选择还是不工作？

**A**: 清除 Streamlit 缓存：
```bash
# 方法1：在浏览器中按 C 键清除缓存
# 方法2：重启应用
# 方法3：删除缓存目录
rm -rf ~/.streamlit/cache
```

### Q: `manage.py start` / `restart` 卡在 Ray，或者换端口后还是起不来？

**A**: 先不要继续怀疑端口，优先判断是不是本地 `Ray` 集群脏了。典型日志包括：

- `global_state_accessor.cc:505`
- `Failed to connect to the default Ray cluster address at 127.0.0.1:6379`
- 切到 `8097` 等其他端口后仍然启动失败

推荐处理顺序：

```bash
ray stop
python bin/manage.py stop
python bin/manage.py start
```

如果确实要换端口：

```powershell
$env:APP_PORT='8097'
python bin/manage.py start
```

注意：先清理 `Ray`，再换端口；不要在脏 `Ray` 状态下反复切端口。

### Q: 为什么明明问过同一个问题，`sql_cache` 还是没有复用？

**A**: 先看日志是不是下面这句：

```text
[sql_cache] SKIP - placeholder count (0) != param count (1)
```

这不表示“没有缓存”，而是“命中了旧坏模板”。典型场景是缓存里的 SQL 被历史版本写成了 `LIMIT 10` 常量，而当前规则引擎仍然会带 `params=[10]`，于是缓存模板不能直接复用。

另外，命令行模式默认不会自动启用 trace / cache。需要显式使用：

```bash
python -m poc.qa.agent_query --enable-trace --question "统计各设备触发告警次数最多的TOP10"
```

否则你会看到查询能跑通，但 `data/traces.db` 和 `sql_cache` 都不会自动积累。

---

## 修改的文件

1. `poc/app/app_v2.py`
   - 修复图片路径查找逻辑
   - 修复快速选择按钮
   - 优化媒体文件显示

2. `poc/qa/trace.py`
   - 修复 SQL 语法错误（已在之前修复）

3. 新创建的目录
   - `logs/`
   - `logs/traces/`

---

## 下一步建议

1. **数据入库时保存完整路径**
   - 修改 `ingest.py`，将 `data/warning_img/文件名` 作为完整路径保存
   - 这样就不需要在显示时猜测路径

2. **统一媒体文件管理**
   - 考虑将所有媒体文件移到统一目录
   - 或者在配置文件中指定媒体根目录

3. **追踪数据定期清理**
   - 添加定时任务清理旧的追踪记录
   - 避免数据库过大

---

修复完成！现在所有功能都应该正常工作了。🎉
