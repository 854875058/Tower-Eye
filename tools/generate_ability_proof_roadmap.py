from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side


XLSX_OUTPUT = Path("能力证明版实施优先级清单.xlsx")
MD_OUTPUT = Path("能力证明版实施优先级清单.md")


ROWS = [
    {
        "序号": 1,
        "优先级": "P0",
        "能力主题": "多模态证据检索引擎",
        "目标能力": "围绕业务问题输出跨文档、图片、视频、日志的证据链，而不是只返回若干检索结果。",
        "为什么重要": "这是最直观的 AI 能力入口，也是区别于普通知识库和普通 RAG 的关键能力。",
        "核心功能": "统一接入文档/表格/图片/视频/日志；文本搜文本、文本搜图、图搜图、图搜视频；跨模态证据拼接；证据卡片与来源追溯。",
        "暂不优先做": "先不追求所有格式全覆盖，也不先做复杂权限编排；先聚焦 2~3 个高价值场景。",
        "预期演示效果": "输入一个运营问题，系统返回相关文档片段、现场图片、视频片段、历史记录和关联说明。",
        "关键技术挑战": "跨模态向量空间、统一召回排序、证据关联、业务语义理解。",
        "建议输出物": "一个可演示的检索界面 + 证据链视图 + 3 个示例问题。",
        "建议工期（人天）": 8.0,
        "阶段": "Phase 1",
    },
    {
        "序号": 2,
        "优先级": "P0",
        "能力主题": "数据运营分析智能体",
        "目标能力": "从简单问答升级为“指标问数 + 异常诊断 + 根因分析 + 运营建议”的业务智能体。",
        "为什么重要": "客户最容易感知，也是规范书里直接写到的能力；必须证明我们不只是做聊天框。",
        "核心功能": "自然语言交互、多轮对话、上下文记忆、问题澄清、工具调用、异常分析、建议生成、角色化视图。",
        "暂不优先做": "先不做复杂组织权限和推送中心，先把核心分析链打通。",
        "预期演示效果": "输入“某区域换电周转率为什么下降”，智能体给出指标拆解、根因判断、证据引用和调度建议。",
        "关键技术挑战": "业务语义层、Agent 工具编排、检索增强、建议生成的可解释性。",
        "建议输出物": "运营分析智能体演示页 + 典型问答脚本 + 业务分析模板。",
        "建议工期（人天）": 9.0,
        "阶段": "Phase 1",
    },
    {
        "序号": 3,
        "优先级": "P0",
        "能力主题": "自动标注与训练数据工厂",
        "目标能力": "把原始多模态数据自动处理成可训练、可复核、可迭代的训练数据资产。",
        "为什么重要": "很多厂商会做推理 Demo，但做不了训练数据生产闭环；这是长期研发能力的证明。",
        "核心功能": "文档/图片/视频自动标注，人工复核，标签版本管理，训练集/验证集/测试集自动生成，质量评估。",
        "暂不优先做": "先不做完整审核工作流与复杂协作权限，先做单团队闭环。",
        "预期演示效果": "上传多模态数据后自动产出标签、摘要、样本集，并支持人工修正后再次沉淀。",
        "关键技术挑战": "弱监督标注、半自动复核、标签治理、训练样本版本化。",
        "建议输出物": "自动标注流水线 + 样本集生成面板 + 标注质量概览。",
        "建议工期（人天）": 8.5,
        "阶段": "Phase 1",
    },
    {
        "序号": 4,
        "优先级": "P0",
        "能力主题": "跨域协同决策样机",
        "目标能力": "将能源、智联等不同业务域的数据和模型协同起来，输出最优资源配置或风险处置方案。",
        "为什么重要": "这是规范书里最有技术含量、也最能体现前沿能力的部分，普通厂商通常做不到。",
        "核心功能": "跨域数据融合、协同规则编排、风险预测、资源调度、求解器、多目标约束建模、结果可解释。",
        "暂不优先做": "先不做 35 个模型全量覆盖，只做 1~2 个标杆跨域场景。",
        "预期演示效果": "展示“项目交付风险 + 资源分配 + 成本约束”一体化决策过程和结果。",
        "关键技术挑战": "跨域特征对齐、规则引擎、优化求解、协同结果可视化。",
        "建议输出物": "一个跨域协同决策 Demo 场景 + 决策过程可视化。",
        "建议工期（人天）": 10.0,
        "阶段": "Phase 1",
    },
    {
        "序号": 5,
        "优先级": "P0",
        "能力主题": "统一模型适配与推理服务",
        "目标能力": "把不同技术路线、不同业务场景的模型统一封装成标准输入输出协议和推理能力。",
        "为什么重要": "没有统一适配层，就只能是几个零散模型，不能证明平台能力。",
        "核心功能": "统一模型接口、标准化入参出参、模型注册、调用协议、服务编排、跨模型兼容。",
        "暂不优先做": "先不把所有模型类型一次接满，先覆盖 3~5 个代表模型。",
        "预期演示效果": "多个不同场景模型通过一个统一接口被智能体和协同决策引擎调用。",
        "关键技术挑战": "模型标准契约、跨技术栈封装、统一推理调度。",
        "建议输出物": "模型注册与调用控制台 + 统一推理 API。",
        "建议工期（人天）": 6.0,
        "阶段": "Phase 1",
    },
    {
        "序号": 6,
        "优先级": "P1",
        "能力主题": "模型全生命周期平台",
        "目标能力": "覆盖训练、评估、上线、灰度、版本回滚、监控告警。",
        "为什么重要": "规范书明确要求 35 种模型的研发、上线和版本管理，必须有平台化能力支撑。",
        "核心功能": "训练任务、评估看板、上线/下线、灰度发布、版本回溯、告警。",
        "暂不优先做": "先不做非常完整的 AutoML 和复杂实验管理。",
        "预期演示效果": "单个模型可以查看版本、指标、发布状态，并支持切换和回滚。",
        "关键技术挑战": "训练资源调度、评估体系、版本治理、灰度策略。",
        "建议输出物": "模型平台控制台 + 版本管理与发布流程。",
        "建议工期（人天）": 7.0,
        "阶段": "Phase 2",
    },
    {
        "序号": 7,
        "优先级": "P1",
        "能力主题": "元数据、血缘与质量治理",
        "目标能力": "形成可追溯的数据底层，包括元数据标准、字段字典、任务血缘、质量评分。",
        "为什么重要": "这是平台可信度的关键，也是规范书反复强调的数据底座能力。",
        "核心功能": "元数据目录、字段字典、任务级/资源级血缘、质量规则、质量评分、异常修复建议。",
        "暂不优先做": "先不从字段级血缘做满，先落任务级和资源级。",
        "预期演示效果": "展示数据从接入、清洗、标注、建模到输出的追踪链路和质量评分。",
        "关键技术挑战": "多模态血缘建模、元数据采集、质量规则体系。",
        "建议输出物": "元数据台账 + 血缘图谱样机 + 质量治理看板。",
        "建议工期（人天）": 7.5,
        "阶段": "Phase 2",
    },
    {
        "序号": 8,
        "优先级": "P1",
        "能力主题": "数据产品化与合规输出",
        "目标能力": "把内部数据能力包装成标准化数据产品，支持展示、订阅、交付和合规审查。",
        "为什么重要": "规范书不是只要内部分析，还要求数据资产化和市场化输出能力。",
        "核心功能": "数据产品目录、产品订阅、交付记录、产品接口、合规审查、脱敏和审计。",
        "暂不优先做": "先不做完整商务计费体系，先把展示/订阅/交付闭环打通。",
        "预期演示效果": "展示一个标准化数据产品从定义、订阅到交付的全过程。",
        "关键技术挑战": "产品抽象、合规规则、对外接口标准、权限审计。",
        "建议输出物": "数据产品目录页 + 合规校验样机 + 产品订阅流程。",
        "建议工期（人天）": 6.5,
        "阶段": "Phase 2",
    },
    {
        "序号": 9,
        "优先级": "P1",
        "能力主题": "企业级交付适配能力",
        "目标能力": "明确从当前原型到铁塔正式交付架构的落地路线，适配其技术栈、认证、流程和监控要求。",
        "为什么重要": "如果不说明交付适配路径，客户会认为我们只有 PoC 能力，没有落地能力。",
        "核心功能": "Spring Cloud 平台层适配方案、Python AI 服务层拆分、4A、流程引擎、IT 网管、日志审计、CI/CD 对接。",
        "暂不优先做": "先不做全部正式接入实现，但方案和关键适配点必须给出。",
        "预期演示效果": "技术方案文档里明确“能力验证架构”与“正式交付架构”的映射图。",
        "关键技术挑战": "异构技术栈协同、企业规范适配、生产准备度要求。",
        "建议输出物": "交付架构蓝图 + 对接清单 + 非功能能力矩阵。",
        "建议工期（人天）": 5.0,
        "阶段": "Phase 2",
    },
    {
        "序号": 10,
        "优先级": "P2",
        "能力主题": "报表与价值展示体系",
        "目标能力": "沉淀标准报表、价值分析报表、监管输出报表，形成稳定的可交付展示层。",
        "为什么重要": "这是最终交付的重要组成，但不是最强能力证明点。",
        "核心功能": "标准报表模板、自动生成、指标校验、价值分析报表、监管视图。",
        "暂不优先做": "先不追求一次做满 100 个报表，先选 10 个标杆。",
        "预期演示效果": "从模型和智能体结果自动生成标准报表。",
        "关键技术挑战": "指标口径统一、模板引擎、自动更新。",
        "建议输出物": "标杆报表模板集 + 自动生成样例。",
        "建议工期（人天）": 4.0,
        "阶段": "Phase 3",
    },
]


