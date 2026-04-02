<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, nextTick, computed, watch, reactive } from 'vue'
import { useUserStore } from '@/stores/user'
import { queryApi, datasetApi, dataSourceApi, historyApi } from '@/api'
import type { QueryContextTurn, QueryResponse, QuerySessionContext, Dataset, SchemaColumn } from '@/api/types'
import { ElMessage } from 'element-plus'
import { ArrowDown, ArrowRight, Loading, UploadFilled } from '@element-plus/icons-vue'
import * as echarts from 'echarts'

const userStore = useUserStore()

// 类型定义
interface Message {
  role: string
  content: string
  data?: QueryResponse
  thinkingLines?: string[]
  progressCollapsed?: boolean
  sqlCollapsed?: boolean
  streamedAnswer?: string
  answerStreaming?: boolean
}

interface TableItem {
  id: number
  name: string
  label: string
  checked: boolean
}

// 状态
const loading = ref(false)
const question = ref('')
const messages = ref<Message[]>([])
const datasets = ref<Dataset[]>([])
const selectedDataset = ref<Dataset | null>(null)
const tableSearch = ref('')
const selectedTables = ref<TableItem[]>([])
let datasetPollTimer: ReturnType<typeof setInterval> | null = null

// 数据表（初始为空，选择数据集后加载）
const allTables = ref<TableItem[]>([])

// 快捷示例
const quickExamples = [
  '统计最近30天各区县告警数量分布',
  '查询最近20条车辆闯入监控告警',
  '分析近期哪些设备触发告警次数最多',
  '查找与“车辆闯入”相关的图片和视频片段',
]

// 过滤后的数据表
const filteredTables = computed(() => {
  if (!tableSearch.value) return allTables.value
  const search = tableSearch.value.toLowerCase()
  return allTables.value.filter(
    t => t.name.toLowerCase().includes(search) || t.label.toLowerCase().includes(search)
  )
})

// 已选数据表
const selectedTableLabels = computed(() => {
  return allTables.value.filter(t => t.checked).map(t => t.label)
})

const selectedDatasetWarning = computed(() => {
  if (!selectedDataset.value) return null
  if (selectedDataset.value.processing_status === 'processing' || selectedDataset.value.processing_status === 'pending') {
    return {
      type: 'warning',
      title: '当前数据集中的图片或视频仍在处理中，检索结果可能不完整',
    }
  }
  if (selectedDataset.value.processing_status === 'failed') {
    return {
      type: 'error',
      title: selectedDataset.value.error_message || '当前数据集中的部分图片或视频处理失败',
    }
  }
  return null
})

type ResultViewMode = 'detail' | 'chart'

const resultViewModeMap = ref<Record<number, ResultViewMode>>({})
const messageChartInstances = new Map<number, echarts.ECharts>()
const answerStreamTimers = new Map<number, number>()

const intentLabelMap: Record<string, string> = {
  chat: '普通问答',
  search: '内容检索',
  count: '统计分析',
  list: '明细查询',
  analysis: '分析查询',
  compare: '对比分析',
  trend: '趋势分析',
  skip: '无需查询',
}

const stepLabelMap: Record<string, string> = {
  parse_question: '问题理解',
  validate_sql: '查询检查',
  execute_sql: '数据查询',
  format_answer: '结果整理',
  semantic_enhance: '结果优化',
  vector_search: '内容检索',
  fix_sql: '自动修正',
  intent_node: '意图识别',
  semantic_node: '语义理解',
  dispatcher_node: '意图分流',
  sql_gen_node: '生成查询语句',
  sql_validate_node: '查询检查',
  sql_execute_node: '执行查询',
  format_node: '结果整理',
}

const SHORT_SESSION_CONTEXT_LIMIT = 3
const SHORT_SESSION_SCHEMA_LIMIT = 8

const getIntentLabel = (intent?: string) => {
  if (!intent) return '查询需求'
  return intentLabelMap[intent] || intent
}

const getFriendlyStepStartText = (step?: string) => {
  const stepText = stepLabelMap[step || ''] || '处理中'
  if (!step) return `${stepText}中`

  const startTextMap: Record<string, string> = {
    parse_question: '正在解析问题并匹配可用数据表',
    validate_sql: '正在校验查询条件与执行安全性',
    execute_sql: '正在执行查询并获取结果',
    format_answer: '正在整理答案与结果摘要',
    semantic_enhance: '正在补充语义匹配与相关推荐',
    vector_search: '正在检索相关图片、视频和文本证据',
    fix_sql: '检测到异常，正在重新规划查询语句',
    intent_node: '正在识别你的查询类型',
    semantic_node: '正在理解问题语义与检索意图',
    dispatcher_node: '正在选择合适的处理路径',
    sql_gen_node: '正在生成可执行的查询语句',
    sql_validate_node: '正在校验查询语句',
    sql_execute_node: '正在执行查询语句',
    format_node: '正在整理答案与展示结果',
  }
  return `[${stepText}] ${startTextMap[step] || '正在处理'}`
}

const getFriendlyStepEndLines = (step?: string, outputs?: any): string[] => {
  if (!step || !outputs) return []

  const lines: string[] = []
  const stepText = stepLabelMap[step] || step
  const errorMessage = outputs?.error_message

  if (step === 'parse_question' || step === 'intent_node') {
    if (outputs?.intent) {
      lines.push(`[${stepText}] 已识别查询类型：${getIntentLabel(outputs.intent)}`)
    } else {
      lines.push(`[${stepText}] 已完成`)
    }
    if (outputs?.sql) {
      lines.push('[查询准备] 已生成可执行查询条件')
    }
    const planSource = outputs?.filters?.plan_source
    if (planSource === 'sql_cache') {
      lines.push('[查询规划] 已命中 SQL 缓存，复用历史查询模板')
    } else if (planSource === 'verified_query') {
      lines.push('[查询规划] 已命中可信模板，直接复用验证过的查询方案')
    } else if (planSource === 'llm') {
      lines.push('[查询规划] 已通过模型语义判定生成查询方案')
    } else if (planSource === 'rule') {
      lines.push('[查询规划] 已通过规则策略生成查询方案')
    }
    const selectedTable = outputs?.filters?.selected_table
    if (selectedTable) {
      lines.push(`[数据范围] 当前使用表：${selectedTable}`)
    }
    if (outputs?.filters?.context_applied) {
      lines.push('[会话上下文] 已结合最近一轮查询理解当前追问')
    }
    return lines
  }

  if (step === 'validate_sql' || step === 'sql_validate_node') {
    if (errorMessage) {
      lines.push('[查询检查] 校验未通过，系统将尝试自动修正')
    } else {
      lines.push('[查询检查] 校验通过，可进入执行阶段')
    }
    return lines
  }

  if (step === 'execute_sql' || step === 'sql_execute_node' || step === 'vector_search') {
    const resultRows = outputs?.result?.rows || outputs?.rows || outputs?.sql_result || []
    const rowCount = outputs?.row_count || (Array.isArray(resultRows) ? resultRows.length : 0)
    if (errorMessage) {
      lines.push('[数据查询] 当前步骤执行异常，系统将继续尝试修复')
    } else {
      lines.push(`[数据查询] 已完成，共返回 ${rowCount} 条结果`)
      if (outputs?.chart_suggestion) {
        lines.push(`[图表建议] 推荐使用 ${String(outputs.chart_suggestion).toUpperCase()} 展示`)
      }
    }
    return lines
  }

  if (step === 'semantic_enhance') {
    const matched = outputs?.semantic_scores ? Object.keys(outputs.semantic_scores).length : 0
    const recommended = Array.isArray(outputs?.vector_only_results) ? outputs.vector_only_results.length : 0
    lines.push(`[结果优化] 已完成，匹配 ${matched} 条，补充 ${recommended} 条`)
    return lines
  }

  if (step === 'fix_sql') {
    lines.push('[自动修正] 已修正查询条件，继续执行')
    return lines
  }

  if (step === 'format_answer' || step === 'format_node') {
    const finalMessage = outputs?.final_answer?.message || outputs?.final_answer?.answer_text || outputs?.answer_text
    if (finalMessage) {
      lines.push(`[结果整理] ${finalMessage}`)
    } else {
      lines.push('[结果整理] 已完成')
    }
    return lines
  }

  lines.push(`[${stepText}] 已完成`)
  return lines
}

const toNumber = (value: unknown): number | null => {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim() !== '') {
    const normalized = value.replace(/,/g, '')
    const num = Number(normalized)
    if (Number.isFinite(num)) return num
  }
  return null
}

const isLikelyRankingView = (data?: QueryResponse | null): boolean => {
  if (!data || data.intent === 'search') return false
  const rows = data.result_rows || []
  if (rows.length < 2) return false

  const sample = rows.slice(0, 10)
  const keys = Object.keys(sample[0] || {})
  if (keys.length < 2) return false

  let numericKeyCount = 0
  for (const key of keys) {
    let valid = 0
    for (const row of sample) {
      if (toNumber((row as any)[key]) !== null) valid += 1
    }
    if (valid >= Math.ceil(sample.length * 0.6)) {
      numericKeyCount += 1
    }
  }

  return numericKeyCount >= 1
}

const getRankingMeta = (data?: QueryResponse | null) => {
  if (!data) return null
  const rows = data.result_rows || []
  if (!rows.length) return null

  const sample = rows.slice(0, 10)
  const keys = Object.keys(sample[0] || {})
  if (!keys.length) return null

  const numericKeys = keys.filter((key) => {
    let valid = 0
    for (const row of sample) {
      if (toNumber((row as any)[key]) !== null) valid += 1
    }
    return valid >= Math.ceil(sample.length * 0.6)
  })
  if (!numericKeys.length) return null

  const schemaNames = (data.result_schema || []).map((s) => s.name)
  const preferredMetric = schemaNames.find((name) => {
    const lower = name.toLowerCase()
    return (
      lower.includes('数') ||
      lower.includes('count') ||
      lower.includes('收入') ||
      lower.includes('金额') ||
      lower.includes('fee') ||
      lower.includes('值')
    ) && numericKeys.includes(name)
  })
  const metricKey = preferredMetric || numericKeys[0]

  const textKeys = keys.filter((k) => !numericKeys.includes(k))
  const preferredDimension = schemaNames.find((name) => {
    const lower = name.toLowerCase()
    return (
      lower.includes('城市') ||
      lower.includes('地区') ||
      lower.includes('渠道') ||
      lower.includes('名称') ||
      lower.includes('name')
    ) && textKeys.includes(name)
  })
  const dimensionKey = preferredDimension || textKeys[0] || keys[0]

  return {
    dimensionKey,
    metricKey,
    dimensionLabel: dimensionKey || '维度',
    metricLabel: metricKey || '指标值',
  }
}

const getRankingRows = (data?: QueryResponse | null) => {
  const rows = data?.result_rows || []
  const meta = getRankingMeta(data)
  if (!meta) return []

  const normalized = rows
    .map((row, index) => {
      const value = toNumber((row as any)[meta.metricKey]) ?? 0
      return {
        rank: index + 1,
        name: String((row as any)[meta.dimensionKey] ?? '-'),
        value,
      }
    })
    .sort((a, b) => b.value - a.value)
    .slice(0, 10)
    .map((row, index) => ({ ...row, rank: index + 1 }))

  const maxValue = normalized[0]?.value || 0
  return normalized.map((row) => ({
    ...row,
    ratio: maxValue > 0 ? Math.max(0.08, row.value / maxValue) : 0.08,
  }))
}

const formatMetricValue = (value: number) => {
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(value)
}

const extractCountValue = (data?: QueryResponse | null): number | null => {
  if (!data || data.intent !== 'count') return null

  const rows = data.result_rows || []
  if (rows.length > 0) {
    const firstRow = rows[0] as Record<string, unknown>
    for (const key of Object.keys(firstRow)) {
      const val = toNumber(firstRow[key])
      if (val !== null) return val
    }
  }

  const text = data.answer || ''
  const match = text.match(/共\s*([\d,]+(?:\.\d+)?)\s*条/)
  if (match?.[1]) {
    const parsed = toNumber(match[1])
    if (parsed !== null) return parsed
  }

  return null
}

const getSuccessSummaryText = (data?: QueryResponse | null): string => {
  if (!data) return '0 条结果'
  if (data.intent === 'count') {
    const countValue = extractCountValue(data)
    if (countValue !== null) {
      return `统计值 ${formatMetricValue(countValue)}`
    }
    return '统计已完成'
  }
  return `${data.row_count || 0} 条结果`
}

const getPlanSourceLabel = (source?: string): string => {
  if (!source) return 'unknown'
  const map: Record<string, string> = {
    rule: '规则引擎',
    llm: 'LLM',
    sql_cache: 'SQL缓存',
    verified_query: '可信模板',
    manual_sql: '手工SQL',
    reject: '拒绝执行',
  }
  return map[source] || source
}

const formatConfidence = (value?: number): string => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '-'
  const clamped = Math.max(0, Math.min(1, value))
  return `${Math.round(clamped * 100)}%`
}

const summarizeTurnAnswer = (data?: QueryResponse | null): string => {
  if (!data) return ''
  const answerText = (data.answer || '').trim()
  if (answerText) return answerText.slice(0, 220)
  if (data.status === 'success') return getSuccessSummaryText(data).slice(0, 220)
  return (data.error || '').trim().slice(0, 220)
}

