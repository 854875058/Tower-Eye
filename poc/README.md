# 多模态视联POC

本目录用于演示多模态检索、结构化关联与智能问数的端到端流程。

## 目录结构
- `poc/config/` 配置
- `poc/schema/` 元数据Schema
- `poc/pipeline/` 入库、标注、训练、向量化
- `poc/search/` 向量索引与检索
- `poc/qa/` 智能问数
- `poc/app/` 演示界面
- `poc/docs/` 文档与报告

## 快速开始
1. 准备离线样本
   - 图片：`data/warning_img/`
   - 视频：`data/warning_file/`
   - 结构化数据：`data/structured/alarms.csv` 或 `alarms.json`

2. 入库与校验
   - `python -m poc.pipeline.ingest --config poc/config/poc.yaml`
   - `python -m poc.pipeline.validate --config poc/config/poc.yaml`

3. 自动化标注与审核
   - `python -m poc.pipeline.label_auto --config poc/config/poc.yaml`
   - `python -m poc.pipeline.label_review_io --export`

4. 数据集构建与训练
   - `python -m poc.pipeline.dataset_build --config poc/config/poc.yaml`
   - `python -m poc.pipeline.train_yolov8 --config poc/config/poc.yaml`

5. 向量化与检索
   - `python -m poc.pipeline.embed --config poc/config/poc.yaml`
   - `python -m poc.search.index --config poc/config/poc.yaml`
   - `python -m poc.search.query --text \"夜间烟火\"`

6. 智能问数
   - `python -m poc.qa.answer --question \"近7天烟火告警数量有多少？\" --with-evidence`

7. 演示界面
   - `streamlit run poc/app/app.py`

## 依赖
建议安装：`ultralytics`、`sentence-transformers`、`faiss-cpu`、`pillow`、`opencv-python`、`streamlit`、`numpy`。