THIN = Side(style="thin", color="D9D9D9")
ALL_BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
SUB_FILL = PatternFill("solid", fgColor="D9EAF7")
P0_FILL = PatternFill("solid", fgColor="FCE4D6")
P1_FILL = PatternFill("solid", fgColor="FFF2CC")
P2_FILL = PatternFill("solid", fgColor="E2F0D9")


def style_header(ws, row=1):
    for cell in ws[row]:
        cell.font = Font(name="Microsoft YaHei", bold=True, color="FFFFFF", size=10)
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = ALL_BORDER


def style_body(ws):
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font = Font(name="Microsoft YaHei", size=10)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = ALL_BORDER


def build_overview(ws):
    ws.title = "总览"
    ws["A1"] = "能力证明版实施优先级清单"
    ws["A1"].font = Font(name="Microsoft YaHei", size=16, bold=True)
    ws["A3"] = "核心判断"
    ws["A3"].font = Font(name="Microsoft YaHei", size=12, bold=True)

    lines = [
        "1. 当前阶段的目标不是把所有规范功能做完，而是优先做出最能证明“平台级智能化能力”的样机与架构闭环。",
        "2. 第一优先级不是大量基础 CRUD，而是多模态证据检索、运营分析智能体、自动标注训练数据工厂、跨域协同决策样机。",
        "3. 要向客户证明的不只是‘能做一个 Demo’，而是‘具备持续研发、平台化扩展、企业级交付适配能力’。",
        "4. 当前技术原型可作为 AI 能力验证底座，对外交付需要补 Spring Cloud 平台层 + Python AI 服务层的双层架构映射。",
        "5. 建议用 2~3 个强场景 Demo 串成闭环，而不是分散堆很多页面功能。",
    ]
    for idx, line in enumerate(lines, start=4):
        ws[f"A{idx}"] = line

    ws["A11"] = "推荐 Demo 场景"
    ws["A11"].font = Font(name="Microsoft YaHei", size=12, bold=True)
    demos = [
        "场景 A：能源资源动态调度优化",
        "场景 B：智联项目交付延迟风险预警",
        "场景 C：异常诊断与运营建议智能体",
    ]
    for idx, line in enumerate(demos, start=12):
        ws[f"A{idx}"] = line

    ws["F3"] = "统计摘要"
    ws["F3"].font = Font(name="Microsoft YaHei", size=12, bold=True)
    metrics = [
        ("能力主题数", '=COUNTA(\'优先级清单\'!C2:C200)'),
        ("P0 数量", '=COUNTIF(\'优先级清单\'!B:B,"P0")'),
        ("P1 数量", '=COUNTIF(\'优先级清单\'!B:B,"P1")'),
        ("P2 数量", '=COUNTIF(\'优先级清单\'!B:B,"P2")'),
        ("总工时", '=SUM(\'优先级清单\'!K:K)'),
        ("P0 工时", '=SUMIF(\'优先级清单\'!B:B,"P0",\'优先级清单\'!K:K)'),
        ("P1 工时", '=SUMIF(\'优先级清单\'!B:B,"P1",\'优先级清单\'!K:K)'),
        ("P2 工时", '=SUMIF(\'优先级清单\'!B:B,"P2",\'优先级清单\'!K:K)'),
    ]
    for idx, (label, formula) in enumerate(metrics, start=4):
        ws[f"F{idx}"] = label
        ws[f"G{idx}"] = formula
        ws[f"F{idx}"].font = Font(name="Microsoft YaHei", size=10, bold=True)

    ws["F14"] = "阶段建议"
    ws["F14"].font = Font(name="Microsoft YaHei", size=12, bold=True)
    phase_lines = [
        "Phase 1：做能力证明样机",
        "Phase 2：做平台化增强",
        "Phase 3：做企业级交付与产品化",
    ]
    for idx, line in enumerate(phase_lines, start=15):
        ws[f"F{idx}"] = line

    ws.column_dimensions["A"].width = 78
    ws.column_dimensions["F"].width = 18
    ws.column_dimensions["G"].width = 16
    ws.sheet_view.zoomScale = 95
    for row in ws.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.font = Font(name="Microsoft YaHei", size=10)