const buildShortSessionContext = (datasetId?: number, currentTableNames: string[] = []): QuerySessionContext | undefined => {
  const recentTurns: QueryContextTurn[] = []

  for (let idx = messages.value.length - 1; idx >= 1 && recentTurns.length < SHORT_SESSION_CONTEXT_LIMIT; idx -= 1) {
    const assistantMsg = messages.value[idx]
    if (assistantMsg.role !== 'assistant' || !assistantMsg.data) continue

    const data = assistantMsg.data
    if (!data || data.intent === 'chat') continue

    const userMsg = messages.value[idx - 1]
    if (!userMsg || userMsg.role !== 'user') continue

    const turnDatasetId = data.dataset_id
    if (typeof datasetId === 'number') {
      if (typeof turnDatasetId !== 'number' || turnDatasetId !== datasetId) continue
    } else if (typeof turnDatasetId === 'number') {
      continue
    }

    if (data.status === 'error' && !data.clarification_needed) continue

    const turnQuestion = (data.question || userMsg.content || '').trim()
    if (!turnQuestion) continue

    const turn: QueryContextTurn = {
      question: turnQuestion,
      intent: data.intent,
      answer: summarizeTurnAnswer(data),
      sql: data.sql || undefined,
      row_count: data.row_count,
      result_schema: (data.result_schema || []).slice(0, SHORT_SESSION_SCHEMA_LIMIT),
      table_names: Array.isArray(data.table_names) && data.table_names.length > 0 ? data.table_names : undefined,
      dataset_id: turnDatasetId,
      status: data.status,
      plan_source: data.plan_source,
    }
    recentTurns.push(turn)
  }

  if (recentTurns.length === 0) return undefined

  recentTurns.reverse()
  return {
    recent_turns: recentTurns,
    current_dataset_id: datasetId,
    current_table_names: currentTableNames.length > 0 ? currentTableNames : undefined,
  }
}

const clearCurrentSession = () => {
  if (loading.value) {
    ElMessage.warning('当前查询仍在执行，请稍后再清空会话')
    return
  }

  messages.value = []
  question.value = ''
  resultViewModeMap.value = {}
  messageChartInstances.forEach((chart) => chart.dispose())
  messageChartInstances.clear()
  ElMessage.success('已清空当前会话上下文')
}

const applyClarificationOption = (option: string, data?: QueryResponse | null) => {
  const baseQuestion = data?.question || ''
  question.value = baseQuestion ? `${baseQuestion}，请基于表 ${option}` : `请基于表 ${option} 查询`
}

const getEvidenceSourceTables = (data?: QueryResponse | null): string[] => {
  const tables = data?.evidence?.source_tables
  if (!Array.isArray(tables)) return []
  return tables.filter((item): item is string => typeof item === 'string' && item.trim() !== '')
}

const getResultViewMode = (idx: number): ResultViewMode => {
  return resultViewModeMap.value[idx] || 'detail'
}

const getChartDomId = (idx: number) => `query-result-chart-${idx}`

const getChartFieldMeta = (data?: QueryResponse | null) => {
  if (!data) return null
  const rows = data.result_rows || []
  if (!rows.length) return null

  const sample = rows.slice(0, 20)
  const keys = Object.keys(sample[0] || {})
  if (!keys.length) return null

  const numericKeys = keys.filter((key) => {
    let valid = 0
    for (const row of sample) {
      if (toNumber((row as any)[key]) !== null) valid += 1
    }
    return valid >= Math.ceil(sample.length * 0.6)
  })
  if (!numericKeys.length) return null

  const schemaNames = (data.result_schema || []).map((s) => s.name)
  const preferredMetric = schemaNames.find((name) => {
    const lower = name.toLowerCase()
    return (
      lower.includes('数') ||
      lower.includes('count') ||
      lower.includes('收入') ||
      lower.includes('金额') ||
      lower.includes('fee') ||
      lower.includes('值')
    ) && numericKeys.includes(name)
  })
  const metricKey = preferredMetric || numericKeys[0]
  const candidateDimensionKeys = keys.filter((key) => key !== metricKey)

  const preferredDimension = schemaNames.find((name) => {
    const lower = name.toLowerCase()
    return (
      lower.includes('城市') ||
      lower.includes('地区') ||
      lower.includes('渠道') ||
      lower.includes('名称') ||
      lower.includes('name')
    ) && candidateDimensionKeys.includes(name)
  })

  const textDimension = candidateDimensionKeys.find((key) => {
    let stringCount = 0
    for (const row of sample) {
      const value = (row as any)[key]
      if (typeof value === 'string' && value.trim() !== '' && toNumber(value) === null) {
        stringCount += 1
      }
    }
    return stringCount >= Math.ceil(sample.length * 0.4)
  })

  const timeDimension = schemaNames.find((name) => {
    const lower = name.toLowerCase()
    if (
      lower.includes('time') ||
      lower.includes('date') ||
      lower.includes('day') ||
      lower.includes('month') ||
      lower.includes('week') ||
      lower.includes('hour') ||
      lower.includes('alarm_time') ||
      lower.includes('created_at')
    ) {
      return candidateDimensionKeys.includes(name)
    }
    return (
      candidateDimensionKeys.includes(name) &&
      (name.includes('时间') || name.includes('日期') || name.includes('按天') || name.includes('按月') || name.includes('按周'))
    )
  })

  const dimensionKey = timeDimension || preferredDimension || textDimension || candidateDimensionKeys[0] || metricKey

  return {
    dimensionKey,
    metricKey,
    metricLabel: metricKey || '数值',
  }
}

const canRenderChart = (data?: QueryResponse | null): boolean => {
  if (!data || data.intent === 'search') return false
  if (isLikelyRankingView(data)) return true
  return !!getChartFieldMeta(data)
}

const getChartSuggestionType = (data?: QueryResponse | null): 'bar' | 'line' | 'pie' => {
  const suggestion = String(data?.chart_suggestion || '').toLowerCase()
  if (suggestion.includes('pie')) return 'pie'
  if (suggestion.includes('line')) return 'line'
  return 'bar'
}

const shouldAutoOpenChart = (data?: QueryResponse | null) => {
  if (!data || !canRenderChart(data)) return false
  if (data.intent === 'search' || data.status !== 'success') return false
  const chartType = getChartSuggestionType(data)
  if (chartType === 'line' || chartType === 'pie') return true
  return data.intent === 'count' && (data.row_count || 0) > 1
}

const buildChartOption = (data?: QueryResponse | null): echarts.EChartsOption | null => {
  if (!data) return null
  const rows = data.result_rows || []
  const fieldMeta = getChartFieldMeta(data)
  if (!rows.length || !fieldMeta) return null

  const slicedRows = rows.slice(0, 10)
  const chartData = slicedRows.map((row, index) => {
    const rawName = (row as any)[fieldMeta.dimensionKey]
    const fallbackName = slicedRows.length === 1 ? '统计值' : `第${index + 1}项`
    const name =
      fieldMeta.dimensionKey === fieldMeta.metricKey
        ? fallbackName
        : String(rawName ?? '').trim() || fallbackName
    const value = toNumber((row as any)[fieldMeta.metricKey]) ?? 0
    return { name, value }
  })

  const chartType = getChartSuggestionType(data)
  if (chartType === 'pie') {
    return {
      tooltip: { trigger: 'item' },
      legend: { bottom: 0, left: 'center' },
      series: [
        {
          name: fieldMeta.metricLabel,
          type: 'pie',
          radius: ['40%', '68%'],
          data: chartData,
          avoidLabelOverlap: true,
          itemStyle: { borderRadius: 8, borderColor: '#fff', borderWidth: 2 },
        },
      ],
    }
  }

  const xData = chartData.map((item) => item.name)
  const yData = chartData.map((item) => item.value)

  return {
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: xData, axisLabel: { interval: 0 } },
    yAxis: { type: 'value' },
    series: [
      {
        type: chartType,
        data: yData,
        smooth: chartType === 'line',
        itemStyle: {
          color: '#2f66f6',
        },
      },
    ],
    grid: { left: 40, right: 24, top: 20, bottom: 40 },
  }
}

const disposeMessageChart = (idx: number) => {
  const existing = messageChartInstances.get(idx)
  if (existing) {
    existing.dispose()
    messageChartInstances.delete(idx)
  }
}

const renderMessageChart = (idx: number, data?: QueryResponse | null) => {
  if (!data || !canRenderChart(data) || isLikelyRankingView(data)) return
  const option = buildChartOption(data)
  if (!option) return

  const chartEl = document.getElementById(getChartDomId(idx))
  if (!chartEl) return

  let chart = messageChartInstances.get(idx)
  if (!chart) {
    chart = echarts.init(chartEl)
    messageChartInstances.set(idx, chart)
  } else if (chart.getDom() !== chartEl) {
    chart.dispose()
    chart = echarts.init(chartEl)
    messageChartInstances.set(idx, chart)
  }

  chart.setOption(option, true)
  chart.resize()
}

const handleResultViewModeChange = (
  idx: number,
  mode: string | number | boolean | undefined,
  data?: QueryResponse | null
) => {
  const nextMode: ResultViewMode = mode === 'chart' ? 'chart' : 'detail'
  if (nextMode === 'chart' && !canRenderChart(data)) {
    ElMessage.warning('当前结果暂不支持图表展示')
    resultViewModeMap.value[idx] = 'detail'
    return
  }

  resultViewModeMap.value[idx] = nextMode
  if (nextMode === 'detail') {
    disposeMessageChart(idx)
    return
  }

  nextTick(() => {
    renderMessageChart(idx, data)
  })
}

const resizeAllCharts = () => {
  messageChartInstances.forEach((chart) => chart.resize())
}

// 根据日志内容返回颜色 - 类似 tieta-multi 风格
const getLogColor = (line: string): string => {
  if (line.includes('成功') || line.includes('success') || line.toLowerCase().includes('success')) {
    return '#4ade80' // 绿色
  }
  if (line.includes('失败') || line.includes('error') || line.includes('Error')) {
    return '#f87171' // 红色
  }
  if (line.startsWith('[') && line.includes(']')) {
    return '#60a5fa' // 蓝色
  }
  if (line.startsWith('===')) {
    return '#6b7280' // 灰色
  }
  return '#d1d5db' // 浅灰色
}

// 加载数据集
const loadDatasets = async () => {
  if (userStore.currentWorkspace) {
    try {
      const res = await datasetApi.list(userStore.currentWorkspace.id)
      datasets.value = res.data.filter((d: Dataset) => d.status !== 'deprecated')
      if (datasets.value.length > 0 && !selectedDataset.value) {
        selectedDataset.value = datasets.value[0]
        // 加载第一个数据集的表结构
        await handleDatasetChange(datasets.value[0])
      } else if (selectedDataset.value) {
        const latestSelected = datasets.value.find((item) => item.id === selectedDataset.value?.id) || null
        if (latestSelected) {
          const prevSourceIds = JSON.stringify(selectedDataset.value.data_source_ids || [selectedDataset.value.data_source_id].filter(Boolean))
          const nextSourceIds = JSON.stringify(latestSelected.data_source_ids || [latestSelected.data_source_id].filter(Boolean))
          selectedDataset.value = latestSelected
          if (allTables.value.length === 0 || prevSourceIds !== nextSourceIds) {
            await handleDatasetChange(latestSelected)
          }
        }
      }
      syncDatasetPolling()
    } catch (e) {
      console.error('加载数据集失败', e)
    }
  }
}

onMounted(loadDatasets)
onMounted(() => {
  window.addEventListener('resize', resizeAllCharts)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeAllCharts)
  messageChartInstances.forEach((chart) => chart.dispose())
  messageChartInstances.clear()
  answerStreamTimers.forEach((timer) => clearTimeout(timer))
  answerStreamTimers.clear()
  if (datasetPollTimer) {
    clearInterval(datasetPollTimer)
    datasetPollTimer = null
  }
})

// 监听工作空间变化
watch(() => userStore.currentWorkspace, loadDatasets)

const syncDatasetPolling = () => {
  const hasPending = datasets.value.some((item) => ['pending', 'processing'].includes(item.processing_status))
  if (hasPending && !datasetPollTimer) {
    datasetPollTimer = setInterval(() => loadDatasets(), 5000)
    return
  }
  if (!hasPending && datasetPollTimer) {
    clearInterval(datasetPollTimer)
    datasetPollTimer = null
  }
}

// 切换数据集
const handleDatasetChange = async (dataset: Dataset) => {
  if (!dataset) return

  selectedDataset.value = dataset
  // 切换数据集时清空已选数据表
  allTables.value.forEach(t => t.checked = false)
  selectedTables.value = []

  // 获取数据源 IDs（支持多个数据源）
  const dataSourceIds = dataset.data_source_ids || (dataset.data_source_id ? [dataset.data_source_id] : [])

  console.log('数据集:', dataset.name, '数据源 IDs:', dataSourceIds)

  if (dataSourceIds.length > 0) {
    try {
      // 获取所有数据源的表结构
      const allSchemas: SchemaColumn[] = []

      for (const dsId of dataSourceIds) {
        try {
          console.log('获取数据源', dsId, '的 schema')
          const schemaRes = await dataSourceApi.getSchema(dsId)
          console.log('schema 数据:', schemaRes.data)
          allSchemas.push(...schemaRes.data)
        } catch (e) {
          console.warn(`获取数据源 ${dsId} 的 schema 失败:`, e)
        }
      }

      // 按表名分组
      const tableMap = new Map<string, SchemaColumn[]>()
      allSchemas.forEach(col => {
        if (!tableMap.has(col.table_name)) {
          tableMap.set(col.table_name, [])
        }
        tableMap.get(col.table_name)!.push(col)
      })

      console.log('表列表:', Array.from(tableMap.keys()))

      // 转换为表格列表
      allTables.value = Array.from(tableMap.entries()).map(([tableName], index) => ({
        id: index + 1,
        name: tableName,
        label: tableName,
        checked: false,
      }))
    } catch (e) {
      ElMessage.error('获取数据表失败')
      console.error(e)
    }
  } else {
    console.log('该数据集没有关联的数据源')
  }
}

