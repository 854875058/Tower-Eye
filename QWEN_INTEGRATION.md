# Qwen3-VL 集成说明

当前仓库中的 Qwen3-VL 集成已经落在 `poc/` 主系统里，不再依赖已移除的 `backend/` 或 `frontend/` 壳层。

## 代码位置

- `poc/search/qwen_embedding.py`
- `poc/search/qwen_reranker.py`
- `poc/search/model_manager.py`
- `poc/infra/ray_actors.py`
- `poc/app/pages/search.py`
- `poc/qa/agent.py`

## 配置项

在 `poc/config/poc.yaml` 中配置：

```yaml
search:
  embedding_model: "qwen"
  qwen_api_url: "http://<host>:8010"
  qwen_timeout: 30
  reranker_enabled: true
  reranker_api_url: "http://<host>:8011"
  reranker_timeout: 60
```

## 工作方式

### Embedding

- 文本检索时，由 `ModelManager` 选择 Qwen3-VL Embedding 客户端
- 图像检索时，上传图片或视频抽帧后生成向量
- 向量最终写入 LanceDB 的 `embeddings` 表

### Reranker

- 检索召回完成后，可选使用 Qwen3-VL Reranker 做二阶段精排
- 精排逻辑主要接在 `poc/search/hybrid_search.py` 和搜索页面流程中

### Agent

- 对视觉描述类问题，Agent 会走向量检索路径
- 对结构化统计或明细问题，Agent 走 DuckDB / NL2SQL 路径
- list 查询完成后，还会做语义增强，补充向量匹配结果

## 运行前检查

- `qwen_api_url` 可访问
- `reranker_api_url` 可访问
- `poc/config/poc.yaml` 已创建
- `python -m poc.pipeline.embed --config poc/config/poc.yaml` 已跑完

## 建议

- 不要把服务地址、密钥或 token 直接写死到代码中
- 统一通过 `poc/config/poc.yaml` 或环境变量注入
- 如果没有 Qwen 服务，可把 `embedding_model` 切回 `clip`