def build_priority_sheet(ws):
    headers = [
        "序号",
        "优先级",
        "能力主题",
        "目标能力",
        "为什么重要",
        "核心功能",
        "暂不优先做",
        "预期演示效果",
        "关键技术挑战",
        "建议输出物",
        "建议工期（人天）",
        "阶段",
    ]
    ws.title = "优先级清单"
    ws.append(headers)
    for row in ROWS:
        ws.append([row[h] for h in headers])

    style_header(ws)
    style_body(ws)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    ws.sheet_view.zoomScale = 90
    widths = {
        "A": 6,
        "B": 8,
        "C": 20,
        "D": 22,
        "E": 20,
        "F": 26,
        "G": 18,
        "H": 24,
        "I": 22,
        "J": 18,
        "K": 12,
        "L": 12,
    }
    for col, width in widths.items():
        ws.column_dimensions[col].width = width
    for row_idx in range(2, ws.max_row + 1):
        prio = ws[f"B{row_idx}"].value
        ws[f"K{row_idx}"].number_format = "0.0"
        if prio == "P0":
            fill = P0_FILL
        elif prio == "P1":
            fill = P1_FILL
        else:
            fill = P2_FILL
        ws[f"B{row_idx}"].fill = fill
        ws[f"C{row_idx}"].fill = fill