const getDatasetProcessingTagType = (status?: Dataset['processing_status']) => {
  if (status === 'ready') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'processing') return 'warning'
  return 'info'
}

const getDatasetProcessingText = (dataset?: Dataset | null) => {
  if (!dataset) return ''
  if (dataset.processing_status === 'ready') return dataset.media_count > 0 ? '可检索' : '已就绪'
  if (dataset.processing_status === 'failed') return '处理失败'
  if (dataset.processing_status === 'processing') return '处理中'
  return '待处理'
}

const getSearchPreview = (row: Record<string, any>) => row.preview_url || row.preview_frame || ''

const formatSearchExtra = (row: Record<string, any>) => {
  const extra = row.extra || {}
  return extra.caption_text || extra.asr_text || extra.ocr_text || '-'
}

const formatSearchTimeRange = (row: Record<string, any>) => {
  if (typeof row.start_sec !== 'number' || typeof row.end_sec !== 'number') return '-'
  return `${row.start_sec.toFixed(1)}s - ${row.end_sec.toFixed(1)}s`
}

const formatSearchScore = (row: Record<string, any>) => {
  if (typeof row.score === 'number') return row.score.toFixed(3)
  if (typeof row.hybrid_score === 'number') return row.hybrid_score.toFixed(3)
  if (typeof row._distance === 'number') return (1 / (1 + row._distance)).toFixed(3)
  return '-'
}

const DETAIL_PRIORITY_FIELDS: Array<{ key: string; label: string }> = [
  { key: 'event_id', label: '事件ID' },
  { key: 'event_type', label: '事件类型' },
  { key: 'alarm_level', label: '告警等级' },
  { key: 'alarm_time', label: '告警时间' },
  { key: 'address', label: '地址' },
  { key: 'province_name', label: '省份' },
  { key: 'city_name', label: '城市' },
  { key: 'county_name', label: '区县' },
  { key: 'town_name', label: '街道' },
  { key: 'device_name', label: '设备名称' },
  { key: 'device_code', label: '设备编码' },
  { key: 'channel_name', label: '通道名称' },
  { key: 'algorithm_name', label: '算法名称' },
  { key: 'order_status', label: '工单状态' },
  { key: 'confidence_level', label: '置信度' },
  { key: 'confidence_level_max', label: '最大置信度' },
  { key: 'summary', label: '摘要' },
  { key: 'description', label: '描述' },
]

