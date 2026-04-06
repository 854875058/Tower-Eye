# Codex AI 编码规则

本文件记录了在与 Codex AI 协作开发过程中需要遵守的规则和最佳实践。

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
**每次我纠正你之后，就在 AGENTS.md 文件中添加一条新规则，这样就不会再发生这种情况了。**

- 从错误中学习
- 规则会不断完善
- 保持文档更新

### 6. 代码提交原则
**完成代码修改后，必须立即自动提交到 Git，不要等用户提醒。**

- 每次修改代码后立即执行 `git add -A` 和 `git commit`
- 提交信息应清晰描述修改内容和原因
- 提交信息默认使用**中文**，并且不能只写一行短句；应至少说明：本次改动解决了什么问题、涉及哪条能力链、改了哪些关键模块、是否完成验证、当前还剩什么边界
- 面向领导、客户或后续复盘场景的提交，提交说明应写成**详细中文提交信息**，允许包含一段较长说明或正文，禁止继续使用过短、过泛、无法复盘的提交内容
- 提交后执行 `git push` 推送到远程仓库
- 提交完成后，明确说明改动了哪些文件及具体修改内容

### 7. 自验收原则
**每完成一个模块、接口或代码修改后，必须自行运行验证，确认功能正常后才算完成。验证不通过则持续修复，直到通过为止。**

- 写完代码不等于完成——必须跑通才算交付
- 验证方式视情况而定：能跑单元测试就跑测试，不能跑测试就用 `python -c` 或脚本做冒烟验证
- 对于语法和导入问题，至少执行 `python -c "import ast; ast.parse(open('文件路径').read())"` 确认无语法错误
- 对于接口/模块修改，构造最小调用验证核心逻辑是否正常返回
- 如果验证发现问题，立即修复并重新验证，循环直到通过
- 不要把未经验证的代码提交给用户

### 8. 架构文档同步原则
**任何影响系统架构的改动（新增功能、修改流程、增删组件、调整数据层等），必须同步更新 `ARCHITECTURE.md`。**

- 新增功能模块 → 更新架构图 + 新增组件说明
- 修改现有流程（如状态机流转） → 更新对应的流程图
- 数据层变更（新增表、换存储引擎等） → 更新数据层描述
- 技术栈变更 → 更新底部技术栈信息
- 每次更新后同步修改"最后更新"日期

---

## 项目特定规则

### 数据库相关
- 在执行检索操作前，务必检查 LanceDB 数据目录是否存在
- 如果数据库不存在，应该给出明确的错误提示和解决方案

### 错误处理
- 所有数据库操作都应该有异常处理
- 错误信息应该清晰、可操作

### Git 仓库管理
- 本项目当前使用**单一本地 Git 仓库**，禁止再假设存在 `poc/.git` 或其他嵌套仓库结构，所有 Git 操作都以仓库根目录 `.git` 为准
- 当前远程仓库约定如下：
  - `origin`：内部 GitLab 仓库，用于团队主同步
  - `github`：个人 GitHub 仓库，用于个人备份、分支协作和对外同步
- **完成代码、文档、配置修改后，必须立即自动提交**，不要等待用户再次提醒；默认执行顺序为：
  - `git add -A`
  - `git commit`
  - 推送到 `github` 个人仓库的开发分支 `Tower-multi-retrieval`
  - 推送到 `origin` 公司 GitLab 仓库的 `master` 分支
- 自动提交不是可选动作；只要本次任务已经形成明确文件改动，并且验证通过，就应立即提交
- 提交信息必须准确反映修改内容，禁止使用空泛提交信息，例如 `update`、`fix bug`、`misc changes`
- 对关键功能迁移、架构调整、能力增强类提交，必须优先使用**详细中文提交说明**，让不了解上下文的人仅通过提交记录也能看懂改动背景、实现内容和验证结果
- 推送规则如下：
  - **本项目后续默认采用双远端同步**
  - `github`：固定推送到 `Tower-multi-retrieval` 开发分支
  - `origin`：固定推送到 `master` 主分支
  - 每次代码、文档、配置有正式改动并验证通过后，必须两个远端都推送，不能只推一个
  - 即使当前本地工作分支是 `Tower-multi-retrieval`，也仍需同步推送到 `origin/master`
  - 新建分支后，首次推送必须显式指定远程并建立 upstream
- **禁止未经用户明确要求就修改远程地址、覆盖历史、强推、删远程分支或改默认分支**
- GitHub 访问如需代理，**只允许配置当前仓库的本地代理**，禁止写入全局 Git 配置；当前项目约定使用：
  - `git config --local http.https://github.com.proxy http://127.0.0.1:7897`
- 如遇凭据失效、网络阻断、远程拒绝等问题，应先保留本地提交并明确说明原因，不要在未确认前反复失败式推送
- 推送前应检查是否误提交大体积样本、临时目录、缓存目录和本地生成文件，避免把不应入库的数据推到远程
- 今后本项目的所有 Git 仓库操作，均以本节规则为准执行

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

