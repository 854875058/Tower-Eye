# Legacy Web Shell Removed

仓库中原有的 React + FastAPI 演示壳已经移除，不再作为项目的运行入口或部署目标。

当前有效的 Web 入口只有：

```bash
python -m poc.app.app_ui
```

或：

```bash
python bin/manage.py start
```

主系统说明请看：

- `README.md`
- `DEPLOY_GUIDE.md`
- `ARCHITECTURE.md`

如果你需要查看旧壳层实现，请从 Git 历史中检索 `backend/` 和 `frontend/` 目录。
