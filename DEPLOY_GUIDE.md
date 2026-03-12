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

- 图片目录：`data/warning_img`
- 视频目录：`data/warning_file`
- 结构化数据目录：`data/structured`

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

该命令会先 bootstrap 本地 `Ray`，再启动 NiceGUI；Web 进程本身只 connect，不再自行拉起第二套 Ray。

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

直接启动仅适用于以下场景：

- `ray.address` 已配置为一个明确可连接的集群地址
- 或你明确把 `ray.address` 设为 `local`，允许当前进程自行 bootstrap 本地 Ray（更适合脚本调试，不推荐用于长期运行的 Web 进程）

默认端口：

```text
http://localhost:8080
```

### 5.1 切换端口

如果不想占用 `8080`，可以在启动前设置 `APP_PORT`：

```powershell
$env:APP_PORT='8097'
python bin/manage.py start
```

```bash
APP_PORT=8097 python bin/manage.py start
```

### 5.2 Ray 启动异常排障

已知现象：

- `python bin/manage.py start` 或 `restart` 卡在启动阶段
- 日志持续出现 `global_state_accessor.cc:505`
- 日志出现 `Failed to connect to the default Ray cluster address at 127.0.0.1:6379`
- 换到 `8097` 等其他端口后仍然起不来

这类问题通常不是端口本身冲突，而是本地 `Ray` 集群处于“半残留 / 脏状态”，或 Web 进程拿到了过期的 bootstrap 地址。

推荐处理顺序：

```bash
ray stop
python bin/manage.py stop
python bin/manage.py start
```

如果只是想临时换端口，先清理 `Ray`，再带 `APP_PORT` 启动；不要在 `Ray` 状态异常时直接反复切端口。

另外，`python bin/manage.py start` 成功后会写入 `logs/ray_bootstrap.json`，记录本次本地 Ray 的 connect 地址。应用只会连接这个地址，而不会在 Web 进程内再次自启 Ray。

### 5.3 SQL 缓存与 Trace 说明

`sql_cache` 和 `trace` 依赖 `TraceManager` 初始化。

对于命令行查询，默认不会自动启用 trace / cache；需要显式加参数：

```bash
python -m poc.qa.agent_query --enable-trace --question "统计各设备触发告警次数最多的TOP10"
```

如果不加 `--enable-trace`：

- 命令行链路不会写入 `data/traces.db`
- `sql_cache` 不会自动积累
- 你会误以为“缓存没生效”

另外，历史缓存里如果存在旧模板，例如 SQL 写成 `LIMIT 10` 常量而不是参数化模板，命中时会出现：

```text
[sql_cache] SKIP - placeholder count (0) != param count (1)
```

这表示“缓存命中了坏模板”，不是“完全没有缓存”。

## 6. 日志与状态

`bin/manage.py` 默认会在仓库根目录使用：

- `logs/app.log`
- `logs/app.pid`
- `logs/ray_bootstrap.json`
- `data/traces.db`
- `data/metrics.db`

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