def build_stage_sheet(ws):
    headers = ["阶段", "能力主题", "建议动作", "输出物", "工时（人天）", "说明"]
    ws.title = "阶段路线"
    ws.append(headers)

    for row in ROWS:
        ws.append(
            [
                row["阶段"],
                row["能力主题"],
                row["核心功能"],
                row["建议输出物"],
                row["建议工期（人天）"],
                row["为什么重要"],
            ]
        )

    style_header(ws)
    style_body(ws)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    ws.sheet_view.zoomScale = 90
    for col, width in zip(("A", "B", "C", "D", "E", "F"), (12, 20, 34, 22, 12, 24)):
        ws.column_dimensions[col].width = width
    for row_idx in range(2, ws.max_row + 1):
        ws[f"E{row_idx}"].number_format = "0.0"


def build_matrix_sheet(ws):
    headers = ["能力主题", "当前项目可复用基础", "能力差距", "下一步动作", "优先级"]
    ws.title = "现状对照"
    ws.append(headers)

    for row in ROWS:
        if row["序号"] <= 5:
            current = "现有项目已具备部分基础，可作为 POC 底座。"
        elif row["序号"] in {6, 7, 8}:
            current = "现有项目只有原型级支撑，尚未平台化。"
        else:
            current = "现有项目几乎未覆盖，需要方案和架构补齐。"

        if row["序号"] == 1:
            gap = "当前有检索原型，但还不是跨模态证据链。"
        elif row["序号"] == 2:
            gap = "当前有问答原型，但不是运营分析智能体。"
        elif row["序号"] == 3:
            gap = "当前有标注基础，但没有训练数据工厂闭环。"
        elif row["序号"] == 4:
            gap = "当前缺跨域协同决策和求解器能力。"
        elif row["序号"] == 5:
            gap = "当前缺统一模型适配与推理服务层。"
        elif row["序号"] == 9:
            gap = "当前技术栈与目标交付技术栈存在明显差异。"
        else:
            gap = "当前仅有局部原型或尚未覆盖。"

        ws.append([row["能力主题"], current, gap, row["建议输出物"], row["优先级"]])

    style_header(ws)
    style_body(ws)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    ws.sheet_view.zoomScale = 90
    for col, width in zip(("A", "B", "C", "D", "E"), (20, 24, 24, 22, 8)):
        ws.column_dimensions[col].width = width