### NL2SQL 时间计算错误 — LLM 不知道当前日期（Bug 记录）

**Bug 现象**：用户问"按街道统计最近30天各类告警数量"，LLM 生成的 SQL 中时间条件为 `alarm_time >= '2025-03-28'`，而实际当前日期是 2026-02-11，差了将近一年。

**根因**：NL2SQL 的 system prompt 中没有注入当前日期，DeepSeek LLM 的训练数据截止时间较早，无法推断"现在"是什么时候，导致"最近30天"的计算完全错误。

**修复方案**：在 `_build_nl2sql_system_prompt()` 和 `call_llm_fix_sql()` 的 system prompt 中注入 `datetime.now()` 的当前时间，并明确要求 LLM 基于该时间计算所有相对时间表达式。

**规则总结**：
- **所有涉及时间计算的 LLM prompt，必须注入当前时间**（`datetime.now()`）
- 不能假设 LLM 知道"现在"是什么时候——它的训练数据有截止日期
- 格式示例：`# 当前时间\n2026-02-11 16:30:00\n`

### Windows GBK 终端 Unicode 编码错误（Bug 记录）

**Bug 现象**：`python -m poc.pipeline.embed` 在 Windows 终端下运行时，`Qwen3VLEmbedding.__init__` 中的 `print(f"✓ ...")` 抛出 `UnicodeEncodeError: 'gbk' codec can't encode character '\u2713'`，导致 `ModelManager` 初始化失败，embed 流程中断，LanceDB 为空。

**根因**：Windows 默认终端编码为 GBK，无法编码 Unicode 特殊字符（如 `✓`、`✗`、emoji 等）。`print()` 在写入 stdout 时触发编码错误。

**修复方案**：将所有 Python 文件中 `print()` 里的 Unicode 特殊字符替换为 ASCII 等价物（如 `✓` → `[OK]`）。

**规则总结**：
- **Python 代码中的 `print()` 语句禁止使用非 ASCII 特殊字符**（如 `✓`、`✗`、emoji）
- 使用 ASCII 替代：`[OK]`、`[FAIL]`、`[WARN]` 等
- Shell 脚本（`.sh`）不受此限制（Linux 终端默认 UTF-8）
- 如果必须使用 Unicode 字符，需要用 `try/except UnicodeEncodeError` 包裹或设置 `PYTHONIOENCODING=utf-8`

### LanceDB 检查方式（Bug 记录）

**Bug 现象**：搜索页面检查 `(lancedb_dir / "embeddings.lance").exists()` 在不同 LanceDB 版本下可能失败（目录结构不同）。

**修复方案**：改用 LanceDB API 检查：`lancedb.connect(dir).list_tables()` 判断 `"embeddings"` 表是否存在。

**规则总结**：
- **检查 LanceDB 表是否存在时，使用 API 而非文件系统路径**
- 不同版本的 LanceDB 内部目录结构可能不同（`.lance` vs 其他格式）

### LanceDB 全量写入 "Table already exists" 错误（Bug 记录）

**Bug 现象**：`embed.py` 全量模式下，`db.create_table("embeddings", data=lance_data)` 抛出 `ValueError: Table 'embeddings' already exists`，即使代码中有 `if table_name in existing_tables: db.drop_table()` 的逻辑。

**根因**：不同版本的 LanceDB 中 `list_tables()` 和 `table_names()` 返回类型不一致——有的返回字符串列表，有的返回 Table 对象列表。`table_name in existing_tables` 做字符串比较时匹配失败，导致 `drop_table` 被跳过。

**修复方案**：全量模式下不依赖 `in` 检查，直接 `try: db.drop_table(name) except: pass`，然后 `create_table`。增量模式用 `_table_exists()` 辅助函数，对列表元素做 `str()` 转换后再比较。

**规则总结**：
- **LanceDB 全量重建表时，用 try/except 无条件 drop，不要依赖 list_tables 的返回值做条件判断**
- `list_tables()` / `table_names()` 的返回类型在不同版本间不稳定，做 `in` 检查前必须 `str()` 转换

### 修改后必须自动重启并验证效果（新增规则）

**背景**：前端页面、后端接口或联调链路相关修改后，如果只改代码不重启运行环境，用户无法立即确认效果，容易出现“代码已改但页面仍是旧版本”的假象。

**规则总结**：
- **凡是涉及前端页面、后端接口、静态资源代理、启动脚本或运行时行为的修改，完成后必须自动重启对应服务或刷新运行环境**
- **重启后必须立即做最小可见验证**：例如访问页面、调用健康检查、触发关键接口、确认最新构建产物已生效
- **不能只告诉用户“已经修改”**，必须确保用户打开页面或接口时能直接看到最新效果
- 如果由于环境限制无法正常重启，也必须明确说明阻塞点，并提供当前实际可访问的替代方式

---

*最后更新: 2026-04-01*
