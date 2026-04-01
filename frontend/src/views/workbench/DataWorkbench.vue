<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { workbenchApi } from '@/api'
import type {
  WorkbenchDataset,
  WorkbenchDatasetCreate,
  WorkbenchDatasetDetail,
  WorkbenchResource,
  WorkbenchSearchResult,
  WorkbenchSubscription,
  WorkbenchSubscriptionCreate,
} from '@/api/types'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()

const acceptTypes = '.zip,.txt,.md,.markdown,.json,.jsonl,.yaml,.yml,.xml,.html,.htm,.sql,.log,.csv,.tsv,.xlsx,.xls,.pdf,.docx'

const activeTab = ref('ingestion')
const loading = ref(false)
const creating = ref(false)
const importingSample = ref(false)
const searching = ref(false)
const processing = ref(false)
const datasets = ref<WorkbenchDataset[]>([])
const selectedDatasetId = ref<number | null>(null)
const selectedDataset = ref<WorkbenchDatasetDetail | null>(null)
const selectedFiles = ref<File[]>([])
const searchResults = ref<WorkbenchSearchResult[]>([])
const subscriptions = ref<WorkbenchSubscription[]>([])
const localPathInput = ref('')
const sftpPathInput = ref('')
const subscriptionPathInput = ref('')
const subscriptionSftpPathInput = ref('')
const creatingSubscription = ref(false)
const runningSubscriptionId = ref<number | null>(null)
let pollTimer: ReturnType<typeof setInterval> | null = null

const datasetForm = ref({
  name: '',
  description: '',
  file_paths: [] as string[],
  sftp_enabled: false,
  sftp: {
    host: '',
    port: 22,
    username: '',
    password: '',
    remote_paths: [] as string[],
    recursive: true,
  },
})

const searchForm = ref({
  query: '',
  top_k: 8,
})

const processingForm = ref({
  extract_labels: true,
  cluster_count: 4,
  refresh_summary: true,
})

const subscriptionForm = ref({
  name: '',
  source_kind: 'path' as 'path' | 'sftp',
  interval_minutes: 60,
  is_enabled: true,
  local_paths: [] as string[],
  sftp: {
    host: '',
    port: 22,
    username: '',
    password: '',
    remote_paths: [] as string[],
    recursive: true,
  },
})

const canCreateDataset = computed(() => {
  const hasInput =
    selectedFiles.value.length > 0 ||
    datasetForm.value.file_paths.length > 0 ||
    (datasetForm.value.sftp_enabled && datasetForm.value.sftp.remote_paths.length > 0)
  return Boolean(userStore.currentWorkspace && datasetForm.value.name.trim() && hasInput)
})

const canCreateSubscription = computed(() => {
  if (!userStore.currentWorkspace || !selectedDataset.value || !subscriptionForm.value.name.trim()) {
    return false
  }
  if (subscriptionForm.value.source_kind === 'path') {
    return subscriptionForm.value.local_paths.length > 0
  }
  return Boolean(
    subscriptionForm.value.sftp.host.trim() &&
    subscriptionForm.value.sftp.username.trim() &&
    subscriptionForm.value.sftp.remote_paths.length > 0
  )
})

const hasProcessingDataset = computed(() => {
  return datasets.value.some(item => ['pending', 'processing'].includes(item.processing_status))
})

const processingSummary = computed<Record<string, any> | null>(() => {
  return (selectedDataset.value?.processing_summary as Record<string, any> | undefined) || null
})

const resetForm = () => {
  datasetForm.value = {
    name: '',
    description: '',
    file_paths: [],
    sftp_enabled: false,
    sftp: {
      host: '',
      port: 22,
      username: '',
      password: '',
      remote_paths: [],
      recursive: true,
    },
  }
  selectedFiles.value = []
  localPathInput.value = ''
  sftpPathInput.value = ''
}

const resetSubscriptionForm = () => {
  subscriptionForm.value = {
    name: '',
    source_kind: 'path',
    interval_minutes: 60,
    is_enabled: true,
    local_paths: [],
    sftp: {
      host: '',
      port: 22,
      username: '',
      password: '',
      remote_paths: [],
      recursive: true,
    },
  }
  subscriptionPathInput.value = ''
  subscriptionSftpPathInput.value = ''
}

