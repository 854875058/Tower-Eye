# Qwen3-VL 接入方案

## 1. 技术选型

### Qwen3-VL-Embedding
- **模型**: Qwen/Qwen2-VL-7B-Instruct 或 Qwen/Qwen2-VL-2B-Instruct
- **用途**: 生成图像和文本的向量表示
- **优势**:
  - 更强的中文理解能力
  - 更好的细粒度特征提取
  - 支持高分辨率图像

### Qwen3-VL-Reranker
- **用途**: 对初步检索结果进行重排序
- **优势**: 提高检索准确率

## 2. 架构设计

```
查询流程：
1. 用户输入文本/图像
2. Qwen3-VL-Embedding 生成查询向量
3. LanceDB 向量检索（召回 top-100）
4. 应用空间+时序过滤
5. Qwen3-VL-Reranker 重排序（精排 top-20）
6. 返回最终结果
```

## 3. 实施步骤

### 步骤1：安装依赖
```bash
pip install transformers>=4.37.0
pip install torch torchvision
pip install qwen-vl-utils
```

### 步骤2：下载模型
```bash
# 使用 HuggingFace 镜像
export HF_ENDPOINT=https://hf-mirror.com

# 下载 Qwen2-VL-2B（较小，适合测试）
huggingface-cli download Qwen/Qwen2-VL-2B-Instruct --local-dir models/Qwen2-VL-2B-Instruct
```

### 步骤3：创建 Embedding 服务
创建 `poc/search/qwen_embedding.py`

### 步骤4：创建 Reranker 服务
创建 `poc/search/qwen_reranker.py`

### 步骤5：修改检索流程
更新 `backend/main.py` 的检索接口

## 4. 性能对比

| 模型 | 向量维度 | 速度 | 准确率 | 显存占用 |
|------|---------|------|--------|---------|
| CLIP-ViT-L-14 | 768 | 快 | 中 | ~2GB |
| Qwen2-VL-2B | 1536 | 中 | 高 | ~8GB |
| Qwen2-VL-7B | 3584 | 慢 | 很高 | ~16GB |

## 5. 兼容性方案

支持两种模式：
- **CLIP 模式**（默认）：快速、轻量
- **Qwen3-VL 模式**：高精度、重量级

通过配置文件切换：
```yaml
search:
  embedding_model: "qwen"  # 或 "clip"
  reranker_enabled: true
```

## 6. 预期效果

- ✅ 中文查询准确率提升 20-30%
- ✅ 细粒度特征识别能力增强
- ✅ 支持更复杂的场景理解
- ⚠️ 检索速度降低 2-3 倍
- ⚠️ 显存需求增加 4-8 倍