const splitMediaPaths = (value?: unknown) => {
  if (typeof value !== 'string') return []
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

const isVideoFile = (value: string) => /\.(mp4|mov|avi|mkv|m4v|webm)$/i.test(value)

const buildWarningImageUrl = (value: string) => {
  const normalized = value.replace(/\\/g, '/')
  const fileName = normalized.split('/').pop() || normalized
  return `/tower-warning-img/${fileName}`
}

const buildWarningVideoUrl = (value: string) => {
  const normalized = value.replace(/\\/g, '/')
  const fileName = normalized.split('/').pop() || normalized
  return `/tower-warning-video/${fileName}`
}

const getListRowImageCandidates = (row: Record<string, any>) => {
  const paths = [
    ...splitMediaPaths(row.img_src_path),
    ...splitMediaPaths(row.file_path).filter((item) => !isVideoFile(item)),
    ...splitMediaPaths(row.img_icon_path),
  ]
  return Array.from(new Set(paths)).map((item) => buildWarningImageUrl(item))
}

const getListRowVideoCandidates = (row: Record<string, any>) => {
  const paths = [
    ...splitMediaPaths(row.video_path),
    ...splitMediaPaths(row.file_path).filter((item) => isVideoFile(item)),
  ]
  return Array.from(new Set(paths)).map((item) => buildWarningVideoUrl(item))
}

const hasListMedia = (data?: QueryResponse | null) => {
  const rows = data?.result_rows || []
  return rows.some((row) => getListRowImageCandidates(row).length > 0 || getListRowVideoCandidates(row).length > 0)
}

const getListPreviewItems = (data?: QueryResponse | null) => {
  const rows = data?.result_rows || []
  return rows.slice(0, 9).map((row, index) => ({
    key: `${row.event_id || row.asset_id || index}`,
    title: `${row.event_type || '告警事件'} | ${String(row.alarm_time || '').slice(0, 19)}`,
    image: getListRowImageCandidates(row)[0] || '',
    video: getListRowVideoCandidates(row)[0] || '',
  }))
}

const parseExtraJson = (row: Record<string, any>) => {
  const raw = row.extra_json
  if (!raw || typeof raw !== 'string') return null
  try {
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed : null
  } catch {
    return null
  }
}

const getDetailFieldRows = (row: Record<string, any>) => {
  const used = new Set<string>()
  const fields: Array<{ label: string; value: string }> = []

  for (const item of DETAIL_PRIORITY_FIELDS) {
    const value = row[item.key]
    if (value === null || value === undefined || String(value).trim() === '') continue
    used.add(item.key)
    fields.push({ label: item.label, value: String(value) })
  }

  const extra = parseExtraJson(row)
  if (extra && typeof extra === 'object') {
    for (const [key, value] of Object.entries(extra)) {
      if (used.has(key)) continue
      if (value === null || value === undefined || String(value).trim() === '') continue
      fields.push({ label: key, value: String(value) })
      if (fields.length >= 28) break
    }
  }

  return fields
}

const getDetailTitle = (row: Record<string, any>, index: number, data?: QueryResponse | null) => {
  const base = `第 ${index + 1} 条 - ${row.event_type || '告警事件'} | ${String(row.alarm_time || '').slice(0, 19)}`
  const scores = data?.semantic_scores || {}
  const filePath = row.file_path || row.img_src_path || ''
  const fileName = typeof filePath === 'string' ? filePath.replace(/\\/g, '/').split('/').pop() || '' : ''
  const score = fileName ? scores[fileName] : undefined
  return score ? `${base} [语义 ${(score * 100).toFixed(0)}%]` : base
}

const getSemanticMatchedCount = (data?: QueryResponse | null) => {
  if (!data?.semantic_scores) return 0
  return Object.keys(data.semantic_scores).length
}

const getVectorRecommendations = (data?: QueryResponse | null) => {
  return Array.isArray(data?.vector_only_results) ? data.vector_only_results : []
}

const getRecommendationTitle = (row: Record<string, any>) => {
  return row.file_name || row.file_path || row.asset_id || row.image_id || row.video_id || '相关结果'
}

const buildFollowUpSuggestions = (data?: QueryResponse | null) => {
  if (!data || data.status !== 'success') return []

  if (data.intent === 'search') {
    return [
      '查找与当前结果相似的图片和视频片段',
      '统计这些相关告警的区县分布',
      '查询最近20条相关告警明细',
    ]
  }

  if (data.intent === 'count') {
    const rows = data.result_rows || []
    const firstRow = rows[0] as Record<string, any> | undefined
    const keys = firstRow ? Object.keys(firstRow) : []
    const dimensionKey = keys.find((key) => typeof firstRow?.[key] === 'string' && key !== '日期')
    const dimensionValue = dimensionKey && firstRow ? String(firstRow[dimensionKey] || '').trim() : ''
    if (dimensionValue) {
      return [
        `查询${dimensionValue}最近20条告警明细`,
        `查询${dimensionValue}告警趋势变化`,
        `统计${dimensionValue}各设备告警数量分布`,
      ]
    }
    return [
      '查询最近20条告警明细',
      '查询各区县告警趋势变化',
      '统计各设备告警数量分布',
    ]
  }

  if (data.intent === 'list') {
    return [
      '统计各区县告警数量分布',
      '查询告警趋势变化',
      '统计各设备告警数量分布',
    ]
  }

  return []
}

const applyFollowUpSuggestion = (suggestion: string) => {
  question.value = suggestion
}

const clearAnswerStreamTimer = (msgIndex: number) => {
  const timer = answerStreamTimers.get(msgIndex)
  if (timer) {
    clearTimeout(timer)
    answerStreamTimers.delete(msgIndex)
  }
}

const streamAnswerToMessage = (msgIndex: number, fullText: string) => {
  clearAnswerStreamTimer(msgIndex)
  const msg = messages.value[msgIndex]
  if (!msg) return

  const text = String(fullText || '').trim()
  if (!text) {
    msg.streamedAnswer = ''
    msg.answerStreaming = false
    return
  }

  const chars = Array.from(text)
  const chunkSize = chars.length > 160 ? 4 : chars.length > 80 ? 3 : 2
  let cursor = 0
  msg.streamedAnswer = ''
  msg.answerStreaming = true

  const tick = () => {
    const target = messages.value[msgIndex]
    if (!target) {
      clearAnswerStreamTimer(msgIndex)
      return
    }

    cursor = Math.min(chars.length, cursor + chunkSize)
    target.streamedAnswer = chars.slice(0, cursor).join('')
    if (cursor >= chars.length) {
      target.answerStreaming = false
      answerStreamTimers.delete(msgIndex)
      return
    }

    const timer = window.setTimeout(tick, 22)
    answerStreamTimers.set(msgIndex, timer)
  }

  tick()
}

const toggleProgressCollapse = (msg: Message) => {
  msg.progressCollapsed = !msg.progressCollapsed
}

const toggleSqlCollapse = (msg: Message) => {
  msg.sqlCollapsed = !msg.sqlCollapsed
}

const collapseAssistantCards = (msg?: Message | null) => {
  if (!msg) return
  msg.progressCollapsed = true
  msg.sqlCollapsed = true
}

const getThinkingSummary = (msg?: Message | null) => {
  const lines = msg?.thinkingLines || []
  const ignored = new Set([
    '本轮处理完成，可展开查看详情',
    '处理完成，结果已返回',
    '已完成',
  ])
  for (let i = lines.length - 1; i >= 0; i -= 1) {
    const line = String(lines[i] || '').trim()
    if (!line || ignored.has(line)) continue
    return line
  }
  if (msg?.data?.answer) {
    return String(msg.data.answer).slice(0, 120)
  }
  return '本轮处理已完成，可展开查看详情'
}

const getSqlPreview = (sql?: string) => {
  if (!sql) return ''
  const singleLine = sql.replace(/\s+/g, ' ').trim()
  return singleLine.length > 180 ? `${singleLine.slice(0, 177)}...` : singleLine
}

const validateQueryMediaFile = (file: File) => {
  const isImage = file.type.startsWith('image/') || /\.(png|jpe?g|bmp|webp)$/i.test(file.name)
  const isVideo = file.type.startsWith('video/') || /\.(mp4|mov|avi|mkv|m4v|webm)$/i.test(file.name)

  if (!isImage && !isVideo) {
    ElMessage.error('只支持上传图片或视频文件')
    return false
  }

  const maxMb = isImage ? 50 : 1024
  if (file.size / 1024 / 1024 > maxMb) {
    ElMessage.error(`${isImage ? '图片' : '视频'}大小不能超过 ${maxMb}MB`)
    return false
  }

  return true
}

// 切换数据表选择
const handleTableCheckChange = (table: any) => {
  const idx = selectedTables.value.findIndex(t => t.id === table.id)
  if (table.checked) {
    if (idx === -1) {
      selectedTables.value.push(table)
    }
  } else {
    if (idx !== -1) {
      selectedTables.value.splice(idx, 1)
    }
  }
}

// 清空已选数据表
const clearSelectedTables = () => {
  allTables.value.forEach(t => t.checked = false)
  selectedTables.value = []
}

// 重新执行编辑后的 SQL
const handleRerunSql = async (msgIdx: number, msgData: any) => {
  if (!msgData.sql || !msgData.sql.trim()) {
    ElMessage.warning('SQL 不能为空')
    return
  }

  if (!userStore.currentWorkspace) {
    ElMessage.warning('请先选择工作空间')
    return
  }

  // 使用生成 SQL 时保存的表名和数据集ID，保证一致性
  const tableNamesForRerun = msgData.table_names || selectedTables.value.map(t => t.name)
  const datasetIdForRerun = msgData.dataset_id || selectedDataset.value?.id
  const sqlParamsForRerun = Array.isArray(msgData.sql_params) ? msgData.sql_params : []

  msgData.executing = true

  try {
    const response = await queryApi.executeSql({
      sql: msgData.sql,
      workspace_id: userStore.currentWorkspace.id,
      dataset_id: datasetIdForRerun,
      table_names: tableNamesForRerun,
      sql_params: sqlParamsForRerun,
    })

    if (response.data.status === 'success') {
      // 更新消息数据
      msgData.result_rows = response.data.result_rows || []
      msgData.result_schema = response.data.result_schema || []
      msgData.row_count = response.data.row_count || 0
      msgData.intent = response.data.intent || 'list'
      msgData.status = 'success'
      msgData.error = null
      msgData.answer = response.data.answer
      msgData.chart_suggestion = response.data.chart_suggestion || 'table'
      msgData.trace_id = response.data.trace_id
      msgData.audit_id = response.data.audit_id
      msgData.execution_history = response.data.execution_history || []
      msgData.evidence = response.data.evidence || null
      msgData.semantic_scores = response.data.semantic_scores || {}
      msgData.vector_only_results = response.data.vector_only_results || []
      msgData.plan_source = response.data.plan_source || 'manual_sql'
      msgData.confidence = typeof response.data.confidence === 'number' ? response.data.confidence : 1
      msgData.warnings = response.data.warnings || []
      msgData.clarification_needed = !!response.data.clarification_needed
      msgData.clarification_options = response.data.clarification_options || []
      msgData.table_names = tableNamesForRerun
      msgData.dataset_id = datasetIdForRerun
      msgData.sql_params = Array.isArray(response.data.sql_params) ? response.data.sql_params : sqlParamsForRerun
      messages.value[msgIdx].sqlCollapsed = true

      // 触发响应式更新
      messages.value[msgIdx].data = { ...msgData }
      streamAnswerToMessage(msgIdx, String(msgData.answer || ''))
      messages.value = [...messages.value]

      ElMessage.success('SQL 执行成功')
    } else {
      msgData.status = 'error'
      msgData.error = response.data.error || '执行失败'
      messages.value[msgIdx].data = { ...msgData }
      messages.value = [...messages.value]
      ElMessage.error('SQL 执行失败: ' + (response.data.error || '未知错误'))
    }
  } catch (e: any) {
    console.error('SQL 执行失败:', e)
    msgData.status = 'error'
    msgData.error = e.message || '执行失败'
    messages.value[msgIdx].data = { ...msgData }
    messages.value = [...messages.value]
    ElMessage.error('SQL 执行失败: ' + (e.message || '未知错误'))
  } finally {
    msgData.executing = false
  }
}

const executeStreamQuery = async (userQuestion: string, uploadFile?: File) => {
  console.log('executeStreamQuery called, question:', userQuestion)
  console.log('selectedDataset:', selectedDataset.value)
  console.log('dataset_id:', selectedDataset.value?.id)

  if (!userStore.currentWorkspace) {
    ElMessage.warning('请先选择工作空间')
    return
  }

  const currentQuestion = userQuestion.trim()
  if (!currentQuestion) {
    ElMessage.warning('请输入问题')
    return
  }

  loading.value = true
  const mediaLabel = uploadFile
    ? `（已上传${uploadFile.type.startsWith('image/') || /\.(png|jpe?g|bmp|webp)$/i.test(uploadFile.name) ? '图片' : '视频'}：${uploadFile.name}）`
    : ''

  messages.value.push({
    role: 'user',
    content: `${currentQuestion}${mediaLabel}`,
  })

  const assistantMsg = reactive({
    role: 'assistant',
    content: '',
    data: null as any,
    thinkingLines: [] as string[],
    progressCollapsed: false,
    sqlCollapsed: false,
    streamedAnswer: '',
    answerStreaming: false,
  })
  messages.value.push(assistantMsg)

  let thinkingContent = ''
  let lastThinkingLine = ''
  let currentTraceId = ''
  let currentAuditId = ''
  let finalExecutionHistory: Record<string, any>[] = []
  let finalFilters: Record<string, any> = {}
  let finalSqlFromMeta = ''
  let finalSqlParamsFromMeta: any[] = []
  const selectedTableNames = selectedTables.value.map(t => t.name)
  const sessionContext = buildShortSessionContext(selectedDataset.value?.id, selectedTableNames)

  const updateThinking = (text: string) => {
    const cleanedText = text.replace(/\n+$/, '').trimEnd()
    if (!cleanedText || cleanedText === lastThinkingLine) return

    lastThinkingLine = cleanedText
    thinkingContent += cleanedText + '\n'
    const lastMsg = messages.value[messages.value.length - 1] as any
    if (lastMsg) {
      lastMsg.content = thinkingContent
      if (!lastMsg.thinkingLines) {
        lastMsg.thinkingLines = []
      }
      lastMsg.thinkingLines.push(cleanedText)
    }
  }

  try {
    updateThinking(uploadFile ? '已接收上传内容，正在分析检索目标' : '已接收问题，正在分析查询意图')

    const requestPayload = {
      question: currentQuestion,
      workspace_id: userStore.currentWorkspace.id,
      dataset_id: selectedDataset.value?.id,
      table_names: selectedTableNames.length > 0 ? selectedTableNames : undefined,
      context: sessionContext,
    }

    const response = uploadFile
      ? await queryApi.streamExecuteUpload(requestPayload, uploadFile)
      : await queryApi.streamExecute(requestPayload)

    if (!response.ok) {
      throw new Error(response.statusText)
    }

    const reader = response.body?.getReader()
    const decoder = new TextDecoder()

    if (!reader) {
      throw new Error('无法读取响应')
    }

    let buffer = ''
    let finalData: any = null
    let finalMetaIntent: string | undefined = undefined

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue

        try {
          const data = JSON.parse(line.slice(6))
          console.log('[Query] 事件:', data.type, data.step || '', data.summary?.substring(0, 30))

          if (data.type === 'run_start') {
            updateThinking(uploadFile ? '正在结合上传内容和当前数据集理解检索需求' : '正在结合当前数据集理解你的查询需求')
          } else if (data.type === 'node_start') {
            const startText = getFriendlyStepStartText(data.step)
            if (startText) {
              updateThinking(startText)
            }
          } else if (data.type === 'node_end') {
            if (!data.outputs) {
              continue
            }

            if (data.step === 'format_node' && data.outputs?.final_answer) {
              finalData = data.outputs.final_answer
              console.log('[Query] 收到 format_node 结果:', JSON.stringify(finalData, null, 2))
              if (finalData?.answer_text && !lastThinkingLine.includes(finalData.answer_text)) {
                updateThinking('结果摘要：' + finalData.answer_text)
              }
            } else {
              const endLines = getFriendlyStepEndLines(data.step, data.outputs)
              endLines.forEach(lineText => updateThinking(lineText))
            }
          } else if (data.type === 'node_error') {
            const errMsg = data.error?.message || data.error || ''
            if (errMsg && errMsg !== '执行失败' && !String(lastThinkingLine || '').includes(errMsg)) {
              updateThinking('当前步骤出现问题：' + errMsg)
            }
          } else if (data.type === 'error') {
            const errMsg = data.error?.message || data.error || '处理过程中发生异常'
            updateThinking('当前流程异常终止：' + errMsg)
            loading.value = false

            const lastMsg = messages.value[messages.value.length - 1]
            if (lastMsg) {
              lastMsg.data = reactive<QueryResponse>({
                question: currentQuestion,
                intent: finalMetaIntent || 'list',
                intent_text: getIntentLabel(finalMetaIntent || 'list'),
                sql: finalSqlFromMeta || '',
                sql_params: finalSqlParamsFromMeta,
                result_rows: [],
                result_schema: [],
                chart_suggestion: 'table',
                row_count: 0,
                status: 'error',
                error: errMsg,
                answer: errMsg,
                trace_id: data.trace_id || currentTraceId,
                audit_id: data.audit_id || currentAuditId,
                execution_history: finalExecutionHistory,
                evidence: undefined,
                semantic_scores: {},
                vector_only_results: [],
                plan_source: finalFilters?.plan_source,
                confidence: typeof finalFilters?.confidence === 'number' ? finalFilters.confidence : undefined,
                clarification_needed: false,
                clarification_options: [],
                table_names: selectedTableNames,
                dataset_id: selectedDataset.value?.id,
              })
              collapseAssistantCards(lastMsg)
            }
          } else if (data.type === 'final') {
            if (data.trace_id) {
              currentTraceId = data.trace_id
            }
            if (data.audit_id) {
              currentAuditId = data.audit_id
            }
            if (Array.isArray(data.meta?.execution_history)) {
              finalExecutionHistory = data.meta.execution_history
            }
            if (typeof data.meta?.intent === 'string') {
              finalMetaIntent = data.meta.intent
            }
            if (data.meta?.filters && typeof data.meta.filters === 'object') {
              finalFilters = data.meta.filters
            }
            if (typeof data.meta?.sql === 'string') {
              finalSqlFromMeta = data.meta.sql
            }
            if (Array.isArray(data.meta?.sql_params)) {
              finalSqlParamsFromMeta = data.meta.sql_params
            }

            finalData = data.result || data.outputs || data
            if ((finalData?.answer_text || finalData?.message) && !lastThinkingLine.includes(finalData?.answer_text || finalData?.message)) {
              updateThinking('结果摘要：' + (finalData?.answer_text || finalData?.message))
            }

            if (finalData) {
              const lastMsgIndex = messages.value.length - 1
              const lastMsg = messages.value[lastMsgIndex]
              if (lastMsg) {
                let columns: any[] = []
                let rows: any[] = []

                if (finalData?.value && Array.isArray(finalData.value)) {
                  rows = finalData.value
                  if (rows.length > 0) {
                    columns = Object.keys(rows[0])
                  }
                } else {
                  columns = finalData?.result?.columns || finalData?.columns || []
                  rows = finalData?.result?.rows || finalData?.rows || []
                }

                const rowCount = finalData?.row_count || rows.length
                let resultSchema = columns.map((c: string) => ({ name: c, type: 'string' }))
                if (resultSchema.length === 0 && rows.length > 0) {
                  resultSchema = Object.keys(rows[0]).map(key => ({ name: key, type: 'string' }))
                }
                const statusValue = finalData?.status || 'success'

                let intentValue = finalData?.intent || finalMetaIntent || 'list'
                if (finalData?.type === 'chat') intentValue = 'chat'
                if (finalData?.type === 'search') intentValue = 'search'
                if (finalData?.type === 'count') intentValue = 'count'

                lastMsg.data = reactive<QueryResponse>({
                  question: currentQuestion,
                  intent: intentValue,
                  intent_text: finalData?.intent_text || getIntentLabel(intentValue),
                  sql: finalData?.sql || finalSqlFromMeta || '',
                  sql_params: Array.isArray(finalData?.sql_params) ? finalData.sql_params : finalSqlParamsFromMeta,
                  result_rows: rows,
                  result_schema: resultSchema,
                  chart_suggestion: finalData?.chart_suggestion || (intentValue === 'count' ? 'bar' : 'table'),
                  row_count: rowCount,
                  status: statusValue,
                  error: finalData?.error?.message || finalData?.message,
                  answer: finalData?.message || finalData?.answer_text || '',
                  trace_id: currentTraceId,
                  audit_id: currentAuditId,
                  execution_history: finalExecutionHistory,
                  evidence: finalData?.evidence,
                  semantic_scores: finalData?.semantic_scores || {},
                  vector_only_results: finalData?.vector_only_results || [],
                  plan_source: finalData?.plan_source || finalFilters?.plan_source,
                  confidence: typeof (finalData?.confidence ?? finalFilters?.confidence) === 'number'
                    ? (finalData?.confidence ?? finalFilters?.confidence)
                    : undefined,
                  warnings: finalData?.warnings || [],
                  clarification_needed: !!(finalData?.clarification_needed ?? finalFilters?.needs_clarification),
                  clarification_options: finalData?.clarification_options || finalFilters?.clarification_options || [],
                  table_names: selectedTableNames,
                  dataset_id: selectedDataset.value?.id,
                })
                collapseAssistantCards(lastMsg)
                streamAnswerToMessage(lastMsgIndex, String(lastMsg.data.answer || ''))
                if (shouldAutoOpenChart(lastMsg.data)) {
                  resultViewModeMap.value[lastMsgIndex] = 'chart'
                  nextTick(() => renderMessageChart(lastMsgIndex, lastMsg.data))
                }
              }
            }
          } else if (data.type === 'done') {
            updateThinking('本轮处理完成，可展开查看详情')
            loading.value = false
            if (currentTraceId) {
              const lastMsg = messages.value[messages.value.length - 1]
              const msgData = lastMsg?.data
              collapseAssistantCards(lastMsg)
              try {
                await historyApi.create({
                  workspace_id: userStore.currentWorkspace?.id || 0,
                  dataset_id: selectedDataset.value?.id,
                  question: currentQuestion,
                  normalized_question: currentQuestion,
                  intent: msgData?.intent || 'list',
                  semantic_sql: msgData?.sql || '',
                  executable_sql: msgData?.sql || '',
                  sql_params: Array.isArray(msgData?.sql_params) ? msgData.sql_params : [],
                  result_schema: msgData?.result_schema || [],
                  result_rows: (msgData?.result_rows || []).slice(0, 100),
                  row_count: msgData?.row_count || 0,
                  status: msgData?.status || 'success',
                  error_message: msgData?.error || '',
                  trace_id: currentTraceId,
                  audit_id: currentAuditId,
                })
              } catch (historyError) {
                console.error('[History] 保存历史记录失败:', historyError)
              }
            }
          }
        } catch (e) {
          console.error('Parse error:', e)
        }
      }
    }

    if (finalData) {
      const lastMsg = messages.value[messages.value.length - 1]
      if (lastMsg && !lastMsg.data) {
        let columns: any[] = []
        let rows: any[] = []

        if (finalData?.value && Array.isArray(finalData.value)) {
          rows = finalData.value
          if (rows.length > 0) {
            columns = Object.keys(rows[0])
          }
        } else {
          columns = finalData?.result?.columns || finalData?.columns || []
          rows = finalData?.result?.rows || finalData?.rows || []
        }

        const rowCount = finalData?.result?.row_count || finalData?.row_count || rows.length
        let resultSchema = columns.map((c: string) => ({ name: c, type: 'string' }))
        if (resultSchema.length === 0 && rows.length > 0) {
          resultSchema = Object.keys(rows[0]).map(key => ({ name: key, type: 'string' }))
        }

        const statusValue = finalData?.status || 'success'
        const fallbackIntent = finalData?.intent || finalMetaIntent || finalData?.type || 'list'
        const fallbackData = reactive<QueryResponse>({
          question: currentQuestion,
          intent: fallbackIntent,
          intent_text: finalData?.intent_text || getIntentLabel(fallbackIntent),
          sql: finalData?.sql || finalSqlFromMeta || '',
          sql_params: Array.isArray(finalData?.sql_params) ? finalData.sql_params : finalSqlParamsFromMeta,
          result_rows: rows,
          result_schema: resultSchema,
          chart_suggestion: finalData?.chart_suggestion || (finalData?.type === 'count' ? 'bar' : 'table'),
          row_count: rowCount,
          status: statusValue,
          error: finalData?.error?.message || finalData?.message,
          answer: finalData?.answer_text || finalData?.message || '',
          trace_id: currentTraceId,
          audit_id: currentAuditId,
          execution_history: finalExecutionHistory,
          evidence: finalData?.evidence,
          semantic_scores: finalData?.semantic_scores || {},
          vector_only_results: finalData?.vector_only_results || [],
          plan_source: finalData?.plan_source || finalFilters?.plan_source,
          confidence: typeof (finalData?.confidence ?? finalFilters?.confidence) === 'number'
            ? (finalData?.confidence ?? finalFilters?.confidence)
            : undefined,
          warnings: finalData?.warnings || [],
          clarification_needed: !!(finalData?.clarification_needed ?? finalFilters?.needs_clarification),
          clarification_options: finalData?.clarification_options || finalFilters?.clarification_options || [],
          table_names: selectedTableNames,
          dataset_id: selectedDataset.value?.id,
        })
        lastMsg.data = fallbackData
        collapseAssistantCards(lastMsg)
        streamAnswerToMessage(messages.value.length - 1, String(fallbackData.answer || ''))
        if (shouldAutoOpenChart(fallbackData)) {
          resultViewModeMap.value[messages.value.length - 1] = 'chart'
          nextTick(() => renderMessageChart(messages.value.length - 1, fallbackData))
        }
        messages.value = [...messages.value]
      }
    }
  } catch (e: any) {
    console.error('Query error:', e)
    updateThinking('[错误] ' + (e.message || '查询失败') + '\n')
    ElMessage.error(e.message || '查询失败')
    const lastMsg = messages.value[messages.value.length - 1]
    if (lastMsg) {
      lastMsg.content = '查询失败'
      lastMsg.data = {
        question: currentQuestion,
        status: 'error',
        row_count: 0,
        error: e.message || '查询失败',
        trace_id: currentTraceId,
        audit_id: currentAuditId,
        table_names: selectedTableNames,
        dataset_id: selectedDataset.value?.id,
        semantic_scores: {},
        vector_only_results: [],
      } as QueryResponse
      collapseAssistantCards(lastMsg)
    }
    if (currentTraceId) {
      try {
        await historyApi.create({
          workspace_id: userStore.currentWorkspace?.id || 0,
          dataset_id: selectedDataset.value?.id,
          question: currentQuestion,
          normalized_question: currentQuestion,
          intent: 'list',
          row_count: 0,
          status: 'error',
          error_message: e.message || '查询失败',
          trace_id: currentTraceId,
          audit_id: currentAuditId,
        })
      } catch (historyError) {
        console.error('[History] 保存失败记录失败:', historyError)
      }
    }
  } finally {
    loading.value = false
  }
}