const syncPolling = () => {
  if (hasProcessingDataset.value && !pollTimer) {
    pollTimer = setInterval(() => {
      void loadDatasets(true)
      if (selectedDatasetId.value) {
        void loadDatasetDetail(selectedDatasetId.value, true)
        void loadSubscriptions(true)
      }
    }, 5000)
    return
  }

  if (!hasProcessingDataset.value && pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

const loadDatasets = async (silent = false) => {
  if (!userStore.currentWorkspace) return
  loading.value = true
  try {
    const res = await workbenchApi.listDatasets(userStore.currentWorkspace.id)
    datasets.value = res.data
    if (!selectedDatasetId.value && datasets.value.length > 0) {
      selectedDatasetId.value = datasets.value[0].id
    }
    syncPolling()
  } catch (error) {
    if (!silent) {
      ElMessage.error('加载工作台数据失败')
    }
    console.error(error)
  } finally {
    loading.value = false
  }
}

const loadDatasetDetail = async (datasetId: number, silent = false) => {
  try {
    const res = await workbenchApi.getDataset(datasetId)
    selectedDataset.value = res.data
    selectedDatasetId.value = datasetId
  } catch (error) {
    if (!silent) {
      ElMessage.error('加载数据集详情失败')
    }
    console.error(error)
  }
}

const loadSubscriptions = async (silent = false) => {
  if (!userStore.currentWorkspace || !selectedDatasetId.value) {
    subscriptions.value = []
    return
  }
  try {
    const res = await workbenchApi.listSubscriptions(userStore.currentWorkspace.id, selectedDatasetId.value)
    subscriptions.value = res.data
  } catch (error) {
    if (!silent) {
      ElMessage.error('加载订阅失败')
    }
    console.error(error)
  }
}

const handleLocalFileChange = (uploadFile: any) => {
  const file = uploadFile?.raw as File | undefined
  if (!file) return
  if (!acceptTypes.toLowerCase().split(',').some(ext => file.name.toLowerCase().endsWith(ext.trim()))) {
    ElMessage.warning('当前版本只支持文档、表格和压缩包采集')
    return
  }
  selectedFiles.value.push(file)
}

const removeSelectedFile = (index: number) => {
  selectedFiles.value.splice(index, 1)
}

const addLocalPath = () => {
  const value = localPathInput.value.trim()
  if (!value) return
  if (!datasetForm.value.file_paths.includes(value)) {
    datasetForm.value.file_paths.push(value)
  }
  localPathInput.value = ''
}

const removeLocalPath = (index: number) => {
  datasetForm.value.file_paths.splice(index, 1)
}

const addSftpPath = () => {
  const value = sftpPathInput.value.trim()
  if (!value) return
  if (!datasetForm.value.sftp.remote_paths.includes(value)) {
    datasetForm.value.sftp.remote_paths.push(value)
  }
  sftpPathInput.value = ''
}

const removeSftpPath = (index: number) => {
  datasetForm.value.sftp.remote_paths.splice(index, 1)
}

const addSubscriptionPath = () => {
  const value = subscriptionPathInput.value.trim()
  if (!value) return
  if (!subscriptionForm.value.local_paths.includes(value)) {
    subscriptionForm.value.local_paths.push(value)
  }
  subscriptionPathInput.value = ''
}

const removeSubscriptionPath = (index: number) => {
  subscriptionForm.value.local_paths.splice(index, 1)
}

const addSubscriptionSftpPath = () => {
  const value = subscriptionSftpPathInput.value.trim()
  if (!value) return
  if (!subscriptionForm.value.sftp.remote_paths.includes(value)) {
    subscriptionForm.value.sftp.remote_paths.push(value)
  }
  subscriptionSftpPathInput.value = ''
}

const removeSubscriptionSftpPath = (index: number) => {
  subscriptionForm.value.sftp.remote_paths.splice(index, 1)
}

const buildSubscriptionPayload = (): WorkbenchSubscriptionCreate => {
  return {
    workspace_id: userStore.currentWorkspace!.id,
    dataset_id: selectedDataset.value!.id,
    name: subscriptionForm.value.name.trim(),
    source_kind: subscriptionForm.value.source_kind,
    interval_minutes: subscriptionForm.value.interval_minutes,
    is_enabled: subscriptionForm.value.is_enabled,
    local_paths: subscriptionForm.value.source_kind === 'path' ? subscriptionForm.value.local_paths : [],
    sftp_config: subscriptionForm.value.source_kind === 'sftp'
      ? { ...subscriptionForm.value.sftp }
      : undefined,
  }
}

const buildCreatePayload = (): WorkbenchDatasetCreate => {
  return {
    workspace_id: userStore.currentWorkspace!.id,
    name: datasetForm.value.name.trim(),
    description: datasetForm.value.description.trim() || undefined,
    file_paths: datasetForm.value.file_paths,
    sftp_config: datasetForm.value.sftp_enabled && datasetForm.value.sftp.remote_paths.length > 0
      ? { ...datasetForm.value.sftp }
      : undefined,
  }
}

const buildCreateFormData = (payload: WorkbenchDatasetCreate) => {
  const formData = new FormData()
  formData.append('payload', JSON.stringify(payload))
  selectedFiles.value.forEach(file => formData.append('files', file))
  return formData
}

const createDataset = async () => {
  if (!canCreateDataset.value) {
    ElMessage.warning('请填写数据集名称并至少提供一种采集来源')
    return
  }
  creating.value = true
  try {
    const payload = buildCreatePayload()
    const requestBody = selectedFiles.value.length > 0 ? buildCreateFormData(payload) : payload
    const res = await workbenchApi.createDataset(requestBody)
    ElMessage.success('数据采集任务已创建，正在进行解析和向量化')
    resetForm()
    await loadDatasets(true)
    await loadDatasetDetail(res.data.id, true)
    await loadSubscriptions(true)
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '创建数据集失败')
  } finally {
    creating.value = false
  }
}

const importTowerSample = async () => {
  if (!userStore.currentWorkspace) {
    ElMessage.warning('请先选择工作空间')
    return
  }
  importingSample.value = true
  try {
    const res = await workbenchApi.importTowerWarningSample({
      workspace_id: userStore.currentWorkspace.id,
      name: '铁塔视联告警样本',
      description: '基于甲方提供的视联告警图片、视频与事件元数据构建的演示数据集',
      max_records: 200,
    })
    ElMessage.success('甲方样本数据导入任务已创建')
    await loadDatasets(true)
    await loadDatasetDetail(res.data.id, true)
    await loadSubscriptions(true)
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '导入甲方样本失败')
  } finally {
    importingSample.value = false
  }
}

