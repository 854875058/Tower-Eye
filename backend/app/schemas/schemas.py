"""
Pydantic schemas - API 请求/响应模型
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Workspace ──────────────────────────────────────────────────────────────

class WorkspaceBase(BaseModel):
    name: str
    description: Optional[str] = None


class WorkspaceCreate(WorkspaceBase):
    pass


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class WorkspaceResponse(WorkspaceBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


# ── User ───────────────────────────────────────────────────────────────────

class UserBase(BaseModel):
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None


class UserCreate(UserBase):
    password: str


class UserResponse(UserBase):
    id: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class UserLogin(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ── DataSource ────────────────────────────────────────────────────────────

class DataSourceBase(BaseModel):
    name: str
    type: str  # mysql, postgresql, sqlserver, csv
    host: Optional[str] = None
    port: Optional[int] = None
    database: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None  # 写入时使用，读取时不返回
    connection_string: Optional[str] = None
    workspace_id: int


class DataSourceCreate(DataSourceBase):
    pass


class DataSourceUpdate(BaseModel):
    name: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    database: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    connection_string: Optional[str] = None
    is_active: Optional[bool] = None


class DataSourceResponse(BaseModel):
    id: int
    workspace_id: int
    name: str
    type: str
    host: Optional[str]
    port: Optional[int]
    database: Optional[str]
    username: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DataSourceTestRequest(BaseModel):
    type: str
    host: Optional[str] = None
    port: Optional[int] = None
    database: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    connection_string: Optional[str] = None


class DataSourceTestResponse(BaseModel):
    success: bool
    message: str
    table_count: Optional[int] = None


# ── CSV File ───────────────────────────────────────────────────────────────

class CSVFileResponse(BaseModel):
    id: int
    data_source_id: int
    filename: str
    file_size: Optional[int]
    row_count: Optional[int]
    column_count: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True


# ── Schema / Column ───────────────────────────────────────────────────────

class SchemaColumnResponse(BaseModel):
    table_name: str
    column_name: str
    column_type: Optional[str] = None
    description: Optional[str] = None
    is_primary_key: bool = False
    is_foreign_key: bool = False
    is_nullable: bool = True
    sample_values: Optional[List[Any]] = None
    row_count_estimate: Optional[int] = None

    class Config:
        from_attributes = True


class SchemaRefreshResponse(BaseModel):
    success: bool
    table_count: int
    column_count: int
    message: str


# ── Dataset ───────────────────────────────────────────────────────────────

class MetricDefinition(BaseModel):
    """指标定义"""
    name: str
    expression: str  # SQL 表达式
    description: Optional[str] = None
    aggregation_type: str = "sum"  # sum, avg, count, max, min


class DimensionDefinition(BaseModel):
    """维度定义"""
    name: str
    column: str  # 对应列名
    description: Optional[str] = None


class AliasMapping(BaseModel):
    """别名映射"""
    alias: str
    column: str
    description: Optional[str] = None


class DatasetBase(BaseModel):
    name: str
    description: Optional[str] = None


class DatasetCreate(DatasetBase):
    workspace_id: Optional[int] = None
    data_source_ids: Optional[List[int]] = None
    data_source_id: Optional[int] = None  # 兼容旧版
    file_paths: Optional[List[str]] = None
    metrics: Optional[List[MetricDefinition]] = None
    dimensions: Optional[List[DimensionDefinition]] = None
    aliases: Optional[List[AliasMapping]] = None
    business_rules: Optional[str] = None
    status: Optional[str] = 'draft'


class TowerCleanedDatasetImportRequest(BaseModel):
    workspace_id: int
    data_source_name: Optional[str] = "铁塔告警清洗数据源"
    dataset_name: Optional[str] = "铁塔告警清洗数据集"
    description: Optional[str] = "基于铁塔清洗后的 metadata.db events 表自动接入，供当前系统查询页和智能问答直接使用。"


class DatasetUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    data_source_ids: Optional[List[int]] = None
    data_source_id: Optional[int] = None  # 兼容旧版
    metrics: Optional[List[MetricDefinition]] = None
    dimensions: Optional[List[DimensionDefinition]] = None
    aliases: Optional[List[AliasMapping]] = None
    business_rules: Optional[str] = None
    status: Optional[str] = None


class DatasetResponse(DatasetBase):
    id: int
    workspace_id: int
    data_source_id: Optional[int] = None
    data_source_ids: Optional[List[int]] = None
    status: str
    processing_status: str = "ready"
    progress: Optional[float] = None
    error_message: Optional[str] = None
    media_count: int = 0
    processed_count: int = 0
    failed_count: int = 0
    last_processed_at: Optional[datetime] = None
    metrics: Optional[List[dict]] = None
    dimensions: Optional[List[dict]] = None
    aliases: Optional[List[dict]] = None
    business_rules: Optional[str] = None
    version: int
    created_at: datetime

    class Config:
        from_attributes = True


# ── Annotation ───────────────────────────────────────────────────────────

class WorkbenchSftpConfig(BaseModel):
    host: str
    port: int = 22
    username: str
    password: str
    remote_paths: List[str] = Field(default_factory=list)
    recursive: bool = True


class WorkbenchDatasetCreate(BaseModel):
    workspace_id: int
    name: str
    description: Optional[str] = None
    file_paths: List[str] = Field(default_factory=list)
    sftp_config: Optional[WorkbenchSftpConfig] = None


class WorkbenchSampleImportRequest(BaseModel):
    workspace_id: int
    name: str = "铁塔视联告警样本"
    description: Optional[str] = "基于甲方提供的视联告警样本构建的多模态演示数据集"
    max_records: int = 200


class WorkbenchDatasetResponse(BaseModel):
    id: int
    workspace_id: int
    name: str
    description: Optional[str] = None
    processing_status: str
    resource_count: int = 0
    processed_count: int = 0
    failed_count: int = 0
    chunk_count: int = 0
    vector_count: int = 0
    total_text_length: int = 0
    source_summary: Optional[dict] = None
    processing_summary: Optional[dict] = None
    error_message: Optional[str] = None
    last_ingested_at: Optional[datetime] = None
    processing_updated_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class WorkbenchResourceResponse(BaseModel):
    id: int
    dataset_id: int
    source_kind: str
    source_uri: str
    stored_path: str
    file_name: str
    file_extension: Optional[str] = None
    file_category: Optional[str] = None
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    checksum: Optional[str] = None
    parser_name: Optional[str] = None
    status: str
    chunk_count: int = 0
    text_length: int = 0
    extraction_metadata: Optional[dict] = None
    labels: List[str] = Field(default_factory=list)
    category_label: Optional[str] = None
    cluster_id: Optional[int] = None
    cluster_label: Optional[str] = None
    summary_text: Optional[str] = None
    quality_score: Optional[float] = None
    processing_metadata: Optional[dict] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    last_processed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class WorkbenchDatasetDetailResponse(WorkbenchDatasetResponse):
    resources: List[WorkbenchResourceResponse] = Field(default_factory=list)


class WorkbenchSearchRequest(BaseModel):
    query: str
    top_k: int = 8


class WorkbenchSearchResult(BaseModel):
    dataset_id: int
    resource_id: int
    chunk_id: int
    chunk_index: int
    file_name: str
    source_uri: str
    score: float
    content: str
    keywords: List[str] = Field(default_factory=list)
    chunk_metadata: Optional[dict] = None
    parser_name: Optional[str] = None


class WorkbenchProcessingRequest(BaseModel):
    extract_labels: bool = True
    cluster_count: int = 4
    refresh_summary: bool = True


class WorkbenchSubscriptionBase(BaseModel):
    dataset_id: int
    name: str
    source_kind: str
    interval_minutes: int = 60
    is_enabled: bool = True
    local_paths: List[str] = Field(default_factory=list)
    sftp_config: Optional[WorkbenchSftpConfig] = None


class WorkbenchSubscriptionCreate(WorkbenchSubscriptionBase):
    workspace_id: int


class WorkbenchSubscriptionUpdate(BaseModel):
    name: Optional[str] = None
    interval_minutes: Optional[int] = None
    is_enabled: Optional[bool] = None
    local_paths: Optional[List[str]] = None
    sftp_config: Optional[WorkbenchSftpConfig] = None


class WorkbenchSubscriptionResponse(BaseModel):
    id: int
    workspace_id: int
    dataset_id: int
    name: str
    source_kind: str
    is_enabled: bool
    interval_minutes: int
    local_paths: List[str] = Field(default_factory=list)
    source_config: Optional[dict] = None
    last_status: str
    last_message: Optional[str] = None
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    last_new_resources: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TowerOntologyEntityConfig(BaseModel):
    type: str
    label: str
    description: str
    key_fields: List[str] = Field(default_factory=list)
    source_fields: List[str] = Field(default_factory=list)
    enabled: bool = True


class TowerOntologyRelationConfig(BaseModel):
    type: str
    label: str
    source_type: str
    target_type: str
    description: str
    source_field: Optional[str] = None
    enabled: bool = True


class TowerOntologyConfigPayload(BaseModel):
    entities: List[TowerOntologyEntityConfig] = Field(default_factory=list)
    relations: List[TowerOntologyRelationConfig] = Field(default_factory=list)


class TowerOntologyConfigResponse(TowerOntologyConfigPayload):
    updated_at: Optional[str] = None


class AnnotationSessionRequest(BaseModel):
    workspace_id: int
    media_type: str
    source_dir: str
    output_dir: Optional[str] = None
    use_tracking: bool = True
    frame_interval: int = 1
    detect_size: int = 640
    force_reprocess: bool = False


class AnnotationCursorUpdateRequest(BaseModel):
    current_index: int


class AnnotationAnnotationsUpdateRequest(BaseModel):
    annotations: List[dict]


class AnnotationFileResponse(BaseModel):
    key: str
    class_name: str
    label: str
    class_id: int


class AnnotationOperationResponse(BaseModel):
    message: str
    saved_paths: Optional[List[str]] = None


# ── Query / NL2SQL ──────────────────────────────────────────────────────

class QueryContextTurn(BaseModel):
    """短会话中的单轮查询摘要"""
    question: str
    intent: Optional[str] = None
    answer: Optional[str] = None
    sql: Optional[str] = None
    row_count: Optional[int] = None
    result_schema: Optional[List[dict]] = None
    table_names: Optional[List[str]] = None
    dataset_id: Optional[int] = None
    status: Optional[str] = None
    plan_source: Optional[str] = None


class QuerySessionContext(BaseModel):
    """当前页面内最近几轮会话上下文"""
    recent_turns: Optional[List[QueryContextTurn]] = None
    current_dataset_id: Optional[int] = None
    current_table_names: Optional[List[str]] = None


class QueryRequest(BaseModel):
    """NL2SQL 查询请求"""
    question: str
    workspace_id: int
    dataset_id: Optional[int] = None
    table_names: Optional[List[str]] = None  # 用户选择的表名列表
    context: Optional[QuerySessionContext] = None  # 短会话上下文
    query_image_path: Optional[str] = None
    query_video_path: Optional[str] = None


class MultimodalSearchExtra(BaseModel):
    caption_text: Optional[str] = None
    asr_text: Optional[str] = None
    ocr_text: Optional[str] = None
    tags: Optional[List[str]] = None


class MultimodalSearchResult(BaseModel):
    type: str
    image_id: Optional[int] = None
    video_id: Optional[int] = None
    start_sec: Optional[float] = None
    end_sec: Optional[float] = None
    score: float
    preview_url: Optional[str] = None
    preview_frame: Optional[str] = None
    dataset_id: int
    resource_id: int
    extra: Optional[MultimodalSearchExtra] = None


class ExecuteSqlRequest(BaseModel):
    """执行 SQL 请求"""
    sql: str
    workspace_id: int
    dataset_id: Optional[int] = None
    table_names: Optional[List[str]] = None  # 用户选择的表名列表
    sql_params: Optional[List[Any]] = None


class QueryResponse(BaseModel):
    """NL2SQL 查询响应"""
    question: str
    normalized_question: Optional[str] = None
    intent: Optional[str] = None
    matched_dataset: Optional[dict] = None
    sql: Optional[str] = None  # 生成的 SQL
    semantic_sql: Optional[str] = None  # 业务逻辑SQL
    executable_sql: Optional[str] = None  # 可执行SQL
    sql_params: Optional[List[Any]] = None
    reasoning_summary: Optional[str] = None
    result_schema: Optional[List[dict]] = None
    result_rows: Optional[List[dict]] = None
    row_count: int = 0
    chart_suggestion: Optional[str] = None
    cost_time_ms: Optional[float] = None
    cost_rows: Optional[int] = None
    warnings: Optional[List[str]] = None
    status: str
    error: Optional[str] = None
    trace_id: str
    audit_id: str
    agent_steps: Optional[List[dict]] = None  # Agent 思考步骤
    execution_history: Optional[List[dict]] = None  # 完整节点执行历史
    evidence: Optional[dict] = None  # 结构化证据
    semantic_scores: Optional[Dict[str, float]] = None  # 语义增强匹配分数
    vector_only_results: Optional[List[dict]] = None  # 语义增强补充推荐结果
    answer: Optional[str] = None  # 自然语言答案
    plan_source: Optional[str] = None  # 规划来源：rule/llm/verified_query/sql_cache/manual_sql/reject
    confidence: Optional[float] = None  # 规划置信度（0~1）
    clarification_needed: Optional[bool] = None  # 是否需要用户澄清
    clarification_options: Optional[List[str]] = None  # 澄清建议候选


class QueryHistoryResponse(BaseModel):
    """查询历史响应"""
    id: int
    question: str
    normalized_question: Optional[str]
    intent: Optional[str]
    semantic_sql: Optional[str]
    executable_sql: Optional[str]
    row_count: int
    execution_time_ms: Optional[float]
    status: str
    trace_id: str
    created_at: datetime

    class Config:
        from_attributes = True


class QueryHistoryCreate(BaseModel):
    """创建查询历史请求"""
    workspace_id: int
    dataset_id: Optional[int] = None
    question: str
    normalized_question: Optional[str] = None
    intent: Optional[str] = None
    semantic_sql: Optional[str] = None
    executable_sql: Optional[str] = None
    sql_params: Optional[List[Any]] = None
    result_schema: Optional[list] = None
    result_rows: Optional[list] = None
    row_count: int = 0
    execution_time_ms: Optional[float] = None
    status: str = "success"
    error_message: Optional[str] = None
    warnings: Optional[list] = None
    trace_id: str
    audit_id: Optional[str] = None
