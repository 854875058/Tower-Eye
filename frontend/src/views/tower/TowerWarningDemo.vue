<script setup lang="ts">
import * as echarts from 'echarts'
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { towerDemoApi } from '@/api'
import type {
  TowerDemoAssistantResponse,
  TowerDemoDashboard,
  TowerGraphPayload,
  TowerLineagePayload,
  TowerOntologyConfig,
} from '@/api/types'

const activeTab = ref('overview')
const loading = ref(false)
const asking = ref(false)
const savingOntology = ref(false)
const dashboard = ref<TowerDemoDashboard | null>(null)
const graphData = ref<TowerGraphPayload | null>(null)
const lineageData = ref<TowerLineagePayload | null>(null)
const ontologyConfig = ref<TowerOntologyConfig | null>(null)
const assistantQuestion = ref('哪些区域告警最集中，建议优先怎么处置？')
const assistantResult = ref<TowerDemoAssistantResponse | null>(null)
const previewVisible = ref(false)
const previewTitle = ref('')
const previewType = ref<'image' | 'video'>('image')
const previewUrl = ref('')
const previewSummary = ref('')
const graphRef = ref<HTMLDivElement | null>(null)
const assistantChartRef = ref<HTMLDivElement | null>(null)
const heroSectionRef = ref<HTMLElement | null>(null)
const hotRegionsRef = ref<HTMLElement | null>(null)
const hotDevicesRef = ref<HTMLElement | null>(null)
const recommendationsRef = ref<HTMLElement | null>(null)
const priorityQueueRef = ref<HTMLElement | null>(null)
const graphSectionRef = ref<HTMLElement | null>(null)
const ontologySectionRef = ref<HTMLElement | null>(null)
const selectedGraphNode = ref<Record<string, any> | null>(null)
let graphChart: echarts.ECharts | null = null
let assistantChart: echarts.ECharts | null = null

const demoQuestions = [
  '哪些区域告警最集中，建议优先怎么处置？',
  '当前哪些设备需要优先巡检？',
  '有哪些疑似误报，应该先做人工复核？',
  '基于现有样本，我们最适合先做哪类能力演示？',
]

const loadDashboard = async () => {
  loading.value = true
  try {
    const res = await towerDemoApi.getDashboard()
    dashboard.value = res.data
  } catch (error) {
    console.error(error)
    ElMessage.error('加载视联样机数据失败')
  } finally {
    loading.value = false
  }
}

const loadGraph = async () => {
  try {
    const res = await towerDemoApi.getGraph()
    graphData.value = res.data
  } catch (error) {
    console.error(error)
    ElMessage.error('加载知识图谱失败')
  }
}

const loadOntology = async () => {
  try {
    const res = await towerDemoApi.getOntology()
    ontologyConfig.value = JSON.parse(JSON.stringify(res.data))
  } catch (error) {
    console.error(error)
    ElMessage.error('加载本体配置失败')
  }
}

const loadLineage = async (eventId?: string) => {
  if (!eventId) return
  try {
    const res = await towerDemoApi.getLineage(eventId)
    lineageData.value = res.data
  } catch (error) {
    console.error(error)
    ElMessage.error('加载事件血缘失败')
  }
}

const addEntity = () => {
  ontologyConfig.value?.entities.push({
    type: `entity_${Date.now()}`,
    label: '新实体',
    description: '请填写实体说明',
    key_fields: [],
    source_fields: [],
    enabled: true,
  })
}

const addRelation = () => {
  ontologyConfig.value?.relations.push({
    type: `relation_${Date.now()}`,
    label: '新关系',
    source_type: 'event',
    target_type: 'region',
    description: '请填写关系说明',
    source_field: '',
    enabled: true,
  })
}

const removeEntity = async (index: number) => {
  if (!ontologyConfig.value) return
  await ElMessageBox.confirm('确认删除该实体类型吗？', '提示', { type: 'warning' })
  ontologyConfig.value.entities.splice(index, 1)
}

const removeRelation = async (index: number) => {
  if (!ontologyConfig.value) return
  await ElMessageBox.confirm('确认删除该关系类型吗？', '提示', { type: 'warning' })
  ontologyConfig.value.relations.splice(index, 1)
}

const saveOntology = async () => {
  if (!ontologyConfig.value) return
  savingOntology.value = true
  try {
    const res = await towerDemoApi.saveOntology(ontologyConfig.value)
    ontologyConfig.value = JSON.parse(JSON.stringify(res.data))
    await loadGraph()
    ElMessage.success('本体配置已保存')
  } catch (error) {
    console.error(error)
    ElMessage.error('保存本体配置失败')
  } finally {
    savingOntology.value = false
  }
}

const resetOntology = async () => {
  savingOntology.value = true
  try {
    const res = await towerDemoApi.resetOntology()
    ontologyConfig.value = JSON.parse(JSON.stringify(res.data))
    await loadGraph()
    ElMessage.success('本体配置已恢复默认')
  } catch (error) {
    console.error(error)
    ElMessage.error('恢复默认配置失败')
  } finally {
    savingOntology.value = false
  }
}

const askAssistant = async (question?: string) => {
  const text = (question || assistantQuestion.value).trim()
  if (!text) {
    ElMessage.warning('请输入问题')
    return
  }
  assistantQuestion.value = text
  asking.value = true
  try {
    const res = await towerDemoApi.askAssistant(text)
    assistantResult.value = res.data
  } catch (error) {
    console.error(error)
    ElMessage.error('智能体分析失败')
  } finally {
    asking.value = false
  }
}