const handleQuery = async () => {
  if (!question.value.trim()) {
    ElMessage.warning('请输入问题')
    return
  }

  const userQuestion = question.value
  question.value = ''
  await executeStreamQuery(userQuestion)
}

const handleQueryMediaUpload = async (uploadFile: any) => {
  const file = uploadFile.raw as File | undefined
  if (!file || !validateQueryMediaFile(file)) return

  if (loading.value) {
    ElMessage.warning('当前任务仍在执行，请稍后再上传')
    return
  }

  if (!selectedDataset.value) {
    ElMessage.warning('请先选择数据集后再上传图片或视频')
    return
  }

  if (selectedDataset.value.media_count <= 0) {
    ElMessage.warning('当前数据集暂无图片或视频索引，无法执行多模态检索')
    return
  }

  const fallbackQuestion = file.type.startsWith('image/') || /\.(png|jpe?g|bmp|webp)$/i.test(file.name)
    ? '查找与上传图片相似的图片和视频'
    : '查找与上传视频内容相似的图片和视频'
  const userQuestion = question.value.trim() || fallbackQuestion
  question.value = ''
  await executeStreamQuery(userQuestion, file)
}
</script>

<template>
  <div class="query-page">
    <!-- 中间数据集面板 -->
    <div class="dataset-panel">
      <div class="dataset-header">
        <span class="panel-label">数据集</span>
        <el-select
          v-model="selectedDataset"
          placeholder="请选择数据集"
          @change="handleDatasetChange"
          class="dataset-select"
        >
          <el-option
            v-for="ds in datasets"
            :key="ds.id"
            :label="ds.name"
            :value="ds"
          >
            <div class="dataset-option">
              <span>{{ ds.name }}</span>
              <el-tag size="small" :type="getDatasetProcessingTagType(ds.processing_status)">
                {{ getDatasetProcessingText(ds) }}
              </el-tag>
            </div>
          </el-option>
        </el-select>
      </div>

      <el-alert
        v-if="selectedDatasetWarning"
        :title="selectedDatasetWarning.title"
        :type="selectedDatasetWarning.type as any"
        :closable="false"
        show-icon
        class="dataset-warning"
      />

      <div class="table-search" v-if="selectedDataset">
        <el-input
          v-model="tableSearch"
          placeholder="搜索数据集/表"
          prefix-icon="Search"
          clearable
        />
      </div>

      <div class="table-list" v-if="selectedDataset">
        <div
          v-for="table in filteredTables"
          :key="table.id"
          class="table-item"
          @click="table.checked = !table.checked; handleTableCheckChange(table)"
        >
          <el-checkbox :model-value="table.checked" @change="table.checked = !table.checked; handleTableCheckChange(table)" />
          <span class="table-name">{{ table.label }}</span>
        </div>
      </div>
      <div class="table-empty" v-else>
        <el-icon :size="32"><InfoFilled /></el-icon>
        <span>请先选择数据集</span>
      </div>
    </div>

    <!-- 右侧主区域 -->
    <div class="main-area">
      <!-- 已选数据表标签 -->
      <div class="selected-tags" v-if="selectedTableLabels.length > 0">
        <span class="tags-label">已选:</span>
        <div class="tags-list">
          <el-tag
            v-for="(label, idx) in selectedTableLabels"
            :key="idx"
            closable
            @close="clearSelectedTables"
            class="selected-tag"
          >
            {{ label }}
          </el-tag>
        </div>
        <el-button text type="primary" size="small" @click="clearSelectedTables">
          清空
        </el-button>
      </div>

      <div v-if="messages.length > 0" class="session-toolbar">
        <span class="session-hint">已启用短会话上下文，可直接继续追问上一轮结果</span>
        <el-button text type="primary" size="small" @click="clearCurrentSession">
          清空当前会话
        </el-button>
      </div>

      <!-- 聊天区域 -->
      <div class="chat-container">
        <div class="chat-messages">
          <!-- 欢迎页 -->
          <div v-if="messages.length === 0" class="welcome-page">
            <h1 class="welcome-title">
              您好！欢迎使用 <span class="highlight">智能问答</span>
            </h1>
            <p class="welcome-desc">
              用自然语言描述业务问题或检索需求，系统可自动理解结构化数据并生成结果，也支持围绕图片、视频内容进行多模态检索。您可以直接选择数据表后提问，也可以从下方示例开始。
            </p>

            <div class="support-section">
              <h3 class="support-title">核心能力</h3>
              <div class="support-list">
                <div class="support-item">
                  <span class="support-icon">💬</span>
                  <span class="support-text">智能问答：理解自然语言问题，自动生成查询并返回结果</span>
                </div>
                <div class="support-item">
                  <span class="support-icon">🗂️</span>
                  <span class="support-text">结构化数据分析：支持告警、设备、区域、时间等业务场景分析</span>
                </div>
                <div class="support-item">
                  <span class="support-icon">🖼️</span>
                  <span class="support-text">图片相似检索：快速定位相似图片与关联线索</span>
                </div>
                <div class="support-item">
                  <span class="support-icon">🎬</span>
                  <span class="support-text">视频内容检索：根据场景描述查找相似视频片段</span>
                </div>
                <div class="support-item">
                  <span class="support-icon">🔗</span>
                  <span class="support-text">多模态融合：结合文本、图片、视频与结构化数据进行综合分析</span>
                </div>
              </div>
            </div>

            <el-divider />

            <div class="quick-examples">
              <h3 class="examples-title">快捷示例</h3>
              <div class="examples-list">
                <el-button
                  v-for="(example, idx) in quickExamples"
                  :key="idx"
                  class="example-btn"
                  @click="question = example"
                >
                  {{ example }}
                </el-button>
              </div>
            </div>
          </div>

          <!-- 消息列表 -->
          <div
            v-for="(msg, idx) in messages"
            :key="idx"
            class="message"
            :class="`message-${msg.role}`"
          >
            <div class="message-content">
              <!-- 用户消息 - 无背景色，不换行 -->
              <div v-if="msg.role === 'user'" style="color: #333; padding: 8px 0; max-width: 100%; margin-left: auto; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                {{ msg.content }}
              </div>

              <!-- 助手消息 - 多个独立卡片 -->
              <div v-else class="assistant-cards">
                <!-- 思考过程卡片 -->
                <div v-if="msg.thinkingLines && msg.thinkingLines.length > 0" class="thinking-card">
                  <div class="card-header">
                    <div class="header-left">
                      <span class="icon-emoji">🤖</span>
                      <span class="header-title">处理进度</span>
                    </div>
                    <div class="header-right">
                      <el-tag v-if="msg.data?.status" size="small" :type="msg.data.status === 'success' ? 'success' : 'danger'">
                        {{ msg.data.status === 'success' ? '已完成' : '已结束' }}
                      </el-tag>
                      <el-icon v-else class="is-loading loading-icon"><Loading /></el-icon>
                      <el-button text class="collapse-btn" @click="toggleProgressCollapse(msg)">
                        <el-icon><component :is="msg.progressCollapsed ? ArrowRight : ArrowDown" /></el-icon>
                        {{ msg.progressCollapsed ? '展开' : '收起' }}
                      </el-button>
                    </div>
                  </div>
                  <div v-if="msg.progressCollapsed" class="thinking-summary">
                    {{ getThinkingSummary(msg) }}
                  </div>
                  <div v-else class="thinking-content">
                    <div v-for="(line, lidx) in msg.thinkingLines" :key="lidx" class="thinking-line" :style="{ color: getLogColor(line) }">
                      {{ line }}
                    </div>
                  </div>
                </div>

                <!-- 闲聊回复卡片 -->
                <div v-if="msg.data && msg.data.intent === 'chat'" class="chat-reply-card">
                  <div class="chat-reply-content">
                    <span class="chat-avatar">🤖</span>
                    <div class="chat-text">{{ msg.streamedAnswer || msg.data.answer || msg.content }}</div>
                  </div>
                </div>

                <!-- 意图识别卡片（非闲聊） -->
                <div v-if="msg.data && msg.data.intent" class="intent-card">
                  <div class="intent-content">
                    <span class="icon-emoji">{{ msg.data.intent === 'chat' ? '💬' : msg.data.intent === 'search' ? '🔍' : msg.data.intent === 'count' ? '📊' : '💡' }}</span>
                    <span class="intent-text">已识别为意图: <strong>{{ msg.data.intent_text || (msg.data.intent === 'chat' ? '闲聊' : msg.data.intent === 'search' ? '向量检索' : msg.data.intent === 'count' ? '统计查询' : msg.data.intent === 'list' ? '列表查询' : msg.data.intent) }}</strong></span>
                  </div>
                </div>

                <!-- 成功状态卡片 -->
                <div v-if="msg.data && msg.data.status === 'success'" class="success-card">
                  <div class="success-content">
                    <span class="icon-emoji success-icon">✅</span>
                    <span class="success-title">查询成功</span>
                    <span class="result-count">{{ getSuccessSummaryText(msg.data) }}</span>
                    <el-tag v-if="msg.data.plan_source" size="small" type="info">
                      {{ getPlanSourceLabel(msg.data.plan_source) }}
                    </el-tag>
                    <el-tag v-if="typeof msg.data.confidence === 'number'" size="small" type="success">
                      置信度 {{ formatConfidence(msg.data.confidence) }}
                    </el-tag>
                  </div>
                </div>

                <el-alert
                  v-if="msg.data && msg.data.warnings && msg.data.warnings.length > 0"
                  :title="msg.data.warnings[0]"
                  type="warning"
                  :closable="false"
                  show-icon
                  class="result-warning"
                />

                <!-- SQL卡片 - 可编辑 -->
                <div v-if="msg.data && msg.data.sql" class="sql-card">
                  <div class="card-header">
                    <div class="header-left">
                      <span class="icon-emoji">📝</span>
                      <span class="header-title">生成的 SQL</span>
                    </div>
                    <div class="header-right">
                      <el-button text class="collapse-btn" @click="toggleSqlCollapse(msg)">
                        <el-icon><component :is="msg.sqlCollapsed ? ArrowRight : ArrowDown" /></el-icon>
                        {{ msg.sqlCollapsed ? '展开' : '收起' }}
                      </el-button>
                      <el-button
                        type="primary"
                        size="small"
                        :loading="msg.data.executing"
                        @click="handleRerunSql(idx, msg.data)"
                      >
                        重新执行
                      </el-button>
                    </div>
                  </div>
                  <div v-if="msg.sqlCollapsed" class="sql-preview">
                    {{ getSqlPreview(msg.data.sql) }}
                  </div>
                  <div v-else class="sql-editor">
                    <el-input type="textarea" v-model="msg.data.sql" :rows="4" class="sql-textarea" />
                  </div>
                </div>

                <div
                  v-if="msg.data && (getSemanticMatchedCount(msg.data) > 0 || getVectorRecommendations(msg.data).length > 0)"
                  class="semantic-card"
                >
                  <div class="card-header">
                    <div class="header-left">
                      <span class="icon-emoji">✨</span>
                      <span class="header-title">{{ getVectorRecommendations(msg.data).length > 0 ? `您可能还感兴趣 (${getVectorRecommendations(msg.data).length})` : '语义增强' }}</span>
                    </div>
                  </div>
                  <div class="semantic-summary">
                    <el-tag size="small" type="success">匹配 {{ getSemanticMatchedCount(msg.data) }} 条</el-tag>
                    <el-tag size="small" type="warning">补充 {{ getVectorRecommendations(msg.data).length }} 条</el-tag>
                  </div>
                  <div v-if="getVectorRecommendations(msg.data).length > 0" class="semantic-tip">
                    以下结果来自图像语义检索，与当前查询在视觉内容上相关
                  </div>
                  <div v-if="getVectorRecommendations(msg.data).length > 0" class="semantic-recommend-list">
                    <div
                      v-for="(item, ridx) in getVectorRecommendations(msg.data)"
                      :key="`${getRecommendationTitle(item)}-${ridx}`"
                      class="semantic-recommend-item"
                    >
                      <el-image
                        v-if="getSearchPreview(item)"
                        :src="getSearchPreview(item)"
                        fit="cover"
                        class="semantic-recommend-preview"
                        :preview-src-list="[getSearchPreview(item)]"
                      />
                      <div v-else class="semantic-recommend-fallback">相关结果</div>
                      <div class="semantic-recommend-main">
                        <div class="semantic-recommend-title">{{ getRecommendationTitle(item) }}</div>
                        <div class="semantic-recommend-desc">{{ formatSearchExtra(item) }}</div>
                      </div>
                      <el-tag size="small" type="info">{{ formatSearchScore(item) }}</el-tag>
                    </div>
                  </div>
                </div>

                <!-- 结果表格卡片 -->
                <div v-if="msg.data && msg.data.row_count > 0" class="result-card">
                  <div class="card-header">
                    <div class="header-left">
                      <span class="icon-emoji">{{ msg.data.intent === 'search' ? '🔍' : msg.data.intent === 'count' ? '📊' : '📋' }}</span>
                      <span class="header-title">{{ msg.data.intent === 'search' ? '检索结果' : msg.data.intent === 'count' ? '统计结果' : '查询结果' }}</span>
                    </div>
                    <div class="header-right">
                      <el-radio-group
                        v-if="canRenderChart(msg.data)"
                        :model-value="getResultViewMode(idx)"
                        size="small"
                        class="result-view-toggle"
                        @change="handleResultViewModeChange(idx, $event, msg.data)"
                      >
                        <el-radio-button label="detail">明细</el-radio-button>
                        <el-radio-button label="chart">图表</el-radio-button>
                      </el-radio-group>
                      <el-tag size="small" class="count-tag">{{ msg.data.row_count }} 条</el-tag>
                    </div>
                  </div>
                  <div class="table-wrapper">
                    <!-- 向量检索结果展示（包含相似度分数） -->
                    <template v-if="msg.data.intent === 'search'">
                      <el-table :data="msg.data.result_rows || []" border stripe size="small" max-height="350" class="result-table">
                        <el-table-column label="类型" min-width="80" align="center">
                          <template #default="{ row }">
                            <el-tag size="small" :type="row.type === 'video' ? 'warning' : 'success'">
                              {{ row.type === 'video' ? '视频' : '图片' }}
                            </el-tag>
                          </template>
                        </el-table-column>
                        <el-table-column label="预览" min-width="120" align="center">
                          <template #default="{ row }">
                            <el-image
                              v-if="getSearchPreview(row)"
                              :src="getSearchPreview(row)"
                              fit="cover"
                              style="width: 88px; height: 56px; border-radius: 6px"
                              :preview-src-list="[getSearchPreview(row)]"
                            />
                            <span v-else>-</span>
                          </template>
                        </el-table-column>
                        <el-table-column label="目标" min-width="140" show-overflow-tooltip>
                          <template #default="{ row }">
                            <span v-if="row.type === 'video'">视频 #{{ row.video_id }}</span>
                            <span v-else>图片 #{{ row.image_id }}</span>
                          </template>
                        </el-table-column>
                        <el-table-column label="时间段" min-width="140">
                          <template #default="{ row }">
                            {{ formatSearchTimeRange(row) }}
                          </template>
                        </el-table-column>
                        <el-table-column label="分数" width="100" align="center">
                          <template #default="{ row }">
                            <el-tag size="small" type="success">{{ formatSearchScore(row) }}</el-tag>
                          </template>
                        </el-table-column>
                        <el-table-column label="描述" min-width="220" show-overflow-tooltip>
                          <template #default="{ row }">
                            {{ formatSearchExtra(row) }}
                          </template>
                        </el-table-column>
                      </el-table>
                    </template>
                    <template v-else-if="getResultViewMode(idx) === 'chart'">
                      <div v-if="isLikelyRankingView(msg.data)" class="ranking-board">
                        <div class="ranking-header-row">
                          <span class="ranking-col-rank">排序</span>
                          <span class="ranking-col-name">{{ getRankingMeta(msg.data)?.dimensionLabel || '名称' }}</span>
                          <span class="ranking-col-value">{{ getRankingMeta(msg.data)?.metricLabel || '数值' }}</span>
                        </div>
                        <div class="ranking-list">
                          <div
                            v-for="item in getRankingRows(msg.data)"
                            :key="`${item.name}-${item.rank}`"
                            class="ranking-item"
                          >
                            <div class="ranking-rank">
                              <span v-if="item.rank <= 3" :class="['rank-badge', `rank-badge-${item.rank}`]">{{ item.rank }}</span>
                              <span v-else class="rank-num">{{ item.rank }}</span>
                            </div>
                            <div class="ranking-name" :title="item.name">{{ item.name }}</div>
                            <div class="ranking-bar-wrap">
                              <div class="ranking-bar-track">
                                <div class="ranking-bar-fill" :style="{ width: `${(item.ratio * 100).toFixed(1)}%` }" />
                              </div>
                            </div>
                            <div class="ranking-value">{{ formatMetricValue(item.value) }}</div>
                          </div>
                        </div>
                      </div>
                      <div
                        v-else
                        :id="getChartDomId(idx)"
                        class="result-chart"
                      />
                    </template>
                    <!-- 普通查询明细 -->
                    <template v-else>
                      <el-table :data="msg.data.result_rows || []" border stripe size="small" max-height="350" class="result-table">
                        <el-table-column v-for="col in msg.data.result_schema" :key="col.name" :prop="col.name" :label="col.name" min-width="120" show-overflow-tooltip />
                      </el-table>
                    </template>
                    <div
                      v-if="msg.data.row_count > (msg.data.result_rows?.length || 0) && getResultViewMode(idx) !== 'chart'"
                      class="more-hint"
                    >
                      当前展示 {{ msg.data.result_rows?.length || 0 }} 行（共 {{ msg.data.row_count }} 行）
                    </div>

                    <div
                      v-if="msg.data.intent === 'list' && hasListMedia(msg.data)"
                      class="list-media-preview"
                    >
                      <div class="section-subtitle">媒体预览</div>
                      <div class="list-media-grid">
                        <div
                          v-for="item in getListPreviewItems(msg.data)"
                          :key="item.key"
                          class="media-preview-item"
                        >
                          <el-image
                            v-if="item.image"
                            :src="item.image"
                            fit="cover"
                            class="media-preview-thumb"
                            :preview-src-list="[item.image]"
                          />
                          <video
                            v-else-if="item.video"
                            :src="item.video"
                            class="media-preview-thumb"
                            controls
                          />
                          <div v-else class="media-preview-empty">无媒体</div>
                          <div class="media-preview-title">{{ item.title }}</div>
                        </div>
                      </div>
                    </div>

                    <div v-if="msg.data.intent === 'list'" class="detail-section">
                      <div class="section-subtitle">查看详情</div>
                      <el-collapse>
                        <el-collapse-item
                          v-for="(row, detailIdx) in (msg.data.result_rows || []).slice(0, 20)"
                          :key="row.event_id || row.asset_id || detailIdx"
                          :title="getDetailTitle(row, detailIdx, msg.data)"
                          :name="detailIdx"
                        >
                          <div class="detail-layout">
                            <div class="detail-fields">
                              <div
                                v-for="field in getDetailFieldRows(row)"
                                :key="field.label"
                                class="detail-field-row"
                              >
                                <span class="detail-field-label">{{ field.label }}：</span>
                                <span class="detail-field-value">{{ field.value }}</span>
                              </div>
                            </div>
                            <div class="detail-media">
                              <el-tabs v-if="getListRowImageCandidates(row).length > 0 || getListRowVideoCandidates(row).length > 0" stretch>
                                <el-tab-pane v-if="getListRowImageCandidates(row).length > 0" label="原图">
                                  <el-image
                                    :src="getListRowImageCandidates(row)[0]"
                                    fit="contain"
                                    class="detail-media-view"
                                    :preview-src-list="getListRowImageCandidates(row)"
                                  />
                                </el-tab-pane>
                                <el-tab-pane v-if="getListRowVideoCandidates(row).length > 0" label="视频">
                                  <video
                                    :src="getListRowVideoCandidates(row)[0]"
                                    class="detail-media-view"
                                    controls
                                  />
                                </el-tab-pane>
                                <el-tab-pane v-if="getListRowImageCandidates(row).length > 1" label="更多图片">
                                  <div class="detail-image-list">
                                    <el-image
                                      v-for="img in getListRowImageCandidates(row).slice(1)"
                                      :key="img"
                                      :src="img"
                                      fit="cover"
                                      class="detail-image-thumb"
                                      :preview-src-list="getListRowImageCandidates(row)"
                                    />
                                  </div>
                                </el-tab-pane>
                              </el-tabs>
                              <div v-else class="detail-media-empty">暂无媒体预览</div>
                            </div>
                          </div>
                        </el-collapse-item>
                      </el-collapse>
                    </div>
                  </div>
                </div>

                <div
                  v-if="msg.data && msg.data.intent !== 'chat' && (msg.data.answer || msg.data.evidence)"
                  class="summary-row"
                >
                  <div v-if="msg.data.answer" class="answer-card">
                    <div class="card-header">
                      <div class="header-left">
                        <span class="icon-emoji">🧠</span>
                        <span class="header-title">回答摘要</span>
                      </div>
                      <el-tag v-if="msg.answerStreaming" size="small" type="primary">流式输出中</el-tag>
                    </div>
                    <div class="answer-text">{{ msg.streamedAnswer || msg.data.answer }}</div>
                  </div>

                  <div v-if="msg.data.evidence" class="evidence-card">
                    <div class="card-header">
                      <div class="header-left">
                        <span class="icon-emoji">📌</span>
                        <span class="header-title">证据</span>
                      </div>
                    </div>
                    <div class="evidence-summary">
                      {{ msg.data.evidence.summary || '已返回结构化证据。' }}
                    </div>
                    <div v-if="getEvidenceSourceTables(msg.data).length > 0" class="evidence-tables">
                      <span class="meta-label">来源表:</span>
                      <div class="meta-tags">
                        <el-tag v-for="table in getEvidenceSourceTables(msg.data)" :key="table" size="small" class="meta-tag">
                          {{ table }}
                        </el-tag>
                      </div>
                    </div>
                  </div>
                </div>

                <div
                  v-if="msg.data && buildFollowUpSuggestions(msg.data).length > 0"
                  class="follow-up-card"
                >
                  <div class="card-header">
                    <div class="header-left">
                      <span class="icon-emoji">🪄</span>
                      <span class="header-title">追问建议</span>
                    </div>
                  </div>
                  <div class="follow-up-list">
                    <el-button
                      v-for="suggestion in buildFollowUpSuggestions(msg.data)"
                      :key="suggestion"
                      size="small"
                      plain
                      @click="applyFollowUpSuggestion(suggestion)"
                    >
                      {{ suggestion }}
                    </el-button>
                  </div>
                </div>

                <!-- 失败状态 -->
                <div v-if="msg.data && msg.data.status === 'error'" class="error-card">
                  <div class="error-content">
                    <span class="icon-emoji error-icon">❌</span>
                    <span class="error-title">查询失败</span>
                  </div>
                  <div v-if="msg.data.error" class="error-detail">{{ msg.data.error }}</div>
                  <div
                    v-if="msg.data.clarification_needed && msg.data.clarification_options && msg.data.clarification_options.length > 0"
                    class="clarification-block"
                  >
                    <div class="clarification-title">请先明确要分析的数据表:</div>
                    <div class="clarification-options">
                      <el-button
                        v-for="option in msg.data.clarification_options"
                        :key="option"
                        size="small"
                        @click="applyClarificationOption(option, msg.data)"
                      >
                        {{ option }}
                      </el-button>
                    </div>
                  </div>
                </div>

                <!-- 加载中提示 -->
                <div v-if="(!msg.data || !msg.data.status) && msg.thinkingLines && msg.thinkingLines.length > 0" class="loading-card">
                  <el-icon class="is-loading loading-icon"><Loading /></el-icon>
                  <span class="loading-text">正在处理中...</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 输入区域 -->
        <div class="chat-input">
          <div class="input-container">
            <div class="input-wrapper">
              <el-upload
                class="upload-trigger"
                :auto-upload="false"
                :show-file-list="false"
                :file-list="[]"
                :multiple="false"
                accept=".jpg,.jpeg,.png,.bmp,.webp,.mp4,.mov,.avi,.mkv,.m4v,.webm,image/*,video/*"
                :on-change="handleQueryMediaUpload"
              >
                <el-button plain class="upload-btn" :disabled="loading">
                  <el-icon><UploadFilled /></el-icon>
                  上传图片/视频
                </el-button>
              </el-upload>
              <el-input
                v-model="question"
                type="textarea"
                placeholder="请输入业务问题、分析诉求或检索需求..."
                :rows="3"
                :autosize="{ minRows: 2, maxRows: 6 }"
                resize="none"
                :loading="loading"
                @keydown.enter.exact.prevent="handleQuery"
              />
              <el-button
                type="primary"
                class="send-btn"
                :loading="loading"
                :disabled="!question.trim()"
                @click="handleQuery"
              >
                <el-icon><Promotion /></el-icon>
              </el-button>
            </div>
            <div class="input-tip">上传图片或视频后将直接触发多模态检索；也可先输入补充说明再上传。</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.query-page {
  height: 100%;
  display: flex;
  background-color: #f5f5f5;
  position: relative;
}

