# 智能数据瞭望系统

基于 FastAPI、SQLAlchemy、SQLite 和原生 HTML/JavaScript 的智能数据与数字员工平台。当前仓库已合流用户侧 A 线和管理侧 B 线，包含账号与人脸登录、数字员工对话、智能问数、数据采集、权限管理、会话审计、工作流、知识库和可视化大屏。

## 环境要求

- Windows 10/11 或兼容的 Python 运行环境
- Python 3.10 及以上
- 人脸识别需要浏览器允许摄像头，并能访问固定版本的 face-api.js CDN
- 真实大模型、图片和视频生成需要在模型管理中配置有效服务地址与 API Key
- 百度新闻、RSS 和自定义网页采集需要部署环境能够访问对应公网源

## 安装与启动

PowerShell：

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

把上面两个命令分别生成的值写入 `.env` 的 `SECRET_KEY` 和 `APP_SECRET_KEY`，同时设置至少 12 位的 `INITIAL_ADMIN_PASSWORD`。然后启动：

```powershell
python -m uvicorn main:app --host 127.0.0.1 --port 8001
```

访问 `http://127.0.0.1:8001/login`。系统没有源码内置的默认密码；首次启动时管理员账号由 `.env` 的 `INITIAL_ADMIN_USERNAME` 和 `INITIAL_ADMIN_PASSWORD` 创建。

生产部署必须保持 `ENABLE_DEMO_SEED=0`，使用不同的随机 `SECRET_KEY` 与 Fernet `APP_SECRET_KEY`，并将 `CORS_ORIGINS` 限制为实际前端域名。工作流代码节点默认关闭，仅在隔离环境评估后才可设置 `WORKFLOW_CODE_EXECUTION_ENABLED=1`。

## 一键演示

脚本使用独立的 `demo_run.db`，随机生成临时管理员密码和两类密钥，不会访问或修改 `data_outlook_v2.db`。它会自动灌入演示数据，验证“登录 → 问数 → 数字员工 → 大屏”链路，然后保持服务运行：

```powershell
.\scripts\demo.ps1
```

终端会显示本次临时账号与密码。按 `Ctrl+C` 停止服务。

回归结束后可清理隔离数据库和测试日志；脚本只处理固定测试文件名，不会删除 `data_outlook_v2.db`：

```powershell
.\scripts\cleanup_test_artifacts.ps1
```

## 测试与安全复扫

```powershell
.\venv\Scripts\python.exe -m pytest -q
.\venv\Scripts\python.exe -m compileall -q .
semgrep scan --config auto --exclude venv --exclude .git .
```

服务启动后可执行全页面浏览器 E2E：

```powershell
.\venv\Scripts\python.exe scripts\browser_e2e.py --base-url http://127.0.0.1:8001 --username <管理员账号> --password <管理员密码>
```

若本机安装了 Trivy，可执行：

```powershell
trivy fs --scanners vuln,secret,misconfig .
```

自动化测试始终使用 `data_outlook_v2.test.db`。浏览器 E2E 或人工联调也应指定独立的 `SQLITE_URL`，不要直接操作开发数据库。

## 核心接口

- 认证：`/api/auth/register`、`/api/auth/login`、`/api/auth/face/register`、`/api/auth/face/login`
- 数字员工：`/api/de/list`、`/api/de/chat`
- 智能问数：`/api/query/nl2sql`
- 数据采集：`/api/dc/sources`、`/api/dc/crawl`、`/api/dc/tasks`
- 权限管理：`/api/permissions/users`、`/api/permissions/functions`、`/api/permissions/bindings`、`/api/permissions/menus`
- 会话管理：`/api/messages/admin/conversations`

## 外部条件说明

仓库内可自动验证接口、权限、数据库、回退逻辑和页面脚本。以下能力需要在目标演示机器上补做人工验收：真实摄像头刷脸、浏览器语音播报、MediaPipe 手势、外部采集源实时可用性，以及配置真实 API Key 后的生文/生图/生视频效果。