const formatDateTime = (value?: string) => value ? new Date(value).toLocaleString() : '-'

const openMediaPreview = (
  type: 'image' | 'video',
  url?: string,
  title?: string,
  summary?: string,
) => {
  if (!url) return
  previewType.value = type
  previewUrl.value = url
  previewTitle.value = title || '样本预览'
  previewSummary.value = summary || ''
  previewVisible.value = true
}

const assistantEvidenceCards = computed(() => {
  const evidence = assistantResult.value?.evidence
  if (!evidence) return []
  if (Array.isArray(evidence)) {
    return evidence.map((item: any, index: number) => ({
      key: `${item.event_id || item.device_name || item.county_name || item.title || index}`,
      title: item.county_name || item.device_name || item.title || item.event_type || `证据 ${index + 1}`,
      summary:
        item.reason ||
        item.summary ||
        (item.count ? `${item.count} 次告警` : '') ||
        (item.avg_confidence ? `平均置信度 ${item.avg_confidence}` : ''),
      imageUrl: item.image_url,
      videoUrl: item.video_url,
      eventId: item.event_id,
      raw: item,
    }))
  }
  if (typeof evidence === 'object') {
    const cards: Array<Record<string, any>> = []
    if (Array.isArray((evidence as any).hot_regions)) {
      cards.push(
        ...(evidence as any).hot_regions.map((item: any, index: number) => ({
          key: `region-${index}`,
          title: item.county_name,
          summary: `${item.count} 次告警，平均置信度 ${item.avg_confidence}`,
          raw: item,
        }))
      )
    }
    if (Array.isArray((evidence as any).hot_devices)) {
      cards.push(
        ...(evidence as any).hot_devices.map((item: any, index: number) => ({
          key: `device-${index}`,
          title: item.device_name,
          summary: `${item.count} 次告警，最近时间 ${formatDateTime(item.last_alarm_time)}`,
          raw: item,
        }))
      )
    }
    return cards.slice(0, 6)
  }
  return []
})

const sectionMap = computed(() => ({
  overview: heroSectionRef.value,
  hot_regions: hotRegionsRef.value,
  hot_devices: hotDevicesRef.value,
  recommendations: recommendationsRef.value,
  priority_queue: priorityQueueRef.value,
  graph: graphSectionRef.value,
  ontology: ontologySectionRef.value,
  trend: recommendationsRef.value,
}))

const graphStatCards = computed(() => {
  const stats = graphData.value?.graph.stats
  if (!stats) return []
  return [
    { label: '图谱节点', value: stats.node_count },
    { label: '图谱边', value: stats.edge_count },
    { label: '实体类型', value: Object.keys(stats.node_categories || {}).length },
    { label: '关系类型', value: Object.keys(stats.edge_categories || {}).length },
  ]
})

const renderAssistantChart = async () => {
  const visualization = assistantResult.value?.visualization
  if (!assistantChartRef.value || !visualization) {
    assistantChart?.dispose()
    assistantChart = null
    return
  }
  await nextTick()
  if (!assistantChart) {
    assistantChart = echarts.init(assistantChartRef.value)
  }
  assistantChart.setOption({
    backgroundColor: 'transparent',
    title: {
      text: visualization.title,
      left: 'center',
      textStyle: { color: '#0f172a', fontSize: 14, fontWeight: 600 },
    },
    tooltip: { trigger: 'axis' },
    grid: { left: 48, right: 24, top: 48, bottom: 48 },
    xAxis: {
      type: 'category',
      data: visualization.categories,
      axisLabel: { color: '#64748b', rotate: visualization.categories.length > 4 ? 18 : 0 },
    },
    yAxis: {
      type: 'value',
      name: visualization.y_axis_name || '',
      axisLabel: { color: '#64748b' },
      splitLine: { lineStyle: { color: '#e2e8f0' } },
    },
    series: visualization.series.map((item, index) => ({
      type: visualization.chart_type === 'line' ? 'line' : 'bar',
      name: item.name,
      data: item.data,
      smooth: visualization.chart_type === 'line',
      barMaxWidth: 42,
      itemStyle: {
        color: index === 0 ? '#3b82f6' : '#14b8a6',
      },
      areaStyle: visualization.chart_type === 'line' ? { color: 'rgba(59,130,246,0.12)' } : undefined,
    })),
  }, true)
  assistantChart.resize()
}