// 左侧边栏
.sidebar {
  width: 220px;
  background-color: #fff;
  border-right: 1px solid #e8eaed;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  position: relative;
  z-index: 10;
}

.sidebar-header {
  padding: 16px;
  border-bottom: 1px solid #e8eaed;
}

.logo-section {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}

.logo-icon {
  color: #409eff;
}

.logo-text {
  font-size: 18px;
  font-weight: 600;
  color: #303133;
}

// 导航菜单
.nav-section {
  padding: 12px 8px;
  border-bottom: 1px solid #e8eaed;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  color: #606266;
  transition: all 0.2s ease;
  font-size: 14px;

  &:hover {
    background-color: #f5f7fa;
    color: #303133;
  }

  &.active {
    background-color: #ecf5ff;
    color: #409eff;
  }
}

.history-section {
  flex: 1;
  padding: 12px 8px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  color: #909399;
  font-size: 12px;
  font-weight: 500;
}

.history-list {
  flex: 1;
  overflow-y: auto;
  margin-top: 8px;
}

.history-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;

  &:hover {
    background-color: #f5f7fa;
  }
}

.history-title {
  font-size: 13px;
  color: #303133;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.history-time {
  font-size: 11px;
  color: #909399;
}

// 历史会话空状态
.history-empty {
  padding: 20px;
  text-align: center;
  color: #909399;
  font-size: 13px;
}