def generate_markdown():
    lines = [
        "# 能力证明版实施优先级清单",
        "",
        "## 核心判断",
        "- 当前目标不是把规范书所有功能一次性做完，而是优先做出最能证明平台级智能化能力的样机。",
        "- 最该优先证明的能力不是上传下载，而是：多模态证据检索、运营分析智能体、自动标注训练数据工厂、跨域协同决策。",
        "- 要对外说明：当前系统是 AI 能力验证底座，交付版将演进为 Spring Cloud 平台层 + Python AI 服务层的双层架构。",
        "",
        "## 优先级清单",
        "",
        "| 序号 | 优先级 | 能力主题 | 目标能力 | 建议工期（人天） | 阶段 |",
        "| --- | --- | --- | --- | ---: | --- |",
    ]
    for row in ROWS:
        lines.append(
            f"| {row['序号']} | {row['优先级']} | {row['能力主题']} | {row['目标能力']} | {row['建议工期（人天）']:.1f} | {row['阶段']} |"
        )

    lines.extend(
        [
            "",
            "## 最推荐先做的 4 件事",
            "1. 多模态证据检索引擎",
            "2. 数据运营分析智能体",
            "3. 自动标注与训练数据工厂",
            "4. 跨域协同决策样机",
            "",
            "## 推荐 Demo 场景",
            "- 场景 A：能源资源动态调度优化",
            "- 场景 B：智联项目交付延迟风险预警",
            "- 场景 C：异常诊断与运营建议智能体",
        ]
    )
    MD_OUTPUT.write_text("\n".join(lines), encoding="utf-8")


def main():
    wb = Workbook()
    build_overview(wb.active)
    build_priority_sheet(wb.create_sheet())
    build_stage_sheet(wb.create_sheet())
    build_matrix_sheet(wb.create_sheet())
    wb.save(XLSX_OUTPUT)
    generate_markdown()
    print(f"generated_xlsx={XLSX_OUTPUT.resolve()}")
    print(f"generated_md={MD_OUTPUT.resolve()}")


if __name__ == "__main__":
    main()