const createSubscription = async () => {
  if (!canCreateSubscription.value) {
    ElMessage.warning('请补齐订阅名称和订阅源')
    return
  }
  creatingSubscription.value = true
  try {
    await workbenchApi.createSubscription(buildSubscriptionPayload())
    ElMessage.success('订阅已创建')
    resetSubscriptionForm()
    await loadSubscriptions(true)
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '创建订阅失败')
  } finally {
    creatingSubscription.value = false
  }
}

const toggleSubscription = async (subscription: WorkbenchSubscription, enabled: boolean) => {
  try {
    const res = await workbenchApi.updateSubscription(subscription.id, { is_enabled: enabled })
    const index = subscriptions.value.findIndex(item => item.id === subscription.id)
    if (index >= 0) {
      subscriptions.value[index] = res.data
    }
  } catch (error: any) {
    subscription.is_enabled = !enabled
    ElMessage.error(error.response?.data?.detail || '更新订阅失败')
  }
}

const runSubscription = async (subscription: WorkbenchSubscription) => {
  runningSubscriptionId.value = subscription.id
  try {
    const res = await workbenchApi.runSubscription(subscription.id)
    const index = subscriptions.value.findIndex(item => item.id === subscription.id)
    if (index >= 0) {
      subscriptions.value[index] = res.data
    }
    ElMessage.success('订阅执行完成')
    await loadDatasets(true)
    if (selectedDatasetId.value) {
      await loadDatasetDetail(selectedDatasetId.value, true)
    }
    await loadSubscriptions(true)
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '执行订阅失败')
  } finally {
    runningSubscriptionId.value = null
  }
}

const removeSubscription = async (subscription: WorkbenchSubscription) => {
  try {
    await ElMessageBox.confirm(`确认删除订阅“${subscription.name}”吗？`, '删除确认', { type: 'warning' })
    await workbenchApi.deleteSubscription(subscription.id)
    ElMessage.success('订阅已删除')
    await loadSubscriptions(true)
  } catch (error) {
    if (error !== 'cancel') {
      console.error(error)
    }
  }
}

const searchDataset = async () => {
  if (!selectedDatasetId.value || !searchForm.value.query.trim()) {
    ElMessage.warning('请输入检索词')
    return
  }
  searching.value = true
  try {
    const res = await workbenchApi.searchDataset(selectedDatasetId.value, {
      query: searchForm.value.query.trim(),
      top_k: searchForm.value.top_k,
    })
    searchResults.value = res.data
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '检索失败')
  } finally {
    searching.value = false
  }
}

const processDataset = async () => {
  if (!selectedDatasetId.value) {
    ElMessage.warning('请先选择数据集')
    return
  }
  processing.value = true
  try {
    const res = await workbenchApi.processDataset(selectedDatasetId.value, {
      extract_labels: processingForm.value.extract_labels,
      cluster_count: processingForm.value.cluster_count,
      refresh_summary: processingForm.value.refresh_summary,
    })
    selectedDataset.value = res.data
    ElMessage.success('数据处理完成')
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '数据处理失败')
  } finally {
    processing.value = false
  }
}

