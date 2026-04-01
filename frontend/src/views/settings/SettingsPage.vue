<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useUserStore } from '@/stores/user'
import { authApi, systemApi } from '@/api'
import type { SystemMonitorSummaryResponse } from '@/api/types'
import { ElMessage } from 'element-plus'
import { Refresh, Monitor, DataAnalysis, Connection, Tools, User, Plus } from '@element-plus/icons-vue'

const userStore = useUserStore()
const wsForm = ref({ name: '', description: '' })
const creating = ref(false)
const monitorLoading = ref(false)
const monitorSummary = ref<SystemMonitorSummaryResponse | null>(null)

const handleCreateWs = async () => {
  if (!wsForm.value.name) {
    ElMessage.warning('请输入工作空间名称')
    return
  }

  creating.value = true
  try {
    const res = await authApi.createWorkspace(wsForm.value)
    userStore.setWorkspaces([...userStore.workspaces, res.data])
    ElMessage.success('创建成功')
    wsForm.value = { name: '', description: '' }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '创建失败')
  } finally {
    creating.value = false
  }
}

const loadMonitorSummary = async () => {
  monitorLoading.value = true
  try {
    const res = await systemApi.getMonitorSummary()
    monitorSummary.value = res.data
  } catch (e: any) {
    console.error('加载系统监控失败:', e)
    ElMessage.error(e.response?.data?.detail || '加载系统监控失败')
  } finally {
    monitorLoading.value = false
  }
}

onMounted(() => {
  void loadMonitorSummary()
})

const intentStats = computed(() => {
  const byIntent = monitorSummary.value?.query_trace?.by_intent || {}
  return Object.entries(byIntent).map(([intent, count]) => ({ intent, count }))
})

const recentQueries = computed(() => monitorSummary.value?.query_trace?.recent_queries || [])
const externalServices = computed(() => monitorSummary.value?.external_services || [])
const toolRegistry = computed(() => monitorSummary.value?.tool_registry || [])
const dataStats = computed(() => monitorSummary.value?.data_stats)

const getServiceTagType = (status?: string) => {
  if (status === 'up') return 'success'
  if (status === 'degraded') return 'warning'
  if (status === 'unconfigured') return 'info'
  return 'danger'
}

const getTraceTagType = (status?: string) => {
  if (status === 'success') return 'success'
  if (status === 'error') return 'danger'
  return 'info'
}

const formatDuration = (value?: number) => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '-'
  return `${Math.round(value)} ms`
}

const formatPercent = (value?: number) => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '0%'
  return `${value.toFixed(1)}%`
}
</script>

