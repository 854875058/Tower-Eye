# Tower-Eye 部署指南

本指南只针对当前仍在维护的主系统：`poc/` + NiceGUI。

## 1. 前置要求

- Python 3.10+
- 建议使用独立虚拟环境
- 如果启用 Qwen3-VL / Reranker，需要先准备外部服务地址
- 如果启用 NL2SQL，需要配置 DeepSeek API Key
- 如果启用地图能力，需要配置高德 API Key

## 2. 安装

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 3. 配置

从模板生成正式配置：

```bash
copy poc\config\poc.yaml.example poc\config\poc.yaml
```

重点检查：

- `paths.*`
- `search.embedding_model`
- `search.qwen_api_url`
- `search.reranker_api_url`
- `llm.api_key` 或 `DEEPSEEK_API_KEY`
- `gaode.api_key`
- `ray.enabled`

## 4. 数据准备

默认路径来自 `poc/config/poc.yaml.example`：

- 图片目录：`warning_img`
- 视频目录：`warning_file`
- 结构化数据目录：`poc/data/structured`

先完成入库与向量化：

```bash
python -m poc.pipeline.ingest --config poc/config/poc.yaml
python -m poc.pipeline.embed --config poc/config/poc.yaml
```

可选：

```bash
python -m poc.pipeline.vl_analyze --config poc/config/poc.yaml
python -m poc.pipeline.label_auto --config poc/config/poc.yaml
```

## 5. 启动方式

### 推荐方式

```bash
python bin/manage.py start
```

常用运维命令：

```bash
python bin/manage.py status
python bin/manage.py check
python bin/manage.py restart
python bin/manage.py stop
```

### 直接启动

```bash
python -m poc.app.app_ui
```

默认端口：

```text
http://localhost:8080
```

## 6. 日志与状态

`bin/manage.py` 默认会在仓库根目录使用：

- `logs/app.log`
- `logs/app.pid`
- `logs/traces.db`
- `logs/metrics.db`

排查时优先看：

```bash
python bin/manage.py status
python bin/manage.py check
```

## 7. 反向代理

如果需要对外暴露，可以把 Nginx 代理到 `127.0.0.1:8080`。

示例：

```nginx
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }
}
```

## 8. systemd 示例

```ini
[Unit]
Description=Tower-Eye NiceGUI App
After=network.target

[Service]
Type=simple
WorkingDirectory=/path/to/Tower-Eye
ExecStart=/path/to/python bin/manage.py start
ExecStop=/path/to/python bin/manage.py stop
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

如果你使用 `systemd`，也可以直接把 `ExecStart` 改为：

```text
/path/to/python -m poc.app.app_ui
```

## 9. 已移除内容

以下旧方案已不再适用：

- `backend/` FastAPI 辅助壳
- `frontend/` React 演示壳
- 依赖它们的旧部署说明

当前仓库只部署 `poc/` 主系统。