const downloadBlob = (blob: Blob, fileName: string) => {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

const exportDataset = async () => {
  if (!selectedDatasetId.value) return
  const res = await workbenchApi.exportDataset(selectedDatasetId.value)
  downloadBlob(res.data, `workbench-dataset-${selectedDatasetId.value}.json`)
}

const downloadResource = async (resource: WorkbenchResource) => {
  if (!selectedDatasetId.value) return
  const res = await workbenchApi.downloadResource(selectedDatasetId.value, resource.id)
  downloadBlob(res.data, resource.file_name)
}

const removeDataset = async () => {
  if (!selectedDataset.value) return
  try {
    await ElMessageBox.confirm(`确认删除数据集“${selectedDataset.value.name}”吗？`, '删除确认', { type: 'warning' })
    await workbenchApi.deleteDataset(selectedDataset.value.id)
    ElMessage.success('数据集已删除')
    searchResults.value = []
    selectedDataset.value = null
    selectedDatasetId.value = null
    await loadDatasets(true)
    if (datasets.value.length > 0) {
      await loadDatasetDetail(datasets.value[0].id, true)
    }
  } catch (error) {
    if (error !== 'cancel') {
      console.error(error)
    }
  }
}

const formatFileSize = (size?: number) => {
  if (!size) return '0 B'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  if (size < 1024 * 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`
  return `${(size / 1024 / 1024 / 1024).toFixed(1)} GB`
}

const formatDateTime = (value?: string) => value ? new Date(value).toLocaleString() : '-'

const statusLabel = (status: WorkbenchDataset['processing_status'] | WorkbenchResource['status']) => {
  if (status === 'ready') return '已完成'
  if (status === 'processing') return '处理中'
  if (status === 'failed') return '失败'
  return '待处理'
}

const statusTagType = (status: WorkbenchDataset['processing_status'] | WorkbenchResource['status']) => {
  if (status === 'ready') return 'success'
  if (status === 'processing') return 'warning'
  if (status === 'failed') return 'danger'
  return 'info'
}

watch(() => userStore.currentWorkspace?.id, async () => {
  searchResults.value = []
  subscriptions.value = []
  selectedDataset.value = null
  selectedDatasetId.value = null
  resetSubscriptionForm()
  await loadDatasets(true)
  if (selectedDatasetId.value) {
    await loadDatasetDetail(selectedDatasetId.value, true)
    await loadSubscriptions(true)
  }
})

watch(selectedDatasetId, async (value) => {
  searchResults.value = []
  resetSubscriptionForm()
  if (value) {
    await loadDatasetDetail(value, true)
    await loadSubscriptions(true)
  } else {
    subscriptions.value = []
  }
})

onMounted(async () => {
  await loadDatasets(true)
  if (selectedDatasetId.value) {
    await loadDatasetDetail(selectedDatasetId.value, true)
    await loadSubscriptions(true)
  }
})

onUnmounted(() => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
})
</script>

<template>
  <div class="workbench-page" v-loading="loading">
    <el-tabs v-model="activeTab" class="workbench-tabs">
      <el-tab-pane label="数据采集" name="ingestion">
        <div class="workbench-grid">
          <section class="left-panel">
            <el-card shadow="never" class="panel-card">
              <template #header>
                <div class="card-header">
                  <span>创建采集数据集</span>
                </div>
              </template>

              <el-form label-position="top" class="dataset-form">
                <el-form-item label="数据集名称">
                  <el-input v-model="datasetForm.name" placeholder="例如：合同资料库 / 财务周报 / 招投标档案" />
                </el-form-item>
                <el-form-item label="说明">
                  <el-input v-model="datasetForm.description" type="textarea" :rows="3" placeholder="描述数据来源、用途和范围" />
                </el-form-item>

                <el-form-item label="本地上传">
                  <el-upload :auto-upload="false" :show-file-list="false" :accept="acceptTypes" :on-change="handleLocalFileChange">
                    <el-button type="primary">添加文件</el-button>
                  </el-upload>
                  <div v-if="selectedFiles.length > 0" class="tag-list">
                    <el-tag v-for="(file, index) in selectedFiles" :key="`${file.name}-${index}`" closable @close="removeSelectedFile(index)">
                      {{ file.name }}
                    </el-tag>
                  </div>
                </el-form-item>

                <el-form-item label="服务器本地路径">
                  <div class="inline-input">
                    <el-input v-model="localPathInput" placeholder="输入文件或目录路径" @keyup.enter="addLocalPath" />
                    <el-button @click="addLocalPath">添加</el-button>
                  </div>
                  <div v-if="datasetForm.file_paths.length > 0" class="tag-list">
                    <el-tag v-for="(path, index) in datasetForm.file_paths" :key="`${path}-${index}`" closable @close="removeLocalPath(index)">
                      {{ path }}
                    </el-tag>
                  </div>
                </el-form-item>

                <el-divider>可选：SFTP 采集</el-divider>

                <el-form-item>
                  <el-switch v-model="datasetForm.sftp_enabled" active-text="启用 SFTP" inactive-text="关闭 SFTP" />
                </el-form-item>

                <template v-if="datasetForm.sftp_enabled">
                  <div class="two-col">
                    <el-form-item label="主机">
                      <el-input v-model="datasetForm.sftp.host" placeholder="10.0.0.8" />
                    </el-form-item>
                    <el-form-item label="端口">
                      <el-input-number v-model="datasetForm.sftp.port" :min="1" :max="65535" style="width: 100%" />
                    </el-form-item>
                  </div>
                  <div class="two-col">
                    <el-form-item label="用户名">
                      <el-input v-model="datasetForm.sftp.username" placeholder="sftp-user" />
                    </el-form-item>
                    <el-form-item label="密码">
                      <el-input v-model="datasetForm.sftp.password" type="password" show-password placeholder="输入 SFTP 密码" />
                    </el-form-item>
                  </div>
                  <el-form-item label="远程路径">
                    <div class="inline-input">
                      <el-input v-model="sftpPathInput" placeholder="/data/contracts 或 /data/archive.zip" @keyup.enter="addSftpPath" />
                      <el-button @click="addSftpPath">添加</el-button>
                    </div>
                    <div v-if="datasetForm.sftp.remote_paths.length > 0" class="tag-list">
                      <el-tag v-for="(path, index) in datasetForm.sftp.remote_paths" :key="`${path}-${index}`" closable @close="removeSftpPath(index)">
                        {{ path }}
                      </el-tag>
                    </div>
                  </el-form-item>
                  <el-form-item>
                    <el-checkbox v-model="datasetForm.sftp.recursive">目录递归采集</el-checkbox>
                  </el-form-item>
                </template>

                <el-button type="primary" :loading="creating" :disabled="!canCreateDataset" @click="createDataset">
                  创建并开始入库
                </el-button>
                <el-button :loading="importingSample" @click="importTowerSample">
                  导入甲方样本数据
                </el-button>
              </el-form>
            </el-card>

            <el-card shadow="never" class="panel-card">
              <template #header>
                <div class="card-header">
                  <span>数据集列表</span>
                  <span class="sub-text">{{ datasets.length }} 个</span>
                </div>
              </template>

              <div v-if="datasets.length === 0" class="empty-state">还没有数据工作台数据集</div>
              <div v-else class="dataset-list">
                <button
                  v-for="dataset in datasets"
                  :key="dataset.id"
                  type="button"
                  class="dataset-item"
                  :class="{ active: selectedDatasetId === dataset.id }"
                  @click="selectedDatasetId = dataset.id"
                >
                  <div class="dataset-item-head">
                    <strong>{{ dataset.name }}</strong>
                    <el-tag size="small" :type="statusTagType(dataset.processing_status)">{{ statusLabel(dataset.processing_status) }}</el-tag>
                  </div>
                  <div class="dataset-item-meta">
                    <span>{{ dataset.resource_count }} 文件</span>
                    <span>{{ dataset.chunk_count }} 分块</span>
                    <span>{{ formatDateTime(dataset.updated_at) }}</span>
                  </div>
                </button>
              </div>
            </el-card>
          </section>

          <section class="right-panel">
            <el-card v-if="selectedDataset" shadow="never" class="panel-card">
              <template #header>
                <div class="card-header">
                  <div>
                    <div class="dataset-title">{{ selectedDataset.name }}</div>
                    <div class="sub-text">{{ selectedDataset.description || '未填写描述' }}</div>
                  </div>
                  <div class="header-actions">
                    <el-button @click="exportDataset">导出</el-button>
                    <el-button type="danger" plain @click="removeDataset">删除</el-button>
                  </div>
                </div>
              </template>

              <div class="stat-grid">
                <div class="stat-card"><span>资源数</span><strong>{{ selectedDataset.resource_count }}</strong></div>
                <div class="stat-card"><span>向量块</span><strong>{{ selectedDataset.chunk_count }}</strong></div>
                <div class="stat-card"><span>向量数</span><strong>{{ selectedDataset.vector_count }}</strong></div>
                <div class="stat-card"><span>文本长度</span><strong>{{ selectedDataset.total_text_length }}</strong></div>
              </div>

              <div class="search-bar">
                <el-input v-model="searchForm.query" placeholder="输入问题，检索向量化后的文档内容" @keyup.enter="searchDataset" />
                <el-input-number v-model="searchForm.top_k" :min="1" :max="20" />
                <el-button type="primary" :loading="searching" @click="searchDataset">检索</el-button>
              </div>

              <div v-if="searchResults.length > 0" class="search-results">
                <div v-for="item in searchResults" :key="item.chunk_id" class="result-card">
                  <div class="result-head">
                    <strong>{{ item.file_name }}</strong>
                    <span>Score {{ item.score.toFixed(3) }}</span>
                  </div>
                  <div class="result-source">{{ item.source_uri }}</div>
                  <p class="result-content">{{ item.content }}</p>
                  <div v-if="item.keywords.length > 0" class="tag-list compact">
                    <el-tag v-for="keyword in item.keywords" :key="keyword" size="small">{{ keyword }}</el-tag>
                  </div>
                </div>
              </div>

              <el-table :data="selectedDataset.resources" class="resource-table">
                <el-table-column prop="file_name" label="文件名" min-width="220" />
                <el-table-column prop="source_kind" label="来源" width="100" />
                <el-table-column prop="file_category" label="类型" width="120" />
                <el-table-column label="状态" width="110">
                  <template #default="{ row }">
                    <el-tag size="small" :type="statusTagType(row.status)">{{ statusLabel(row.status) }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="大小" width="110">
                  <template #default="{ row }">{{ formatFileSize(row.file_size) }}</template>
                </el-table-column>
                <el-table-column prop="chunk_count" label="分块数" width="90" />
                <el-table-column prop="text_length" label="文本长度" width="110" />
                <el-table-column label="操作" width="100">
                  <template #default="{ row }">
                    <el-button link type="primary" @click="downloadResource(row)">下载</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </el-card>

            <el-card v-else shadow="never" class="panel-card empty-detail">
              <div class="empty-state">选择一个数据集后，可查看采集结果、文件列表和向量检索结果。</div>
            </el-card>
          </section>
        </div>
      </el-tab-pane>

      <el-tab-pane label="数据处理" name="processing">
        <el-card shadow="never" class="panel-card">
          <template #header>
            <div class="card-header">
              <div>
                <span>清洗增强与标签处理</span>
                <div class="sub-text">{{ selectedDataset ? `当前数据集：${selectedDataset.name}` : '请先选择数据集' }}</div>
              </div>
              <el-button type="primary" :loading="processing" :disabled="!selectedDataset" @click="processDataset">
                运行数据处理
              </el-button>
            </div>
          </template>

          <div v-if="selectedDataset" class="processing-panel">
            <div class="three-col">
              <el-form-item label="聚类数量">
                <el-input-number v-model="processingForm.cluster_count" :min="1" :max="12" style="width: 100%" />
              </el-form-item>
              <el-form-item label="标签抽取">
                <el-switch v-model="processingForm.extract_labels" active-text="启用" inactive-text="关闭" />
              </el-form-item>
              <el-form-item label="刷新摘要">
                <el-switch v-model="processingForm.refresh_summary" active-text="启用" inactive-text="关闭" />
              </el-form-item>
            </div>

            <div v-if="processingSummary" class="processing-summary">
              <div class="stat-grid">
                <div class="stat-card"><span>平均质量</span><strong>{{ processingSummary.avg_quality_score ?? '-' }}</strong></div>
                <div class="stat-card"><span>重复块</span><strong>{{ processingSummary.duplicate_chunk_count ?? 0 }}</strong></div>
                <div class="stat-card"><span>处理资源</span><strong>{{ processingSummary.resource_count ?? selectedDataset.resource_count }}</strong></div>
                <div class="stat-card"><span>处理时间</span><strong>{{ formatDateTime(processingSummary.processed_at || selectedDataset.processing_updated_at) }}</strong></div>
              </div>

              <div class="summary-block">
                <h4>Top Labels</h4>
                <div class="tag-list">
                  <el-tag
                    v-for="item in (processingSummary.top_labels || [])"
                    :key="item.label"
                    size="small"
                  >
                    {{ item.label }} · {{ item.count }}
                  </el-tag>
                </div>
              </div>

              <div class="summary-block">
                <h4>分类分布</h4>
                <div class="tag-list">
                  <el-tag
                    v-for="(count, category) in (processingSummary.category_distribution || {})"
                    :key="String(category)"
                    size="small"
                    type="success"
                  >
                    {{ category }} · {{ count }}
                  </el-tag>
                </div>
              </div>

              <div class="summary-block">
                <h4>语义聚类</h4>
                <div class="cluster-list">
                  <div v-for="cluster in (processingSummary.clusters || [])" :key="cluster.cluster_id" class="cluster-card">
                    <strong>#{{ cluster.cluster_id }} {{ cluster.label }}</strong>
                    <div class="sub-text">{{ cluster.resource_count }} 个资源</div>
                  </div>
                </div>
              </div>

              <div v-if="(processingSummary.recommendations || []).length > 0" class="summary-block">
                <h4>处理建议</h4>
                <div class="recommendation-list">
                  <div v-for="(item, index) in processingSummary.recommendations" :key="index" class="recommendation-item">
                    {{ item }}
                  </div>
                </div>
              </div>
            </div>

            <el-table :data="selectedDataset.resources" class="resource-table">
              <el-table-column prop="file_name" label="文件名" min-width="200" />
              <el-table-column prop="category_label" label="分类" width="120" />
              <el-table-column prop="cluster_label" label="聚类" min-width="160" />
              <el-table-column label="质量分" width="110">
                <template #default="{ row }">{{ row.quality_score ?? '-' }}</template>
              </el-table-column>
              <el-table-column label="标签" min-width="220">
                <template #default="{ row }">
                  <div class="tag-list compact">
                    <el-tag v-for="label in (row.labels || [])" :key="label" size="small">{{ label }}</el-tag>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="摘要" min-width="300">
                <template #default="{ row }">
                  <div class="summary-text-cell">{{ row.summary_text || '-' }}</div>
                </template>
              </el-table-column>
            </el-table>
          </div>
          <div v-else class="empty-state">先在“数据采集”页签中选择一个数据集，再运行清洗增强、标签抽取和聚类。</div>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="数据管理" name="management">
        <div class="workbench-grid">
          <section class="left-panel">
            <el-card shadow="never" class="panel-card">
              <template #header>
                <div class="card-header">
                  <span>订阅管理</span>
                  <span class="sub-text">{{ selectedDataset ? `当前数据集：${selectedDataset.name}` : '请先选择数据集' }}</span>
                </div>
              </template>

              <el-form label-position="top" class="dataset-form">
                <el-form-item label="订阅名称">
                  <el-input v-model="subscriptionForm.name" placeholder="例如：合同库每小时同步 / 财报目录巡检" />
                </el-form-item>
                <div class="two-col">
                  <el-form-item label="订阅源类型">
                    <el-select v-model="subscriptionForm.source_kind">
                      <el-option label="服务器路径" value="path" />
                      <el-option label="SFTP" value="sftp" />
                    </el-select>
                  </el-form-item>
                  <el-form-item label="同步频率（分钟）">
                    <el-input-number v-model="subscriptionForm.interval_minutes" :min="1" :max="10080" style="width: 100%" />
                  </el-form-item>
                </div>
                <el-form-item>
                  <el-switch v-model="subscriptionForm.is_enabled" active-text="创建后启用" inactive-text="创建后暂停" />
                </el-form-item>

                <template v-if="subscriptionForm.source_kind === 'path'">
                  <el-form-item label="订阅路径">
                    <div class="inline-input">
                      <el-input v-model="subscriptionPathInput" placeholder="输入要持续扫描的文件或目录路径" @keyup.enter="addSubscriptionPath" />
                      <el-button @click="addSubscriptionPath">添加</el-button>
                    </div>
                    <div v-if="subscriptionForm.local_paths.length > 0" class="tag-list">
                      <el-tag v-for="(path, index) in subscriptionForm.local_paths" :key="`${path}-${index}`" closable @close="removeSubscriptionPath(index)">
                        {{ path }}
                      </el-tag>
                    </div>
                  </el-form-item>
                </template>

                <template v-else>
                  <div class="two-col">
                    <el-form-item label="主机">
                      <el-input v-model="subscriptionForm.sftp.host" placeholder="10.0.0.8" />
                    </el-form-item>
                    <el-form-item label="端口">
                      <el-input-number v-model="subscriptionForm.sftp.port" :min="1" :max="65535" style="width: 100%" />
                    </el-form-item>
                  </div>
                  <div class="two-col">
                    <el-form-item label="用户名">
                      <el-input v-model="subscriptionForm.sftp.username" placeholder="sftp-user" />
                    </el-form-item>
                    <el-form-item label="密码">
                      <el-input v-model="subscriptionForm.sftp.password" type="password" show-password placeholder="输入 SFTP 密码" />
                    </el-form-item>
                  </div>
                  <el-form-item label="远程路径">
                    <div class="inline-input">
                      <el-input v-model="subscriptionSftpPathInput" placeholder="/data/contracts 或 /data/archive.zip" @keyup.enter="addSubscriptionSftpPath" />
                      <el-button @click="addSubscriptionSftpPath">添加</el-button>
                    </div>
                    <div v-if="subscriptionForm.sftp.remote_paths.length > 0" class="tag-list">
                      <el-tag v-for="(path, index) in subscriptionForm.sftp.remote_paths" :key="`${path}-${index}`" closable @close="removeSubscriptionSftpPath(index)">
                        {{ path }}
                      </el-tag>
                    </div>
                  </el-form-item>
                  <el-form-item>
                    <el-checkbox v-model="subscriptionForm.sftp.recursive">目录递归采集</el-checkbox>
                  </el-form-item>
                </template>

                <el-button type="primary" :loading="creatingSubscription" :disabled="!canCreateSubscription" @click="createSubscription">
                  创建订阅
                </el-button>
              </el-form>
            </el-card>
          </section>

          <section class="right-panel">
            <el-card shadow="never" class="panel-card">
              <template #header>
                <div class="card-header">
                  <span>订阅列表</span>
                  <span class="sub-text">{{ subscriptions.length }} 个</span>
                </div>
              </template>

              <div v-if="!selectedDataset" class="empty-state">先在“数据采集”里选中一个数据集，再为它配置订阅。</div>
              <div v-else-if="subscriptions.length === 0" class="empty-state">当前数据集还没有订阅。</div>
              <div v-else class="dataset-list">
                <div v-for="subscription in subscriptions" :key="subscription.id" class="dataset-item">
                  <div class="dataset-item-head">
                    <strong>{{ subscription.name }}</strong>
                    <el-tag size="small" :type="statusTagType(subscription.last_status === 'idle' ? 'pending' : subscription.last_status === 'success' ? 'ready' : subscription.last_status === 'running' ? 'processing' : 'failed')">
                      {{ subscription.last_status }}
                    </el-tag>
                  </div>
                  <div class="dataset-item-meta">
                    <span>类型：{{ subscription.source_kind }}</span>
                    <span>频率：{{ subscription.interval_minutes }} 分钟</span>
                    <span>下次：{{ formatDateTime(subscription.next_run_at) }}</span>
                  </div>
                  <div class="subscription-summary">
                    <div v-if="subscription.source_kind === 'path'">
                      <strong>路径：</strong>{{ subscription.local_paths.join('，') || '-' }}
                    </div>
                    <div v-else>
                      <strong>SFTP：</strong>{{ subscription.source_config?.host || '-' }} / {{ (subscription.source_config?.remote_paths || []).join('，') || '-' }}
                    </div>
                    <div class="sub-text">上次结果：{{ subscription.last_message || '尚未执行' }}</div>
                  </div>
                  <div class="subscription-actions">
                    <el-switch
                      :model-value="subscription.is_enabled"
                      active-text="启用"
                      inactive-text="暂停"
                      @change="(value: string | number | boolean) => toggleSubscription(subscription, Boolean(value))"
                    />
                    <el-button
                      type="primary"
                      plain
                      :loading="runningSubscriptionId === subscription.id"
                      @click="runSubscription(subscription)"
                    >
                      立即执行
                    </el-button>
                    <el-button type="danger" plain @click="removeSubscription(subscription)">删除</el-button>
                  </div>
                </div>
              </div>
            </el-card>
          </section>
        </div>
      </el-tab-pane>

      <el-tab-pane label="数据标注" name="annotation">
        <el-card shadow="never" class="placeholder-card">
          <h3>下一阶段</h3>
          <p>后续会把当前图片/视频标注能力与文档数据集打通，支持分类标注、字段标注和弱监督抽取。</p>
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped lang="scss">
.workbench-page {
  min-height: 100%;
  padding: 24px;
  background: linear-gradient(180deg, #f6f8fb 0%, #eef3f9 100%);
}

.workbench-grid {
  display: grid;
  grid-template-columns: 420px 1fr;
  gap: 20px;
}

.panel-card {
  border-radius: 16px;
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.sub-text {
  font-size: 12px;
  color: #64748b;
}

.dataset-form,
.search-bar,
.inline-input,
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

.inline-input {
  grid-template-columns: 1fr auto;
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.tag-list.compact {
  margin-top: 0;
}

.dataset-list {
  display: grid;
  gap: 10px;
}

.dataset-item {
  text-align: left;
  border: 1px solid #dbe3ef;
  border-radius: 14px;
  padding: 14px;
  background: #fff;
  cursor: pointer;
  transition: 0.2s ease;
}

.dataset-item.active {
  border-color: #409eff;
  box-shadow: 0 10px 24px rgba(64, 158, 255, 0.12);
}

.dataset-item-head,
.dataset-item-meta,
.result-head,
.header-actions,
.stat-grid {
  display: flex;
  gap: 10px;
}

.dataset-item-head,
.result-head {
  align-items: center;
  justify-content: space-between;
}

.dataset-item-meta {
  flex-wrap: wrap;
  margin-top: 8px;
  font-size: 12px;
  color: #64748b;
}

.subscription-summary {
  margin-top: 10px;
  font-size: 13px;
  line-height: 1.6;
  color: #334155;
}

.subscription-actions {
  margin-top: 14px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.dataset-title {
  font-size: 18px;
  font-weight: 600;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}

.stat-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.stat-card span {
  font-size: 12px;
  color: #64748b;
}

.stat-card strong {
  font-size: 20px;
  color: #0f172a;
}

.search-bar {
  grid-template-columns: 1fr 120px auto;
  margin-bottom: 18px;
}

.search-results {
  display: grid;
  gap: 12px;
  margin-bottom: 18px;
}

.processing-panel {
  display: grid;
  gap: 18px;
}

.processing-summary {
  display: grid;
  gap: 16px;
}

.summary-block {
  border: 1px solid #dbe3ef;
  border-radius: 14px;
  padding: 14px;
  background: #fff;
}

.summary-block h4 {
  margin: 0 0 12px;
  font-size: 14px;
  color: #0f172a;
}

.cluster-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
}

.cluster-card {
  border: 1px solid #dbe3ef;
  border-radius: 12px;
  padding: 12px;
  background: #f8fbff;
}

.recommendation-list {
  display: grid;
  gap: 10px;
}

.recommendation-item {
  border-left: 3px solid #409eff;
  padding-left: 12px;
  color: #334155;
  line-height: 1.6;
}

.summary-text-cell {
  line-height: 1.6;
  color: #334155;
  white-space: pre-wrap;
}

.result-card {
  border: 1px solid #dbe3ef;
  border-radius: 14px;
  padding: 14px;
  background: #f8fbff;
}

.result-source {
  font-size: 12px;
  color: #64748b;
  margin: 6px 0 8px;
}

.result-content {
  margin: 0 0 10px;
  line-height: 1.7;
  color: #1f2937;
  white-space: pre-wrap;
}

.resource-table {
  width: 100%;
}

.empty-state {
  padding: 36px 16px;
  text-align: center;
  color: #64748b;
}

.placeholder-card,
.empty-detail {
  min-height: 260px;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
}

@media (max-width: 1200px) {
  .workbench-grid {
    grid-template-columns: 1fr;
  }

  .stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 768px) {
  .workbench-page {
    padding: 16px;
  }

  .two-col,
  .three-col,
  .search-bar,
  .inline-input,
  .stat-grid {
    grid-template-columns: 1fr;
  }
}
</style>