const renderGraph = async () => {
  if (!graphRef.value || !graphData.value) return
  await nextTick()

  const categoryColorMap: Record<string, string> = {
    source: '#3b82f6',
    event: '#f97316',
    region: '#14b8a6',
    device: '#8b5cf6',
    algorithm: '#eab308',
    media: '#ef4444',
    process: '#64748b',
    recommendation: '#10b981',
  }

  if (!graphChart) {
    graphChart = echarts.init(graphRef.value)
    graphChart.on('click', (params: any) => {
      selectedGraphNode.value = params?.data || null
      const eventId = params?.data?.meta?.event_id
      if (eventId) {
        void loadLineage(eventId)
      }
    })
  }

  const categories = graphData.value.ontology.map(item => ({
    name: item.type,
    itemStyle: { color: categoryColorMap[item.type] || '#94a3b8' },
  }))

  const nodes = graphData.value.graph.nodes.map(node => ({
    ...node,
    name: node.label,
    category: graphData.value!.ontology.findIndex(item => item.type === node.category),
    itemStyle: { color: categoryColorMap[node.category] || '#94a3b8' },
    label: {
      show: true,
      color: '#0f172a',
      fontSize: node.category === 'event' ? 11 : 12,
    },
  }))

  const links = graphData.value.graph.edges.map(edge => ({
    source: edge.source,
    target: edge.target,
    value: edge.label,
    lineStyle: {
      color: '#cbd5e1',
      width: 1.5,
      curveness: 0.12,
    },
    label: {
      show: false,
      formatter: edge.label,
    },
  }))

  graphChart.setOption({
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'item',
      formatter: (params: any) => {
        if (params.dataType === 'edge') {
          return `${params.data.source} → ${params.data.target}<br/>${params.data.value || ''}`
        }
        const meta = params.data.meta || {}
        const lines = [`<strong>${params.data.name}</strong>`]
        Object.entries(meta).slice(0, 5).forEach(([key, value]) => {
          if (value !== undefined && value !== null && value !== '') {
            lines.push(`${key}: ${value}`)
          }
        })
        return lines.join('<br/>')
      },
    },
    legend: {
      top: 0,
      textStyle: { color: '#334155' },
    },
    series: [
      {
        type: 'graph',
        layout: 'force',
        roam: true,
        draggable: true,
        focusNodeAdjacency: true,
        categories,
        data: nodes,
        links,
        force: {
          repulsion: 280,
          edgeLength: [90, 180],
          gravity: 0.08,
        },
        emphasis: {
          scale: 1.15,
          lineStyle: { width: 3 },
        },
      },
    ],
  }, true)
  graphChart.resize()
}

watch(graphData, () => {
  void renderGraph()
})

watch(() => assistantResult.value?.visualization, () => {
  void renderAssistantChart()
})