<template>
  <div class="settings-page">
    <div class="settings-grid">
      <el-card class="panel-card">
        <template #header>
          <div class="card-title">
            <el-icon><User /></el-icon>
            <h3>用户信息</h3>
          </div>
        </template>
        <el-descriptions :column="1" border>
          <el-descriptions-item label="用户名">{{ userStore.userInfo?.username }}</el-descriptions-item>
          <el-descriptions-item label="邮箱">{{ userStore.userInfo?.email || '-' }}</el-descriptions-item>
          <el-descriptions-item label="姓名">{{ userStore.userInfo?.full_name || '-' }}</el-descriptions-item>
        </el-descriptions>
      </el-card>

      <el-card class="panel-card">
        <template #header>
          <div class="card-title">
            <el-icon><Plus /></el-icon>
            <h3>创建工作空间</h3>
          </div>
        </template>
        <el-form label-width="100px">
          <el-form-item label="名称">
            <el-input v-model="wsForm.name" placeholder="工作空间名称" />
          </el-form-item>
          <el-form-item label="描述">
            <el-input v-model="wsForm.description" type="textarea" :rows="2" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="creating" @click="handleCreateWs">创建</el-button>
          </el-form-item>
        </el-form>
      </el-card>
    </div>

    <el-card class="monitor-card">
      <template #header>
        <div class="monitor-header">
          <div class="card-title">
            <el-icon><Monitor /></el-icon>
            <h3>系统监控</h3>
          </div>
          <div class="monitor-actions">
            <span class="checked-at">最近刷新：{{ monitorSummary?.checked_at || '-' }}</span>
            <el-button :icon="Refresh" :loading="monitorLoading" @click="loadMonitorSummary">刷新</el-button>
          </div>
        </div>
      </template>

      <div class="monitor-section">
        <div class="section-header">
          <el-icon><DataAnalysis /></el-icon>
          <span>数据统计</span>
        </div>
        <div class="stats-grid">
          <div class="stat-item">
            <div class="stat-value">{{ dataStats?.workspace_count || 0 }}</div>
            <div class="stat-label">工作空间</div>
          </div>
          <div class="stat-item">
            <div class="stat-value">{{ dataStats?.data_source_count || 0 }}</div>
            <div class="stat-label">数据源</div>
          </div>
          <div class="stat-item">
            <div class="stat-value">{{ dataStats?.dataset_count || 0 }}</div>
            <div class="stat-label">数据集</div>
          </div>
          <div class="stat-item">
            <div class="stat-value">{{ dataStats?.workbench_dataset_count || 0 }}</div>
            <div class="stat-label">工作台数据集</div>
          </div>
          <div class="stat-item">
            <div class="stat-value">{{ dataStats?.query_history_count || 0 }}</div>
            <div class="stat-label">查询历史</div>
          </div>
          <div class="stat-item highlight">
            <div class="stat-value">{{ dataStats?.tower_events || 0 }}</div>
            <div class="stat-label">铁塔清洗事件</div>
          </div>
          <div class="stat-item">
            <div class="stat-value">{{ dataStats?.tower_assets || 0 }}</div>
            <div class="stat-label">铁塔清洗资产</div>
          </div>
          <div class="stat-item">
            <div class="stat-value">{{ dataStats?.tower_detections || 0 }}</div>
            <div class="stat-label">检测结果</div>
          </div>
        </div>
      </div>

      <div class="monitor-section">
        <div class="section-header">
          <el-icon><Connection /></el-icon>
          <span>查询追踪</span>
        </div>
        <div class="trace-overview">
          <el-tag type="info">总查询 {{ monitorSummary?.query_trace?.total_queries || 0 }}</el-tag>
          <el-tag type="success">成功 {{ monitorSummary?.query_trace?.success_count || 0 }}</el-tag>
          <el-tag type="danger">失败 {{ monitorSummary?.query_trace?.error_count || 0 }}</el-tag>
          <el-tag type="warning">成功率 {{ formatPercent(monitorSummary?.query_trace?.success_rate) }}</el-tag>
          <el-tag>平均耗时 {{ formatDuration(monitorSummary?.query_trace?.avg_duration_ms) }}</el-tag>
        </div>
        <el-table v-if="intentStats.length > 0" :data="intentStats" size="small" border class="table-block">
          <el-table-column prop="intent" label="意图" min-width="140" />
          <el-table-column prop="count" label="数量" width="100" />
        </el-table>
        <el-table v-if="recentQueries.length > 0" :data="recentQueries" size="small" border class="table-block">
          <el-table-column prop="timestamp" label="时间" width="180" />
          <el-table-column prop="question" label="问题" min-width="280" show-overflow-tooltip />
          <el-table-column prop="intent" label="意图" width="100" />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="getTraceTagType(row.status)">{{ row.status || '-' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="耗时" width="100">
            <template #default="{ row }">{{ formatDuration(row.duration_ms) }}</template>
          </el-table-column>
          <el-table-column prop="trace_id" label="Trace ID" min-width="180" show-overflow-tooltip />
        </el-table>
      </div>

      <div class="monitor-section">
        <div class="section-header">
          <el-icon><Tools /></el-icon>
          <span>Tool 注册中心</span>
        </div>
        <el-table :data="toolRegistry" size="small" border class="table-block">
          <el-table-column prop="name" label="名称" min-width="180" />
          <el-table-column prop="category" label="分类" width="140" />
          <el-table-column prop="description" label="描述" min-width="320" show-overflow-tooltip />
        </el-table>
      </div>

      <div class="monitor-section">
        <div class="section-header">
          <el-icon><Connection /></el-icon>
          <span>外部服务状态</span>
        </div>
        <el-table :data="externalServices" size="small" border class="table-block">
          <el-table-column prop="name" label="服务" min-width="180" />
          <el-table-column label="状态" width="130">
            <template #default="{ row }">
              <el-tag size="small" :type="getServiceTagType(row.status)">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="message" label="说明" min-width="180" />
          <el-table-column label="延迟" width="100">
            <template #default="{ row }">{{ formatDuration(row.latency_ms) }}</template>
          </el-table-column>
          <el-table-column prop="detail" label="详情" min-width="320" show-overflow-tooltip />
        </el-table>
      </div>
    </el-card>

    <el-card class="about-card">
      <template #header>
        <div class="card-title">
          <el-icon><Monitor /></el-icon>
          <h3>关于</h3>
        </div>
      </template>
      <p>智能问答平台 v1.0.0</p>
      <p class="about-desc">企业级自然语言数据查询、多模态检索、视联告警分析与数据工作台一体化平台。</p>
    </el-card>
  </div>
</template>

<style scoped lang="scss">
.settings-page {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.settings-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
}

.panel-card,
.monitor-card,
.about-card {
  border-radius: 14px;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;

  h3 {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
  }
}

.monitor-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.monitor-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.checked-at {
  font-size: 12px;
  color: #7a8599;
}

.monitor-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 18px 0;
  border-bottom: 1px solid #eef2f7;
}

.monitor-section:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: #2c3a4b;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.stat-item {
  padding: 14px;
  border-radius: 12px;
  background: #f7f9fc;
  border: 1px solid #ebeff5;
}

.stat-item.highlight {
  background: linear-gradient(135deg, #eef4ff 0%, #f8fbff 100%);
  border-color: #dbe6ff;
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: #22314a;
  line-height: 1.2;
}

.stat-label {
  margin-top: 6px;
  font-size: 12px;
  color: #6b778c;
}

.trace-overview {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.table-block {
  width: 100%;
}

.about-desc {
  color: #7a8599;
  font-size: 13px;
}

@media (max-width: 1200px) {
  .settings-grid,
  .stats-grid {
    grid-template-columns: 1fr;
  }

  .monitor-header {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