// 中间数据集面板
.dataset-panel {
  width: 260px;
  background-color: #fff;
  border-right: 1px solid #e8eaed;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  position: relative;
  z-index: 10;
}

.dataset-header {
  padding: 16px;
  border-bottom: 1px solid #e8eaed;
}

.panel-label {
  display: block;
  font-size: 12px;
  color: #909399;
  margin-bottom: 8px;
  font-weight: 500;
}

.dataset-select {
  width: 100%;
}

.dataset-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.dataset-warning {
  margin: 12px 16px 0;
}

.table-search {
  padding: 12px 16px;
  border-bottom: 1px solid #e8eaed;
}

.table-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px 0;
}

.table-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: #909399;
  font-size: 14px;
  padding: 40px 20px;
}

.table-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  cursor: pointer;
  transition: all 0.2s ease;

  &:hover {
    background-color: #f5f7fa;
  }

  .table-name {
    font-size: 13px;
    color: #303133;
  }
}

// 右侧主区域
.main-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
}

.mobile-buttons {
  display: none;
  position: absolute;
  top: 16px;
  left: 16px;
  z-index: 5;
  gap: 8px;
}

.selected-tags {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 20px;
  background-color: #fff;
  border-bottom: 1px solid #e8eaed;
  flex-shrink: 0;
}

.tags-label {
  font-size: 13px;
  color: #606266;
  font-weight: 500;
}

.tags-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  flex: 1;
}

.selected-tag {
  background-color: #ecf5ff;
  border-color: #b3d8ff;
  color: #409eff;
}

.session-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 20px;
  background: #f8fbff;
  border-bottom: 1px solid #e8eaed;
  flex-shrink: 0;
}

.session-hint {
  font-size: 13px;
  color: #606266;
}

// 聊天容器
.chat-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  background-color: #f5f5f5;
}

// 欢迎页
.welcome-page {
  max-width: 720px;
  margin: 0 auto;
  padding: 20px 0;
}

.welcome-title {
  font-size: 32px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 16px;
  line-height: 1.4;

  .highlight {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 50%, #409eff 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }
}

.welcome-desc {
  font-size: 15px;
  color: #606266;
  line-height: 1.8;
  margin-bottom: 32px;
}

.support-section {
  margin-bottom: 32px;
}

.support-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 16px;
}

.support-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.support-item {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 14px;
  color: #606266;
}

.support-icon {
  font-size: 16px;
  width: 24px;
  text-align: center;
}

.quick-examples {
  margin-top: 24px;
}

.examples-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 16px;
}

.examples-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.example-btn {
  text-align: left;
  justify-content: flex-start;
  padding: 12px 16px;
  height: auto;
  white-space: normal;
  line-height: 1.5;
  color: #606266;
  background-color: #f5f7fa;
  border-color: #e8eaed;

  &:hover {
    background-color: #ecf5ff;
    border-color: #b3d8ff;
    color: #409eff;
  }
}

// 消息样式
.message {
  margin-bottom: 20px;
  display: flex;
  animation: fadeIn 0.3s ease;
  width: 100%;

  &.message-user {
    justify-content: flex-end;

    .message-content {
      background-color: #409eff;
      color: #fff;
      border-radius: 16px 16px 4px 16px;
      box-shadow: 0 2px 8px rgba(64, 158, 255, 0.3);
      padding: 12px 16px;
    }
  }

  &.message-assistant {
    justify-content: flex-end;

    .message-content {
      background-color: #fff;
      border: 1px solid #e4e7ed;
      border-radius: 12px;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
      padding: 16px;
      max-width: 100%;
      width: 100%;
    }
  }
}

// 助手消息卡片容器
.assistant-cards {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
  max-width: 100%;
}

// 思考过程卡片
.thinking-card {
  background: white;
  border-radius: 12px;
  padding: 16px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
  border: none;

  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;

    .header-left {
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .icon-emoji {
      font-size: 20px;
    }

    .header-title {
      color: #333;
      font-weight: 600;
      font-size: 14px;
    }

    .loading-icon {
      color: #409eff;
      font-size: 16px;
    }
  }

  .header-right {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .collapse-btn {
    color: #667085;
    padding: 0;
  }

  .thinking-summary {
    background: #f8f9fa;
    border-radius: 8px;
    padding: 12px;
    font-size: 13px;
    color: #4b5563;
    line-height: 1.7;
  }

  .thinking-content {
    background: #f8f9fa;
    border-radius: 8px;
    padding: 12px;
    max-height: 400px;
    overflow-y: auto;
    font-family: 'Monaco', 'Menlo', monospace;
    font-size: 12px;
    line-height: 1.8;

    .thinking-line {
      color: #666;
    }
  }
}

// 意图识别卡片
.intent-card {
  background: #e6f7ff;
  border-radius: 12px;
  padding: 12px 16px;
  border-left: 4px solid #1890ff;

  .intent-content {
    display: flex;
    align-items: center;
    gap: 8px;

    .icon-emoji {
      font-size: 16px;
    }

    .intent-text {
      color: #1890ff;
      font-weight: 500;
      font-size: 14px;

      strong {
        font-weight: 600;
      }
    }
  }
}

.answer-card {
  background: #f5f8ff;
  border-radius: 12px;
  padding: 14px 16px;
  border: 1px solid #d9e6ff;
  flex: 1;
  min-width: 0;

  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 10px;

    .header-left {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .icon-emoji {
      font-size: 16px;
    }

    .header-title {
      color: #3557a6;
      font-weight: 600;
      font-size: 14px;
    }
  }

  .answer-text {
    color: #344054;
    font-size: 14px;
    line-height: 1.8;
    white-space: pre-wrap;
    word-break: break-word;
  }
}

// SQL卡片
.sql-card {
  background: #fff7e6;
  border-radius: 12px;
  padding: 16px;
  border: 1px solid #ffd591;

  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;

    .header-left {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .header-right {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .icon-emoji {
      font-size: 16px;
    }

    .header-title {
      color: #fa8c16;
      font-weight: 600;
      font-size: 14px;
    }
  }

  .collapse-btn {
    color: #8c5a12;
    padding: 0;
  }

  .sql-preview {
    background: #fff;
    border: 1px solid #f7c97c;
    border-radius: 8px;
    padding: 10px 12px;
    color: #7c4a03;
    font-family: 'Monaco', 'Menlo', monospace;
    font-size: 12px;
    line-height: 1.6;
    word-break: break-all;
  }

  .sql-editor {
    .sql-textarea {
      :deep(.el-textarea__inner) {
        font-family: 'Monaco', 'Menlo', monospace;
        font-size: 13px;
        background: white;
        border: 1px solid #d9d9d9;
        border-radius: 6px;
      }
    }
  }
}

.evidence-card {
  background: #f9f9ff;
  border-radius: 12px;
  padding: 14px 16px;
  border: 1px solid #dfe3ff;
  flex: 1;
  min-width: 0;

  .card-header {
    display: flex;
    align-items: center;
    margin-bottom: 8px;

    .header-left {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .icon-emoji {
      font-size: 16px;
    }

    .header-title {
      color: #4a56a6;
      font-weight: 600;
      font-size: 14px;
    }
  }

  .evidence-summary {
    font-size: 13px;
    color: #434b63;
    line-height: 1.6;
  }

  .evidence-tables {
    margin-top: 10px;
    display: flex;
    align-items: center;
    gap: 8px;

    .meta-label {
      font-size: 12px;
      color: #737a91;
      flex-shrink: 0;
    }

    .meta-tags {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }

    .meta-tag {
      border-color: #cad2ff;
      color: #4a56a6;
      background: #eef1ff;
    }
  }
}

.summary-row {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr);
  gap: 12px;
}

.list-media-preview {
  margin-top: 16px;
}

.section-subtitle {
  margin-bottom: 10px;
  font-size: 13px;
  font-weight: 600;
  color: #475467;
}

.list-media-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 12px;
}

.media-preview-item {
  padding: 10px;
  border: 1px solid #e6edf5;
  border-radius: 10px;
  background: #fafcff;
}

.media-preview-thumb,
.media-preview-empty {
  width: 100%;
  height: 96px;
  border-radius: 8px;
}

.media-preview-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f3f4f6;
  color: #98a2b3;
  font-size: 12px;
}

.media-preview-title {
  margin-top: 8px;
  font-size: 12px;
  color: #667085;
  line-height: 1.5;
}

.detail-section {
  margin-top: 16px;
}

.detail-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(320px, 0.9fr);
  gap: 16px;
}

.detail-fields {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.detail-field-row {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  padding: 6px 0;
  border-bottom: 1px dashed #eef2f6;
}

.detail-field-label {
  flex-shrink: 0;
  width: 88px;
  color: #667085;
  font-size: 12px;
}

.detail-field-value {
  color: #344054;
  font-size: 12px;
  line-height: 1.6;
  word-break: break-word;
}

.detail-media {
  min-width: 0;
}

.detail-media-view {
  width: 100%;
  max-height: 320px;
  border-radius: 10px;
  background: #0f172a;
}

.detail-media-empty {
  height: 160px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px dashed #d0d5dd;
  border-radius: 10px;
  color: #98a2b3;
  font-size: 13px;
}

.detail-image-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(88px, 1fr));
  gap: 10px;
}

.detail-image-thumb {
  width: 100%;
  height: 72px;
  border-radius: 8px;
}

