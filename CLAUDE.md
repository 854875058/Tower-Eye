# Claude AI 编码规则

本文件记录了在与 Claude AI 协作开发过程中需要遵守的规则和最佳实践。

## 核心规则

### 1. 方案先行原则
**在编写任何代码之前，请先描述你的方案并等待批准。如果需求不明确，在编写任何代码之前务必提出澄清问题。**

- 先理解需求，再动手编码
- 方案需要清晰描述实现思路、涉及的文件、主要步骤
- 等待用户确认后再开始实施

### 2. 任务分解原则
**如果一项任务需要修改超过3个文件，请先停下来，将其分解成更小的任务。**

- 大任务容易出错，小任务更可控
- 每个子任务应该聚焦单一目标
- 分步实施，逐步验证

### 3. 测试驱动原则
**编写代码后，列出可能出现的问题，并建议相应的测试用例来覆盖这些问题。**

- 主动思考边界情况和异常场景
- 提供具体的测试步骤或测试代码
- 确保代码的健壮性

### 4. Bug 修复原则
**当发现 bug 时，首先要编写一个能够重现该 bug 的测试，然后不断修复它，直到测试通过为止。**

- 先重现问题，再修复问题
- 测试用例作为修复的验收标准
- 避免盲目修改代码

### 5. 持续改进原则
**每次我纠正你之后，就在 CLAUDE.md 文件中添加一条新规则，这样就不会再发生这种情况了。**

- 从错误中学习
- 规则会不断完善
- 保持文档更新

### 6. 代码提交原则
**完成代码修改后，必须立即自动提交到 Git，不要等用户提醒。**

- 每次修改代码后立即执行 `git add -A` 和 `git commit`
- 提交信息应清晰描述修改内容和原因
- 提交后执行 `git push` 推送到远程仓库
- 提交完成后，明确说明改动了哪些文件及具体修改内容

---

## 项目特定规则

### 数据库相关
- 在执行检索操作前，务必检查 LanceDB 数据目录是否存在
- 如果数据库不存在，应该给出明确的错误提示和解决方案

### 错误处理
- 所有数据库操作都应该有异常处理
- 错误信息应该清晰、可操作

### Git 仓库管理
- **严禁修改领导的远程仓库**：只能修改和推送到我们自己的仓库（origin）
- 领导的仓库（leader）只用于查看和拉取，不要进行任何推送操作
- 本地有两个 Git 仓库：
  - 外层 `.git`：推送到我们自己的仓库 `origin`
  - `poc/.git`：推送到领导的仓库 `origin`（zhn_test 分支）
- 只在明确得到用户指令时才推送到领导的仓库

### Streamlit 按钮与状态管理（Bug 记录）

**Bug 现象**：智能问答页面的"查看明细"和"您可能还想了解"追问按钮点击后闪退，不会自动执行查询。

**根因（两层）**：
1. **按钮在条件块内部**：按钮渲染在 `if should_execute:` 块内，点击触发 rerun 时条件不成立 → 按钮不渲染 → 点击事件丢失 → 闪退
2. **widget key 修改时机错误**：`st.session_state.question_input` 不能在 `st.text_input(key="question_input")` 渲染**之后**修改，否则抛出 `StreamlitAPIException`

**修复方案**：
1. 查询结果存入 `st.session_state.last_qa_result`，结果渲染移到条件块**外部**
2. 按钮处理器只设 `pending_question` + `auto_execute = True`，**不直接设** `question_input`
3. 在函数顶部（text_input 渲染**之前**）统一将 `pending_question` 同步到 `question_input`

**规则总结**：
- Streamlit 中需要交互的按钮，**禁止**放在一次性条件块内部
- 需要跨 rerun 保留的数据必须存入 `st.session_state`
- **严禁在 widget 渲染后修改其 `st.session_state[widget_key]`**，只能在渲染前设置
- 动态更新 widget 值的正确模式：用中间变量（如 `pending_question`）传递，在 widget 渲染前同步

### Streamlit Widget Key 缓存导致显示错位（Bug 记录）

**Bug 现象**：SQL 编辑器 `st.text_area(key="sql_editor")` 在执行新查询后仍显示上一次查询的 SQL。

**根因**：Streamlit 在同一次 rerun 中 `del st.session_state['sql_editor']` 后又重建同名 widget 时，内部 widget state 缓存不一定被清除，导致 `value=` 参数被忽略。

**修复方案**：使用版本号动态 key：
```python
st.session_state.sql_editor_version = st.session_state.get("sql_editor_version", 0) + 1
st.text_area("SQL", value=new_sql, key=f"sql_editor_v{version}")
```

**规则总结**：
- **需要在 rerun 间强制刷新内容的 widget，使用版本号动态 key**，不要靠 `del + 重建同名 key`
- 格式：`key=f"widget_name_v{counter}"` + 每次更新递增 counter

### NL2SQL "最近N条" vs "最近N天"（Bug 记录）

**Bug 现象**：用户问"查询最近20条车辆闯入告警"，LLM 将"最近20"误解为时间过滤 `date('now', '-20 days')`，数据库无近期数据 → 返回 0 条。

**根因**：DeepSeek LLM 没有区分"最近N条"（LIMIT N）和"最近N天"（时间过滤）的语义差异。

**修复方案**：在 NL2SQL system prompt 中新增明确规则，强调"最近N条"只表示 LIMIT N，绝不添加时间条件。

**规则总结**：
- LLM prompt 中**必须明确区分量词表达式**（"N条/个/件" → LIMIT）和**时间表达式**（"N天/小时/月" → WHERE 时间过滤）
- 任何可能被误解的中文表达，都应该在 prompt 中用正例+反例对比说明

---

*最后更新: 2026-02-10*
