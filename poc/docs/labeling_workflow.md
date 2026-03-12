# 自动化标注与审核流程

## 目标
- 使用 YOLOv8 进行批量自动化标注，降低人工成本
- 保留人工审核入口，完成少量纠错以形成可用训练集

## 自动化标注
1. 准备离线样本目录：
   - `data/warning_img/`：图片
   - `data/warning_file/`：视频（可选）
2. 运行入库后执行自动标注：
   - `python -m poc.pipeline.label_auto --config poc/config/poc.yaml`
3. 输出结果：
   - 标签文件：`data/labels/auto/*.txt`
   - 检测结果入库到 `detections` 表

## 人工审核导出
1. 导出审核任务（JSONL）：
   - `python -m poc.pipeline.label_review_io --export --output data/review/review_tasks.jsonl`
2. 将 JSONL 导入到标注平台（Label Studio/CVAT）或交由人工审核。

## 人工审核回导
1. 将审核后的结果整理为 JSONL，每行包含：
   - `asset_id`
   - `annotations`: `[{label: "xxx", bbox: [x, y, w, h]}]`（bbox 为归一化坐标）
2. 回导：
   - `python -m poc.pipeline.label_review_io --import-file data/review/review_done.jsonl --reviewer alice`
3. 结果写入 `annotations` 表，可用于训练集构建。

## 说明
- 自动化标注依赖 `ultralytics`；视频抽帧依赖 `opencv-python`。
- 需要快速演示时可使用 `--mock` 生成空标签文件。