.follow-up-card {
  background: #f8fafc;
  border-radius: 12px;
  padding: 14px 16px;
  border: 1px solid #e6edf5;

  .card-header {
    display: flex;
    align-items: center;
    margin-bottom: 10px;

    .header-left {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .icon-emoji {
      font-size: 16px;
    }

    .header-title {
      color: #334155;
      font-weight: 600;
      font-size: 14px;
    }
  }

  .follow-up-list {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
}

.exec-history-card {
  background: #f7fafc;
  border-radius: 12px;
  padding: 14px 16px;
  border: 1px solid #dde7f2;

  .card-header {
    display: flex;
    align-items: center;
    margin-bottom: 8px;

    .header-left {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .icon-emoji {
      font-size: 16px;
    }

    .header-title {
      color: #2f4a66;
      font-weight: 600;
      font-size: 14px;
    }
  }

  .exec-history-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .exec-history-item {
    display: grid;
    grid-template-columns: minmax(120px, 1fr) auto auto;
    gap: 8px;
    align-items: center;
    font-size: 12px;
    color: #425466;
    padding: 6px 8px;
    border-radius: 8px;
    background: #ffffff;
    border: 1px solid #e6edf5;
  }

  .exec-step {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .exec-duration {
    color: #5f7286;
    font-family: 'Monaco', 'Menlo', monospace;
  }

  .exec-history-more {
    font-size: 12px;
    color: #7a8a9a;
    margin-top: 2px;
  }
}

.semantic-card {
  background: #fffdf6;
  border-radius: 12px;
  padding: 14px 16px;
  border: 1px solid #f4e2a8;

  .card-header {
    display: flex;
    align-items: center;
    margin-bottom: 10px;

    .header-left {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .icon-emoji {
      font-size: 16px;
    }

    .header-title {
      color: #8b6a11;
      font-weight: 600;
      font-size: 14px;
    }
  }

  .semantic-summary {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    margin-bottom: 12px;
  }

  .semantic-tip {
    font-size: 12px;
    color: #7c6a36;
    margin-bottom: 10px;
  }

  .semantic-recommend-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .semantic-recommend-item {
    display: grid;
    grid-template-columns: 88px minmax(0, 1fr) auto;
    gap: 12px;
    align-items: center;
    padding: 10px;
    border-radius: 10px;
    background: #fff;
    border: 1px solid #f3ead1;
  }

  .semantic-recommend-preview,
  .semantic-recommend-fallback {
    width: 88px;
    height: 56px;
    border-radius: 8px;
  }

  .semantic-recommend-fallback {
    display: flex;
    align-items: center;
    justify-content: center;
    background: linear-gradient(135deg, #fff7db 0%, #ffefb0 100%);
    color: #8b6a11;
    font-size: 12px;
    font-weight: 600;
  }

  .semantic-recommend-main {
    min-width: 0;
  }

  .semantic-recommend-title {
    font-size: 13px;
    font-weight: 600;
    color: #4c4c4c;
    margin-bottom: 4px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .semantic-recommend-desc {
    font-size: 12px;
    color: #6b7280;
    line-height: 1.5;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
}

// 成功状态卡片
.success-card {
  background: #f6ffed;
  border-radius: 12px;
  padding: 12px 16px;
  border: 1px solid #b7eb8f;

  .success-content {
    display: flex;
    align-items: center;
    gap: 8px;

    .success-icon {
      font-size: 18px;
    }

    .success-title {
      color: #52c41a;
      font-weight: 600;
      font-size: 16px;
    }

    .result-count {
      color: #666;
      margin-left: 8px;
      font-size: 14px;
    }
  }
}

// 结果表格卡片
.result-card {
  background: white;
  border-radius: 12px;
  padding: 16px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
  border: 1px solid #e8e8e8;
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;

  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;

    .header-left {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .icon-emoji {
      font-size: 16px;
    }

    .header-title {
      color: #333;
      font-weight: 600;
      font-size: 14px;
    }

    .header-right {
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .result-view-toggle {
      :deep(.el-radio-button__inner) {
        padding: 5px 12px;
        border-radius: 16px;
      }
    }

    .count-tag {
      background: #f0f0f0;
      border-color: #d9d9d9;
      color: #666;
    }
  }

  .table-wrapper {
    .ranking-board {
      border: 1px solid #e8edf5;
      border-radius: 12px;
      overflow: hidden;
      background: #ffffff;
    }

    .ranking-header-row {
      display: grid;
      grid-template-columns: 90px minmax(180px, 1fr) 120px;
      align-items: center;
      gap: 16px;
      padding: 12px 16px;
      background: linear-gradient(90deg, #f6f9ff 0%, #eef4ff 100%);
      color: #44536a;
      font-weight: 600;
      font-size: 13px;
      border-bottom: 1px solid #edf1f8;
    }

    .ranking-list {
      max-height: 360px;
      overflow-y: auto;
    }

    .ranking-item {
      display: grid;
      grid-template-columns: 90px minmax(180px, 1fr) 1fr 120px;
      align-items: center;
      gap: 16px;
      padding: 14px 16px;
      border-bottom: 1px solid #f0f3f8;

      &:nth-child(odd) {
        background: #fbfdff;
      }

      &:last-child {
        border-bottom: none;
      }
    }

    .ranking-rank {
      display: flex;
      align-items: center;
      justify-content: center;

      .rank-badge {
        width: 28px;
        height: 28px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 13px;
        font-weight: 700;
        color: #fff;
      }

      .rank-badge-1 {
        background: linear-gradient(135deg, #f5a623 0%, #f8c255 100%);
        box-shadow: 0 4px 8px rgba(245, 166, 35, 0.35);
      }

      .rank-badge-2 {
        background: linear-gradient(135deg, #4c8cff 0%, #74a6ff 100%);
        box-shadow: 0 4px 8px rgba(76, 140, 255, 0.35);
      }

      .rank-badge-3 {
        background: linear-gradient(135deg, #f28f45 0%, #f6b17e 100%);
        box-shadow: 0 4px 8px rgba(242, 143, 69, 0.3);
      }

      .rank-num {
        font-size: 18px;
        font-weight: 600;
        color: #4e5b70;
      }
    }

    .ranking-name {
      color: #1f2d3d;
      font-size: 18px;
      font-weight: 500;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .ranking-bar-wrap {
      display: flex;
      align-items: center;
      width: 100%;
      min-width: 120px;
    }

    .ranking-bar-track {
      width: 100%;
      height: 12px;
      border-radius: 999px;
      background: #e7edf8;
      overflow: hidden;
      position: relative;
    }

    .ranking-bar-fill {
      height: 100%;
      border-radius: 999px;
      background: linear-gradient(90deg, #2f66f6 0%, #3a7bff 100%);
      box-shadow: inset 0 0 6px rgba(21, 76, 214, 0.25);
      transition: width 0.45s ease;
    }

    .ranking-value {
      justify-self: end;
      color: #1f2d3d;
      font-size: 32px;
      font-weight: 700;
      letter-spacing: 0.5px;
      line-height: 1;
    }

    .result-table {
      width: 100%;
      border-radius: 8px;
      overflow: hidden;
    }

    .result-chart {
      width: 100%;
      height: 340px;
      border: 1px solid #e8edf5;
      border-radius: 12px;
      background: #fff;
    }

    .more-hint {
      text-align: center;
      padding: 8px;
      color: #909399;
      font-size: 12px;
      background: #f5f7fa;
      border-radius: 0 0 8px 8px;
    }
  }
}

.result-warning {
  margin-bottom: 12px;
}

// 失败状态卡片
.error-card {
  background: #fff2f0;
  border-radius: 12px;
  padding: 16px;
  border: 1px solid #ffccc7;

  .error-content {
    display: flex;
    align-items: center;
    gap: 8px;

    .error-icon {
      font-size: 18px;
    }

    .error-title {
      color: #ff4d4f;
      font-weight: 600;
      font-size: 16px;
    }
  }

  .error-detail {
    margin-top: 8px;
    color: #666;
    font-size: 14px;
  }

  .clarification-block {
    margin-top: 10px;
    padding-top: 10px;
    border-top: 1px dashed #f5a6a6;
  }

  .clarification-title {
    color: #b54745;
    font-size: 12px;
    margin-bottom: 8px;
  }

  .clarification-options {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
}

// 加载中卡片
.loading-card {
  text-align: center;
  color: #999;
  padding: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;

  .loading-icon {
    font-size: 16px;
  }

  .loading-text {
    font-size: 14px;
  }
}

// @keyframes 定义
@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.message-content {
  max-width: 100%;
  padding: 14px 18px;
  word-wrap: break-word;
  line-height: 1.6;
}

.result-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  padding: 12px 16px;
  background: linear-gradient(135deg, #f0f9eb 0%, #e1f3d8 100%);
  border-radius: 8px;
  border: 1px solid #67c23a;
}

.result-info {
  font-size: 14px;
  color: #67c23a;
  font-weight: 500;
}

/* 思考过程区域 - 黑色背景类似 aaa.jpg */
.agent-thinking-section {
  margin: 16px 0;
  border-radius: 8px;
  overflow: hidden;
  background: #1e1e1e;
  border: 1px solid #333;
}

.agent-thinking-section .section-header {
  padding: 12px 16px;
  background: #2d2d2d;
  border-bottom: 1px solid #333;
}

.agent-thinking-section .section-title {
  color: #fff;
  font-size: 14px;
  font-weight: 600;
}

.agent-thinking-section .thinking-content {
  padding: 16px;
  max-height: 300px;
  overflow-y: auto;
}

.agent-thinking-section .thinking-content pre {
  margin: 0;
  color: #9cdcfe;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}

/* SQL 详情区域 */
.sql-section {
  margin: 16px 0;
  border-radius: 8px;
  overflow: hidden;
  background: #f5f7fa;
  border: 1px solid #dcdfe6;
}

.sql-section .section-header {
  padding: 12px 16px;
  background: #ebeef5;
  border-bottom: 1px solid #dcdfe6;
  display: flex;
  align-items: center;
}

.sql-section .section-title {
  color: #303133;
  font-size: 14px;
  font-weight: 600;
}

.sql-section .sql-content {
  padding: 16px;
}

.sql-section .sql-content pre {
  margin: 0;
  color: #e6a23c;
  font-size: 13px;
  font-family: 'Monaco', 'Menlo', monospace;
  line-height: 1.5;
}

/* 结果表格区域 */
.result-table-section {
  margin: 16px 0;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid #dcdfe6;
}

.result-table-section .section-header {
  padding: 12px 16px;
  background: #f5f7fa;
  border-bottom: 1px solid #dcdfe6;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.result-table-section .section-title {
  color: #303133;
  font-size: 14px;
  font-weight: 600;
}

.sql-section {
  margin: 12px 0;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  overflow: hidden;
}

.sql-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  background-color: #f5f7fa;
  cursor: pointer;
  user-select: none;

  &:hover {
    background-color: #ebeef5;
  }

  .arrow {
    margin-left: auto;
  }
}

.sql-content {
  padding: 12px;
  background-color: #fff;
}

.sql-item {
  margin-bottom: 12px;

  &:last-child {
    margin-bottom: 0;
  }
}

.sql-label {
  font-weight: 600;
  color: #606266;
  margin-bottom: 6px;
  font-size: 12px;
}

.sql-display {
  background-color: #f5f7fa;
  padding: 10px;
  border-radius: 4px;
  font-family: 'Monaco', 'Menlo', monospace;
  font-size: 12px;
  margin: 0;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

.reasoning-section,
.agent-steps {
  margin: 12px 0;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  overflow: hidden;
}

.reasoning-header,
.steps-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  background-color: #f0f9ff;
  cursor: pointer;
  user-select: none;

  &:hover {
    background-color: #e0f2fe;
  }

  .arrow {
    margin-left: auto;
  }
}

.reasoning-content {
  padding: 12px;
  background-color: #fff;
  font-size: 13px;
  line-height: 1.6;
  color: #303133;
}

.steps-content {
  background-color: #fafafa;
  max-height: 400px;
  overflow-y: auto;
}

.step-item {
  padding: 12px;
  border-bottom: 1px solid #ebeef5;

  &:last-child {
    border-bottom: none;
  }
}

.step-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 8px;

  &.thought {
    background-color: #e6f7ff;
    color: #1890ff;
    border: 1px solid #91d5ff;
  }

  &.action {
    background-color: #fff7e6;
    color: #fa8c16;
    border: 1px solid #ffd591;
  }

  &.observation {
    background-color: #f6ffed;
    color: #52c41a;
    border: 1px solid #b7eb8f;
  }
}

.step-text {
  font-size: 13px;
  line-height: 1.6;
  color: #303133;
  padding-left: 4px;
}

.step-input {
  margin-top: 8px;
  padding: 8px;
  background-color: #f5f5f5;
  border-radius: 4px;

  pre {
    margin: 0;
    font-size: 12px;
    font-family: 'Monaco', 'Menlo', monospace;
    white-space: pre-wrap;
    word-break: break-all;
    color: #e6a23c;
  }
}

.observation-text {
  color: #67c23a;
}

.result-table {
  margin-top: 16px;
}

.chart-type-selector {
  margin-bottom: 12px;
  display: flex;
  gap: 10px;
}

.chart-container {
  width: 100%;
  height: 400px;
}

.error-message {
  margin-top: 12px;
}

.warnings {
  margin-top: 12px;
}

.chat-input {
  padding: 16px 24px 20px;
  background-color: #fff;
  border-top: 1px solid #e8eaed;
  flex-shrink: 0;
}

.input-container {
  max-width: 100%;
  margin: 0 auto;
}

.input-tip {
  margin-top: 8px;
  font-size: 12px;
  color: #909399;
}

.input-wrapper {
  display: flex;
  gap: 12px;
  align-items: flex-end;
  background: #f5f7fa;
  border: 2px solid #e4e7ed;
  border-radius: 12px;
  padding: 12px 16px;
  transition: all 0.3s ease;

  &:hover {
    border-color: #c0c4cc;
  }

  &:focus-within {
    border-color: #409eff;
    box-shadow: 0 0 0 3px rgba(64, 158, 255, 0.1);
  }

  :deep(.el-textarea__inner) {
    background: transparent;
    border: none;
    font-size: 15px;
    line-height: 1.6;
    padding: 4px 0;

    &:focus {
      box-shadow: none;
    }
  }
}

.upload-trigger {
  flex-shrink: 0;
}

.upload-btn {
  height: 40px;
  border-radius: 8px;
}

.send-btn {
  height: auto;
  padding: 10px 14px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: all 0.3s ease;

  &:hover:not(:disabled) {
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(64, 158, 255, 0.3);
  }

  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
}

// 移动端响应式
.mobile-overlay {
  display: none;
}

@media (max-width: 1024px) {
  .sidebar {
    position: fixed;
    left: 0;
    top: 60px;
    bottom: 0;
    transform: translateX(-100%);
    transition: transform 0.3s ease;
    z-index: 100;

    &.mobile-show {
      transform: translateX(0);
    }
  }

  .dataset-panel {
    position: fixed;
    left: 0;
    top: 60px;
    bottom: 0;
    transform: translateX(-100%);
    transition: transform 0.3s ease;
    z-index: 100;

    &.mobile-show {
      transform: translateX(0);
    }
  }

  .mobile-overlay {
    display: block;
    position: fixed;
    top: 60px;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.5);
    z-index: 99;
  }

  .mobile-buttons {
    display: flex;
  }

  .main-area {
    margin-left: 0;
  }
}

@media (max-width: 768px) {
  .welcome-title {
    font-size: 24px;
  }

  .welcome-desc {
    font-size: 14px;
  }

  .message-content {
    max-width: 100%;
    width: 100%;
  }

  .result-card .table-wrapper {
    .result-chart {
      height: 260px;
    }

    .ranking-header-row {
      grid-template-columns: 64px minmax(120px, 1fr) 90px;
      gap: 10px;
      font-size: 12px;
      padding: 10px 12px;
    }

    .ranking-item {
      grid-template-columns: 64px minmax(120px, 1fr) 1fr 90px;
      gap: 10px;
      padding: 10px 12px;
    }

    .ranking-rank .rank-badge {
      width: 22px;
      height: 22px;
      font-size: 12px;
    }

    .ranking-rank .rank-num {
      font-size: 15px;
    }

    .ranking-name {
      font-size: 14px;
    }

    .ranking-bar-track {
      height: 9px;
    }

    .ranking-value {
      font-size: 16px;
    }
  }
}
</style>
