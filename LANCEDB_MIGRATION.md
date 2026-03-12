# LanceDB 迁移指南

## ✅ 自动 Git 提交已启用

本项目已配置自动 Git 提交功能，每次代码修改后会自动提交到 Git。

---

## 📋 改造内容

已将向量存储从 **FAISS + NumPy + SQLite** 迁移到 **LanceDB**，实现向量和元数据一体化存储。

### 主要变更

1. **配置文件** (`poc/config/poc.yaml`)
   - 移除: `embeddings_dir`, `index_dir`
   - 新增: `lancedb_dir: "data/lancedb"`

2. **向量生成** (`poc/pipeline/embed.py`)
   - 直接将向量和元数据写入 LanceDB
   - 自动创建向量索引（cosine 相似度）
   - 不再需要单独的 NumPy 文件

3. **检索查询** (`poc/search/query.py`)
   - 使用 LanceDB 的向量搜索 API
   - 支持混合查询（向量 + 属性过滤）
   - 简化了代码逻辑

4. **Web 界面** (`poc/app/app_v2.py`)
   - 更新为使用 LanceDB
   - 移除 FAISS 相关代码

5. **脚本更新** (`重新入库.sh`)
   - 移除索引构建步骤（不再需要）
   - 简化为 3 步：清理 → 导入 → 生成向量

6. **删除文件**
   - `poc/search/index.py` - 不再需要单独建索引

## 🚀 安装依赖

在 multimodal 环境中安装 LanceDB：

```bash
conda activate multimodal
pip install lancedb
```

## 📦 使用方法

### 1. 重新生成数据

```bash
# 在服务器上运行
bash 重新入库.sh
```

这会：
- 清理旧的 FAISS 索引和 NumPy 文件
- 重新导入结构化数据
- 生成向量并写入 LanceDB（包含元数据）

### 2. 启动服务

```bash
bash restart_poc.sh
```

## ✨ LanceDB 优势

### 相比 FAISS 方案的改进：

| 特性 | FAISS 方案 | LanceDB 方案 |
|------|-----------|-------------|
| 存储方式 | 向量和元数据分离 | 一体化存储 |
| 更新方式 | 需要重建整个索引 | 支持增量更新 |
| 查询方式 | 两步查询（向量→元数据） | 一步完成 |
| 过滤功能 | 后置过滤（低效） | 内置混合查询 |
| 代码复杂度 | 高（3个存储系统） | 低（1个系统） |
| 性能 | 好 | 更好（零拷贝） |

### 具体改进：

1. **简化架构**
   ```
   旧: CSV → SQLite → embed.py → NumPy → index.py → FAISS → query.py
   新: CSV → SQLite → embed.py → LanceDB → query.py
   ```

2. **支持增量更新**
   - 添加新图片不需要重建整个索引
   - 可以直接 append 到 LanceDB

3. **更高效的过滤**
   - 向量搜索和属性过滤在数据库层面完成
   - 减少数据传输和内存占用

4. **更好的可维护性**
   - 不需要维护 `index_meta.json`
   - 不需要同步多个存储系统

## 🔧 技术细节

### LanceDB 表结构

```python
{
    "asset_id": str,           # 资产ID
    "file_path": str,          # 文件路径
    "file_name": str,          # 文件名
    "captured_at": str,        # 拍摄时间
    "lat": float,              # 纬度
    "lon": float,              # 经度
    "event_type": str,         # 事件类型
    "alarm_time": str,         # 告警时间
    "alarm_level": str,        # 告警级别
    "model_name": str,         # 模型名称
    "vector": List[float],     # 向量（768维）
}
```

### 向量索引配置

```python
table.create_index(
    metric="cosine",        # 余弦相似度
    num_partitions=256,     # 分区数
    num_sub_vectors=96      # 子向量数
)
```

### 混合查询示例

```python
# 向量搜索 + 属性过滤
query = table.search(query_vec) \
    .where("event_type = '火灾' AND lat >= 30.0 AND lat <= 40.0") \
    .limit(10)
```

## 📝 注意事项

1. **首次运行需要重新生成数据**
   - 旧的 FAISS 索引不兼容
   - 运行 `bash 重新入库.sh` 即可

2. **LanceDB 数据目录**
   - 位置: `data/lancedb/`
   - 包含表数据和索引文件
   - 可以直接备份整个目录

3. **性能优化**
   - 向量索引已自动创建
   - 适合 10万+ 级别的数据量
   - 如果数据量更大，可以调整 `num_partitions`

## 🐛 故障排查

### 问题1: ModuleNotFoundError: No module named 'lancedb'

```bash
conda activate multimodal
pip install lancedb
```

### 问题2: 表不存在

```bash
# 重新生成数据
bash 重新入库.sh
```

### 问题3: 维度不匹配

确保配置文件中的模型名称正确：
```yaml
search:
  clip_model: "clip-ViT-L-14"  # 768维
```

## 📚 参考资料

- [LanceDB 官方文档](https://lancedb.github.io/lancedb/)
- [LanceDB Python API](https://lancedb.github.io/lancedb/python/)
- [Apache Arrow](https://arrow.apache.org/)