const handleAssistantAction = async (action: { type: string; target: string; payload?: Record<string, any> }) => {
  if (action.target === 'ontology') {
    activeTab.value = 'ontology'
    await nextTick()
    ontologySectionRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    return
  }

  if (action.type === 'open_lineage' && action.payload?.event_id) {
    await loadLineage(String(action.payload.event_id))
    graphSectionRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    return
  }

  if (action.type === 'focus_graph') {
    graphSectionRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    return
  }

  const targetEl = sectionMap.value[action.target as keyof typeof sectionMap.value]
  targetEl?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

onMounted(async () => {
  await loadDashboard()
  await loadOntology()
  await loadGraph()
  if (dashboard.value?.low_confidence_events?.length) {
    await loadLineage(dashboard.value.low_confidence_events[0].event_id)
  }
  await askAssistant(assistantQuestion.value)
})

onUnmounted(() => {
  graphChart?.dispose()
  graphChart = null
  assistantChart?.dispose()
  assistantChart = null
})
</script>

<template>
  <div class="tower-demo-page" v-loading="loading">
    <el-tabs v-model="activeTab" class="tower-tabs">
      <el-tab-pane label="分析总览" name="overview">
    <section ref="heroSectionRef" class="hero-card">
      <div class="hero-copy">
        <span class="eyebrow">视联告警智能分析平台</span>
        <h1>融合告警事件、图片、视频与设备元数据，支撑告警检索、异常分析、风险识别与处置建议</h1>
        <p>
          面向视联告警业务场景，平台围绕多模态证据关联、告警热点识别、疑似误报复核、
          风险排序和处置建议生成，提供一体化的智能分析与决策支持能力。
        </p>
      </div>
      <div v-if="dashboard" class="hero-stats">
        <div class="hero-stat">
          <span>告警事件</span>
          <strong>{{ dashboard.summary.total_events }}</strong>
        </div>
        <div class="hero-stat">
          <span>图片样本</span>
          <strong>{{ dashboard.summary.image_count }}</strong>
        </div>
        <div class="hero-stat">
          <span>视频样本</span>
          <strong>{{ dashboard.summary.video_count }}</strong>
        </div>
        <div class="hero-stat">
          <span>平均置信度</span>
          <strong>{{ dashboard.summary.avg_confidence.toFixed(3) }}</strong>
        </div>
        <div class="hero-stat">
          <span>高优先级建议</span>
          <strong>{{ dashboard.recommendations.filter(item => item.priority === 'high').length }}</strong>
        </div>
        <div class="hero-stat">
          <span>待复核样本</span>
          <strong>{{ dashboard.priority_queue.length }}</strong>
        </div>
      </div>
    </section>

    <section class="assistant-card">
      <div class="section-head">
        <div>
          <h2>运营分析智能体</h2>
          <p>面向视联告警场景，支持区域热点识别、设备风险分析、疑似误报筛查与处置建议生成。</p>
        </div>
      </div>
      <div class="assistant-input">
        <el-input v-model="assistantQuestion" placeholder="输入一个业务问题" @keyup.enter="askAssistant()" />
        <el-button type="primary" :loading="asking" @click="askAssistant()">分析</el-button>
      </div>
      <div class="question-list">
        <el-button v-for="item in demoQuestions" :key="item" plain @click="askAssistant(item)">
          {{ item }}
        </el-button>
      </div>

      <div v-if="assistantResult" class="assistant-result">
        <div class="answer-card">
          <h3>智能体回答</h3>
          <p>{{ assistantResult.answer }}</p>
          <div v-if="assistantResult.actions?.length" class="question-list action-list">
            <el-button
              v-for="(action, index) in assistantResult.actions"
              :key="`${action.type}-${index}`"
              plain
              @click="handleAssistantAction(action)"
            >
              {{ action.label }}
            </el-button>
          </div>
        </div>
        <div class="step-card">
          <h3>推理步骤</h3>
          <div class="step-list">
            <div v-for="(step, index) in assistantResult.steps" :key="`${step.step}-${index}`" class="step-item">
              <strong>{{ step.step }}</strong>
              <span>{{ step.detail }}</span>
            </div>
          </div>
        </div>
      </div>

      <div v-if="assistantResult?.visualization" class="assistant-chart-card">
        <div ref="assistantChartRef" class="assistant-chart"></div>
      </div>

      <div v-if="assistantEvidenceCards.length > 0" class="assistant-evidence">
        <div class="section-head compact-head">
          <div>
            <h2>智能体证据</h2>
            <p>展示当前分析结论所关联的重点区域、设备和事件证据</p>
          </div>
        </div>
        <div class="evidence-grid">
          <div v-for="item in assistantEvidenceCards" :key="String(item.key)" class="evidence-card">
            <div class="evidence-meta">
              <strong>{{ item.title }}</strong>
            </div>
            <p>{{ item.summary || '—' }}</p>
            <div v-if="item.imageUrl || item.videoUrl" class="evidence-actions">
              <el-button v-if="item.imageUrl" link type="primary" @click="openMediaPreview('image', item.imageUrl, item.title, item.summary)">图片</el-button>
              <el-button v-if="item.videoUrl" link type="primary" @click="openMediaPreview('video', item.videoUrl, item.title, item.summary)">视频</el-button>
              <el-button v-if="item.eventId" link type="primary" @click="loadLineage(item.eventId)">血缘</el-button>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section v-if="graphData" ref="graphSectionRef" class="graph-section">
      <el-card shadow="never" class="panel-card wide-card">
        <template #header>
          <div class="section-head">
            <div>
              <h2>本体与知识图谱</h2>
              <p>以区域、设备、告警事件、图片、视频、建议动作为核心对象，构建可追溯的业务知识关联。</p>
            </div>
          </div>
        </template>

        <div class="ontology-grid">
          <div v-for="item in graphData.ontology" :key="item.type" class="ontology-card">
            <strong>{{ item.label }}</strong>
            <p>{{ item.description }}</p>
            <div class="tag-list compact">
              <el-tag v-for="field in item.key_fields" :key="field" size="small">{{ field }}</el-tag>
            </div>
          </div>
        </div>

        <div class="graph-layout">
          <div class="graph-pane">
            <div class="graph-stats">
              <div v-for="item in graphStatCards" :key="item.label" class="mini-stat">
                <span>{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
              </div>
            </div>
            <div ref="graphRef" class="graph-canvas"></div>
          </div>
          <div class="lineage-pane">
            <div v-if="selectedGraphNode" class="lineage-card selected-node-card">
              <div class="section-head compact-head">
                <div>
                  <h2>节点详情</h2>
                  <p>点击图谱中的区域、设备、事件、算法节点后可在此查看详情。</p>
                </div>
              </div>
              <div class="lineage-event-head">
                <strong>{{ selectedGraphNode.name || selectedGraphNode.label }}</strong>
                <span>类别：{{ selectedGraphNode.category }}</span>
              </div>
              <div class="lineage-evidence">
                <div v-for="(value, key) in (selectedGraphNode.meta || {})" :key="String(key)" class="lineage-evidence-item">
                  <span>{{ key }}</span>
                  <strong>{{ value }}</strong>
                </div>
              </div>
            </div>

            <div class="section-head compact-head">
              <div>
                <h2>事件血缘链</h2>
                <p>展示从原始事件到知识关联、风险分析、处置建议的全链路过程</p>
              </div>
            </div>

            <div v-if="lineageData" class="lineage-card">
              <div class="lineage-event-head">
                <strong>{{ lineageData.event.event_type }}</strong>
                <span>{{ lineageData.event.city_name }} / {{ lineageData.event.county_name }}</span>
                <span>置信度 {{ lineageData.event.confidence_level }}</span>
              </div>
              <div class="lineage-actions">
                <el-button
                  v-if="lineageData.event.image_url"
                  link
                  type="primary"
                  @click="openMediaPreview('image', lineageData.event.image_url, lineageData.event.event_type, lineageData.event.summary)"
                >
                  查看图片
                </el-button>
                <el-button
                  v-if="lineageData.event.video_url"
                  link
                  type="primary"
                  @click="openMediaPreview('video', lineageData.event.video_url, lineageData.event.event_type, lineageData.event.summary)"
                >
                  查看视频
                </el-button>
              </div>

              <div class="lineage-timeline">
                <div v-for="(item, index) in lineageData.timeline" :key="`${item.stage}-${index}`" class="lineage-step">
                  <div class="lineage-stage">{{ item.stage }}</div>
                  <div class="lineage-body">
                    <strong>{{ item.title }}</strong>
                    <p>{{ item.description }}</p>
                    <div class="lineage-evidence">
                      <div v-for="(value, key) in item.evidence" :key="String(key)" class="lineage-evidence-item">
                        <span>{{ key }}</span>
                        <strong>{{ value }}</strong>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div class="recommendation-banner">
                <strong>建议动作</strong>
                <p>{{ lineageData.recommendation.next_action }}</p>
              </div>
            </div>

            <div v-else class="empty-lineage">
              选择一条事件样本或点击图谱中的事件节点，可查看对应血缘链。
            </div>
          </div>
        </div>
      </el-card>
    </section>

    <section v-if="dashboard" class="content-grid">
      <el-card ref="hotRegionsRef" shadow="never" class="panel-card">
        <template #header>
          <div class="section-head">
            <div>
              <h2>区域热点</h2>
              <p>识别告警高发区域，为重点巡检和资源投放提供依据</p>
            </div>
          </div>
        </template>
        <div class="metric-list">
          <div v-for="item in dashboard.hot_regions.slice(0, 6)" :key="item.county_name" class="metric-item">
            <strong>{{ item.county_name }}</strong>
            <span>{{ item.count }} 次告警</span>
            <span>平均置信度 {{ item.avg_confidence }}</span>
            <span>风险分 {{ item.risk_score }}</span>
            <el-tag size="small" :type="item.priority === 'P1' ? 'danger' : item.priority === 'P2' ? 'warning' : 'info'">{{ item.priority }}</el-tag>
          </div>
        </div>
      </el-card>

      <el-card ref="hotDevicesRef" shadow="never" class="panel-card">
        <template #header>
          <div class="section-head">
            <div>
              <h2>设备热点</h2>
              <p>识别告警高频设备，为设备复核和巡检优先级排序提供支撑</p>
            </div>
          </div>
        </template>
        <div class="metric-list">
          <div v-for="item in dashboard.hot_devices.slice(0, 6)" :key="item.device_name" class="metric-item">
            <strong>{{ item.device_name }}</strong>
            <span>{{ item.count }} 次告警</span>
            <span>最近告警 {{ formatDateTime(item.last_alarm_time) }}</span>
            <span>风险分 {{ item.risk_score }}</span>
            <el-tag size="small" :type="item.priority === 'P1' ? 'danger' : item.priority === 'P2' ? 'warning' : 'info'">{{ item.priority }}</el-tag>
          </div>
        </div>
      </el-card>

      <el-card ref="recommendationsRef" shadow="never" class="panel-card wide-card">
        <template #header>
          <div class="section-head">
            <div>
              <h2>处置建议</h2>
              <p>结合热点区域、重点设备与疑似误报样本，输出可执行的处置动作建议</p>
            </div>
          </div>
        </template>
        <div class="recommendation-list">
          <div v-for="item in dashboard.recommendations" :key="item.title" class="recommendation-item">
            <div class="recommendation-top">
              <strong>{{ item.title }}</strong>
              <el-tag :type="item.priority === 'high' ? 'danger' : 'warning'">{{ item.priority }}</el-tag>
            </div>
            <p>{{ item.reason }}</p>
            <div class="recommendation-action">{{ item.action }}</div>
          </div>
        </div>
      </el-card>

      <el-card ref="priorityQueueRef" shadow="never" class="panel-card wide-card">
        <template #header>
          <div class="section-head">
            <div>
              <h2>处置优先队列</h2>
              <p>基于置信度、区域活跃度和设备活跃度形成的事件处置优先级排序</p>
            </div>
          </div>
        </template>
        <div class="evidence-grid">
          <div v-for="item in dashboard.priority_queue" :key="`priority-${item.event_id}`" class="evidence-card">
            <div v-if="item.image_url" class="evidence-thumb" @click="openMediaPreview('image', item.image_url, item.event_type, item.summary)">
              <img :src="item.image_url" :alt="item.event_type" />
            </div>
            <div class="evidence-meta">
              <strong>{{ item.event_type }}</strong>
              <el-tag :type="item.priority === 'P1' ? 'danger' : item.priority === 'P2' ? 'warning' : 'info'">{{ item.priority }}</el-tag>
            </div>
            <div class="priority-meta">
              <span>{{ item.city_name }} / {{ item.county_name }}</span>
              <span>风险分 {{ item.risk_score }}</span>
              <span>置信度 {{ item.confidence_level?.toFixed(3) }}</span>
            </div>
            <p>{{ item.summary || '无摘要' }}</p>
            <div class="recommendation-action">{{ item.action_type }}</div>
            <div class="evidence-actions">
              <el-button v-if="item.image_url" link type="primary" @click="openMediaPreview('image', item.image_url, item.event_type, item.summary)">图片</el-button>
              <el-button v-if="item.video_url" link type="primary" @click="openMediaPreview('video', item.video_url, item.event_type, item.summary)">视频</el-button>
              <el-button link type="primary" @click="loadLineage(item.event_id)">血缘</el-button>
            </div>
          </div>
        </div>
      </el-card>

      <el-card shadow="never" class="panel-card wide-card">
        <template #header>
          <div class="section-head">
            <div>
              <h2>低置信度事件样本</h2>
              <p>低置信度事件可作为人工复核、规则优化与样本治理的重要依据</p>
            </div>
          </div>
        </template>
        <div class="evidence-grid">
          <div v-for="item in dashboard.low_confidence_events.slice(0, 8)" :key="item.event_id" class="evidence-card">
            <div v-if="item.image_url" class="evidence-thumb" @click="openMediaPreview('image', item.image_url, item.event_type, item.summary)">
              <img :src="item.image_url" :alt="item.event_type" />
            </div>
            <div class="evidence-meta">
              <strong>{{ item.event_type }}</strong>
              <span>{{ item.city_name }} / {{ item.county_name }}</span>
              <span>置信度 {{ item.confidence_level?.toFixed(3) }}</span>
            </div>
            <p>{{ item.summary || '无摘要' }}</p>
            <div class="priority-meta">
              <span>风险分 {{ item.risk_score }}</span>
              <span>优先级 {{ item.priority }}</span>
              <span>{{ item.action_type }}</span>
            </div>
            <div class="evidence-actions">
              <el-button v-if="item.image_url" link type="primary" @click="openMediaPreview('image', item.image_url, item.event_type, item.summary)">查看图片</el-button>
              <el-button v-if="item.video_url" link type="primary" @click="openMediaPreview('video', item.video_url, item.event_type, item.summary)">查看视频</el-button>
              <el-button link type="primary" @click="loadLineage(item.event_id)">查看血缘</el-button>
            </div>
          </div>
        </div>
      </el-card>
    </section>

      </el-tab-pane>
      <el-tab-pane label="本体配置" name="ontology">
        <section ref="ontologySectionRef" class="ontology-config-page">
          <el-card shadow="never" class="panel-card">
            <template #header>
              <div class="section-head">
                <div>
                  <h2>本体配置中心</h2>
                  <p>以实体、关系和字段映射配置驱动图谱与血缘生成，体现平台可配置能力。</p>
                </div>
                <div class="header-actions">
                  <el-button @click="addEntity">新增实体</el-button>
                  <el-button @click="addRelation">新增关系</el-button>
                  <el-button @click="resetOntology">恢复默认</el-button>
                  <el-button type="primary" :loading="savingOntology" @click="saveOntology">保存配置</el-button>
                </div>
              </div>
            </template>

            <div v-if="ontologyConfig" class="ontology-config-layout">
              <div class="config-panel">
                <div class="config-block">
                  <div class="section-head compact-head">
                    <div>
                      <h2>实体类型</h2>
                      <p>定义平台中的核心业务对象、关键字段与来源字段。</p>
                    </div>
                  </div>

                  <div class="config-list">
                    <div v-for="(item, index) in ontologyConfig.entities" :key="`${item.type}-${index}`" class="config-card">
                      <div class="config-head">
                        <strong>{{ item.label }}</strong>
                        <div class="config-actions">
                          <el-switch v-model="item.enabled" active-text="启用" inactive-text="停用" />
                          <el-button text type="danger" @click="removeEntity(index)">删除</el-button>
                        </div>
                      </div>
                      <div class="two-col">
                        <el-form-item label="类型编码">
                          <el-input v-model="item.type" />
                        </el-form-item>
                        <el-form-item label="显示名称">
                          <el-input v-model="item.label" />
                        </el-form-item>
                      </div>
                      <el-form-item label="描述">
                        <el-input v-model="item.description" type="textarea" :rows="2" />
                      </el-form-item>
                      <el-form-item label="关键字段（逗号分隔）">
                        <el-input
                          :model-value="item.key_fields.join(', ')"
                          @update:model-value="(value: string) => item.key_fields = value.split(',').map(v => v.trim()).filter(Boolean)"
                        />
                      </el-form-item>
                      <el-form-item label="来源字段（逗号分隔）">
                        <el-input
                          :model-value="item.source_fields.join(', ')"
                          @update:model-value="(value: string) => item.source_fields = value.split(',').map(v => v.trim()).filter(Boolean)"
                        />
                      </el-form-item>
                    </div>
                  </div>
                </div>

                <div class="config-block">
                  <div class="section-head compact-head">
                    <div>
                      <h2>关系类型</h2>
                      <p>定义实体之间的关联规则，用于驱动图谱边与血缘链条。</p>
                    </div>
                  </div>

                  <div class="config-list">
                    <div v-for="(item, index) in ontologyConfig.relations" :key="`${item.type}-${index}`" class="config-card">
                      <div class="config-head">
                        <strong>{{ item.label }}</strong>
                        <div class="config-actions">
                          <el-switch v-model="item.enabled" active-text="启用" inactive-text="停用" />
                          <el-button text type="danger" @click="removeRelation(index)">删除</el-button>
                        </div>
                      </div>
                      <div class="three-col">
                        <el-form-item label="关系编码">
                          <el-input v-model="item.type" />
                        </el-form-item>
                        <el-form-item label="起点类型">
                          <el-input v-model="item.source_type" />
                        </el-form-item>
                        <el-form-item label="终点类型">
                          <el-input v-model="item.target_type" />
                        </el-form-item>
                      </div>
                      <el-form-item label="显示名称">
                        <el-input v-model="item.label" />
                      </el-form-item>
                      <el-form-item label="描述">
                        <el-input v-model="item.description" type="textarea" :rows="2" />
                      </el-form-item>
                      <el-form-item label="来源字段（可选）">
                        <el-input v-model="item.source_field" />
                      </el-form-item>
                    </div>
                  </div>
                </div>
              </div>

              <div class="config-preview-panel">
                <div class="section-head compact-head">
                  <div>
                    <h2>配置说明</h2>
                    <p>当前页面修改后会直接影响图谱与血缘生成逻辑。</p>
                  </div>
                </div>
                <div class="summary-block">
                  <h4>演示价值</h4>
                  <div class="recommendation-list">
                    <div class="recommendation-item">实体类型可配置：说明平台不是只服务单一场景，而是支持后续扩展到能源、工单、资源调度等业务对象。</div>
                    <div class="recommendation-item">关系规则可配置：说明图谱和血缘不是写死逻辑，而是可被业务规则驱动。</div>
                    <div class="recommendation-item">字段映射可配置：说明不同来源数据可以通过配置接入统一知识层，不依赖硬编码。</div>
                  </div>
                </div>
                <div class="summary-block">
                  <h4>当前配置规模</h4>
                  <div class="stat-grid compact-grid">
                    <div class="stat-card"><span>实体类型</span><strong>{{ ontologyConfig.entities.length }}</strong></div>
                    <div class="stat-card"><span>关系类型</span><strong>{{ ontologyConfig.relations.length }}</strong></div>
                    <div class="stat-card"><span>启用实体</span><strong>{{ ontologyConfig.entities.filter(item => item.enabled).length }}</strong></div>
                    <div class="stat-card"><span>启用关系</span><strong>{{ ontologyConfig.relations.filter(item => item.enabled).length }}</strong></div>
                  </div>
                </div>
              </div>
            </div>
          </el-card>
        </section>
      </el-tab-pane>
    </el-tabs>

    <el-dialog
      v-model="previewVisible"
      :title="previewTitle"
      width="900px"
      class="media-preview-dialog"
      destroy-on-close
    >
      <div class="media-preview-body">
        <img v-if="previewType === 'image'" :src="previewUrl" :alt="previewTitle" class="preview-image" />
        <video v-else :src="previewUrl" class="preview-video" controls autoplay />
        <div v-if="previewSummary" class="preview-summary">
          <strong>事件说明</strong>
          <p>{{ previewSummary }}</p>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
.tower-demo-page {
  min-height: 100%;
  padding: 24px;
  background:
    radial-gradient(circle at top right, rgba(59, 130, 246, 0.16), transparent 32%),
    linear-gradient(180deg, #f4f7fb 0%, #eef4fb 100%);
}

.tower-tabs {
  :deep(.el-tabs__header) {
    margin-bottom: 18px;
  }
}

.hero-card,
.assistant-card,
.panel-card {
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 20px;
  box-shadow: 0 18px 48px rgba(15, 23, 42, 0.06);
}

.hero-card {
  padding: 28px;
  display: grid;
  grid-template-columns: 1.4fr 0.9fr;
  gap: 24px;
  margin-bottom: 20px;
}

.eyebrow {
  display: inline-flex;
  padding: 6px 12px;
  border-radius: 999px;
  background: #dbeafe;
  color: #1d4ed8;
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 12px;
}

.hero-copy h1 {
  margin: 0 0 12px;
  font-size: 30px;
  line-height: 1.2;
  color: #0f172a;
}

.hero-copy p,
.section-head p,
.answer-card p,
.recommendation-item p,
.evidence-card p {
  margin: 0;
  line-height: 1.7;
  color: #475569;
}

.hero-stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.hero-stat {
  padding: 18px;
  border-radius: 18px;
  background: linear-gradient(180deg, #f8fbff 0%, #eef6ff 100%);
  border: 1px solid #dbeafe;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.hero-stat span {
  color: #64748b;
  font-size: 13px;
}

.hero-stat strong {
  font-size: 28px;
  color: #0f172a;
}

.assistant-card {
  padding: 24px;
  margin-bottom: 20px;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.header-actions,
.config-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.section-head h2 {
  margin: 0 0 6px;
  font-size: 18px;
  color: #0f172a;
}

.assistant-input {
  margin-top: 16px;
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 12px;
}

.question-list {
  margin-top: 14px;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.action-list {
  margin-top: 18px;
}

.assistant-result {
  margin-top: 18px;
  display: grid;
  grid-template-columns: 1.1fr 0.9fr;
  gap: 16px;
}

.assistant-evidence {
  margin-top: 18px;
}

.assistant-chart-card {
  margin-top: 18px;
  padding: 18px;
  border-radius: 16px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.assistant-chart {
  width: 100%;
  height: 360px;
}

.compact-head {
  margin-bottom: 12px;
}

.graph-section {
  margin-bottom: 20px;
}

.ontology-config-page {
  display: grid;
}

.ontology-config-layout {
  display: grid;
  grid-template-columns: 1.2fr 0.8fr;
  gap: 18px;
}

.config-panel,
.config-preview-panel {
  display: grid;
  gap: 16px;
}

.config-block {
  padding: 16px;
  border-radius: 18px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.two-col,
.three-col {
  display: grid;
  gap: 12px;
}

.two-col {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.three-col {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.config-list {
  display: grid;
  gap: 12px;
}

.config-card {
  padding: 14px;
  border-radius: 14px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
}

.config-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
}

.ontology-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 14px;
  margin-bottom: 18px;
}

.ontology-card {
  padding: 14px;
  border-radius: 16px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.ontology-card strong {
  display: block;
  margin-bottom: 8px;
  color: #0f172a;
}

.ontology-card p {
  margin: 0;
  color: #475569;
  line-height: 1.7;
}

.graph-layout {
  display: grid;
  grid-template-columns: 1.15fr 0.85fr;
  gap: 18px;
}

.graph-pane,
.lineage-pane {
  padding: 16px;
  border-radius: 18px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.graph-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}

.mini-stat {
  padding: 12px;
  border-radius: 14px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.compact-grid {
  margin-bottom: 0;
}

.mini-stat span {
  font-size: 12px;
  color: #64748b;
}

.mini-stat strong {
  font-size: 18px;
  color: #0f172a;
}

.graph-canvas {
  width: 100%;
  height: 520px;
}

.lineage-card {
  display: grid;
  gap: 14px;
}

.selected-node-card {
  margin-bottom: 14px;
}

.lineage-event-head {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 14px;
  border-radius: 14px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
}

.lineage-event-head strong {
  color: #0f172a;
}

.lineage-event-head span {
  color: #64748b;
  font-size: 13px;
}

.lineage-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.lineage-timeline {
  display: grid;
  gap: 12px;
}

.lineage-step {
  display: grid;
  grid-template-columns: 72px 1fr;
  gap: 12px;
}

.lineage-stage {
  display: inline-flex;
  align-items: flex-start;
  justify-content: center;
  padding: 8px 10px;
  border-radius: 999px;
  background: #dbeafe;
  color: #1d4ed8;
  font-size: 12px;
  font-weight: 600;
}

.lineage-body {
  padding: 14px;
  border-radius: 14px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
}

.lineage-body strong {
  display: block;
  margin-bottom: 8px;
  color: #0f172a;
}

.lineage-body p {
  margin: 0 0 10px;
  line-height: 1.7;
  color: #475569;
}

.lineage-evidence {
  display: grid;
  gap: 8px;
}

.lineage-evidence-item {
  display: grid;
  gap: 4px;
  padding: 8px 10px;
  border-radius: 10px;
  background: #f8fafc;
}

.lineage-evidence-item span {
  font-size: 12px;
  color: #64748b;
}

.lineage-evidence-item strong {
  margin: 0;
  color: #0f172a;
  word-break: break-word;
}

.recommendation-banner {
  padding: 14px;
  border-radius: 16px;
  background: linear-gradient(180deg, #eff6ff 0%, #dbeafe 100%);
  border: 1px solid #bfdbfe;
}

.recommendation-banner strong {
  display: block;
  margin-bottom: 8px;
  color: #1d4ed8;
}

.recommendation-banner p {
  margin: 0;
  color: #1e3a8a;
  line-height: 1.7;
}

.empty-lineage {
  min-height: 240px;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  color: #64748b;
}

.answer-card,
.step-card {
  padding: 18px;
  border-radius: 16px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.answer-card h3,
.step-card h3 {
  margin: 0 0 12px;
  color: #0f172a;
}

.step-list {
  display: grid;
  gap: 10px;
}

.step-item {
  padding: 10px 12px;
  border-left: 3px solid #3b82f6;
  background: #fff;
  display: grid;
  gap: 4px;
}

.content-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
}

.panel-card {
  min-height: 100%;
}

.wide-card {
  grid-column: span 2;
}

.metric-list,
.recommendation-list,
.evidence-grid {
  display: grid;
  gap: 12px;
}

.metric-item,
.recommendation-item,
.evidence-card {
  padding: 14px;
  border-radius: 14px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.metric-item {
  display: grid;
  gap: 6px;
}

.recommendation-top,
.evidence-meta {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.priority-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 8px;
  font-size: 12px;
  color: #64748b;
}

.recommendation-action {
  margin-top: 10px;
  padding: 10px 12px;
  border-radius: 12px;
  background: #eff6ff;
  color: #1d4ed8;
  line-height: 1.6;
}

.evidence-thumb {
  margin-bottom: 12px;
  border-radius: 12px;
  overflow: hidden;
  background: #e2e8f0;
  cursor: pointer;
}

.evidence-thumb img {
  display: block;
  width: 100%;
  aspect-ratio: 16 / 9;
  object-fit: cover;
}

.evidence-actions {
  margin-top: 12px;
  display: flex;
  gap: 10px;
}

.media-preview-body {
  display: grid;
  gap: 16px;
}

.preview-image,
.preview-video {
  width: 100%;
  max-height: 70vh;
  object-fit: contain;
  border-radius: 14px;
  background: #0f172a;
}

.preview-summary {
  padding: 14px;
  border-radius: 14px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.preview-summary strong {
  display: block;
  margin-bottom: 8px;
  color: #0f172a;
}

.preview-summary p {
  margin: 0;
  color: #475569;
  line-height: 1.7;
}

@media (max-width: 1100px) {
  .hero-card,
  .assistant-result,
  .content-grid,
  .graph-layout,
  .ontology-config-layout {
    grid-template-columns: 1fr;
  }

  .wide-card {
    grid-column: span 1;
  }
}

@media (max-width: 768px) {
  .tower-demo-page {
    padding: 16px;
  }

  .assistant-input {
    grid-template-columns: 1fr;
  }

  .hero-stats,
  .graph-stats,
  .compact-grid,
  .three-col {
    grid-template-columns: 1fr;
  }

  .lineage-step {
    grid-template-columns: 1fr;
  }
}
</style>
