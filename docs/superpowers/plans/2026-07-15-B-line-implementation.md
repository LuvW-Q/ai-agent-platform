# B 线 — 管理后台 + 瞭望数据 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成智能数据瞭望系统 B 线全部 12 个子任务（#12-#23），实现管理后台多模块 CRUD、数据采集链路、多模态模型管理、数字员工管理、大屏可视化、系统设置等。

**Architecture:** 后端 FastAPI + SQLAlchemy + SQLite，前端 Tailwind 单 HTML 多页（无前端工程化），遵循现有模式：controller 层提供 REST API，HTML 内联 `<script>` 通过 `apiGet/apiPost` 调用后端，`app.js` 提供统一侧边栏和工具函数。

**Tech Stack:** Python 3.9+, FastAPI 0.115, SQLAlchemy 2.0, SQLite, Tailwind CSS (CDN), ECharts 5, Material Symbols

**分支:** `feat/B`（基于 `main`，底座已合并）

## 全局约束

- 禁止改动 A 线对话流页面（`de-chat.html`、`smart-query.html`、`login.html`），除非在计划中明确列出
- `agents` / `skills` / `ai_models` / `collected_data` 表 schema 改动由 B 独占，A 线只读
- 所有新建模型必须在 `seed.py` 的 `_seed_menus()` 中注册对应菜单
- 所有新建模型文件必须在 `main.py` 顶部 import 确保建表
- 每步后需启动服务验收（`python main.py`）

---

## 任务分解

### Task 1: 系统设置引擎 (#23) — settings 表 + 后端 API

**前提：** 当前 `settings.html` 页面有前端 UI 但数据是硬编码的，没有对应的 settings 表和后端 API。

**Files:**
- Create: `models/setting.py`
- Create: `controller/setting_controller.py`
- Modify: `main.py`（注册 setting_router、import Setting）
- Modify: `static/settings.html`（对接真实 API）

**Interfaces:**
- Consumes: `get_current_user` (core.security)
- Produces: `Setting` model (id, key, value, description, updated_at)；`GET /api/settings`、`PUT /api/settings/{key}`
- Produces: `POST /api/settings/system-name` 修改系统名称（侧边栏标题联动）

- [ ] **Step 1: 创建 Setting 模型**

```python
# models/setting.py
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime
from database.session import Base

class Setting(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(String(500), default="")
    description = Column(String(200), default="")
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
```

- [ ] **Step 2: 创建 Setting Controller**

```python
# controller/setting_controller.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from database.session import SessionLocal, get_db
from core.security import get_current_user
from models.user import User
from models.setting import Setting

setting_router = APIRouter(prefix="/api/settings", tags=["系统设置"])

class SettingUpdateIn(BaseModel):
    value: str

class SettingOut(BaseModel):
    key: str
    value: str
    description: str

@setting_router.get("", response_model=list[SettingOut])
def list_settings(db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(Setting).order_by(Setting.id).all()

@setting_router.put("/{key}", response_model=SettingOut)
def update_setting(key: str, body: SettingUpdateIn, db: SessionLocal = Depends(get_db),
                    user: User = Depends(get_current_user)):
    s = db.query(Setting).filter(Setting.key == key).first()
    if not s:
        s = Setting(key=key, value=body.value)
        db.add(s)
    else:
        s.value = body.value
    db.commit()
    db.refresh(s)
    return SettingOut(key=s.key, value=s.value, description=s.description)

@setting_router.post("/system-name")
def set_system_name(body: SettingUpdateIn, db: SessionLocal = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """修改系统名称，更新 settings 表"""
    s = db.query(Setting).filter(Setting.key == "system_name").first()
    if not s:
        s = Setting(key="system_name", value=body.value, description="系统名称")
        db.add(s)
    else:
        s.value = body.value
    db.commit()
    db.refresh(s)
    return {"key": "system_name", "value": s.value}
```

- [ ] **Step 3: 注册到 main.py**

在 `main.py` 的 import 区域添加：
```python
from models.setting import Setting
from controller.setting_controller import setting_router
```
在建表 `create_all` 后（但 setting 表已含在 base 中），在 `app.include_router` 区域添加：
```python
app.include_router(setting_router)
```

- [ ] **Step 4: 更新 seed.py 添加系统设置默认值**

在 `_seed_` 系列函数中添加新函数 `_seed_settings(db)`：
```python
def _seed_settings(db: SessionLocal):
    if db.query(Setting).first():
        return
    defaults = [
        Setting(key="system_name", value="智能数据瞭望系统", description="系统名称"),
        Setting(key="log_retention_days", value="30", description="日志保留天数"),
        Setting(key="default_model_id", value="1", description="默认模型ID"),
        Setting(key="sensitive_threshold", value="0.6", description="敏感词匹配阈值"),
        Setting(key="voice_enabled", value="true", description="语音播报开关"),
        Setting(key="face_recognition_enabled", value="false", description="人脸识别开关"),
        Setting(key="collection_rate_limit", value="10", description="采集频率限制(次/分钟)"),
    ]
    for s in defaults:
        db.add(s)
    print("[seed] 系统设置写入完成")
```
并在 `run_seed()` 中调用 `_seed_settings(db)`。

- [ ] **Step 5: 更新 settings.html 前端对接 API**

在 `static/settings.html` 的 `<script>` 块中：
- `loadProfile()` 之后添加 `loadSettings()` 读取 `/api/settings` 并回填所有控件
- 系统名称输入框保存时调 `POST /api/settings/system-name`
- 各开关（语音播报、通知开关等）绑定对应 setting key 的 PUT 操作
- 修改"数据瞭望系统"静态文本为根据 setting 动态渲染（通过侧边栏联动，靠 `app.js` 的系统名称 GET）

- [ ] **Step 6: 更新 app.js 加载系统名称**

在 `app.js` 的 `loadSidebarUser()` 中或单独 `loadSystemName()` 中：
```javascript
async function loadSystemName() {
  try {
    const settings = await apiGet('/api/settings');
    const sysName = settings.find(s => s.key === 'system_name');
    if (sysName) {
      document.querySelectorAll('.app-top-nav h1, .app-utility-rail h1').forEach(el => {
        el.textContent = sysName.value;
      });
    }
  } catch(e) { /* silent */ }
}
```
调用时机：在 `replaceSidebar()` 成功后调用 `loadSystemName()`。

- [ ] **Step 7: 启动服务验收**

```bash
rm -f data_outlook_v2.db
python main.py &
# 验证
curl -s http://127.0.0.1:8001/api/settings -H "Authorization: Bearer $(curl -s -X POST http://127.0.0.1:8001/api/auth/login -H 'Content-Type: application/json' -d '{"username":"admin","password":"admin123"}' | python3 -c 'import json,sys;print(json.load(sys.stdin)[\"access_token\"])')" | python3 -m json.tool
```
Expected: 7 个系统设置返回，包括 system_name = "智能数据瞭望系统"。

- [ ] **Step 8: Commit**

```bash
git add models/setting.py controller/setting_controller.py main.py seed.py static/settings.html static/js/app.js
git commit -m "feat(B): 系统设置引擎 - Setting模型+API+前端对接 (#23)"
```

---

### Task 2: 控制台首页仪表盘 (#12) — 完善 Dashboard 指标

**前提:** `im-console.html` 已有 63k 雏形，`dashboard_controller.py` 已返回 `DashboardMetrics`，但需要：
1. 套用统一侧边栏（底座已完成，只需确认 `im-console.html` 的 `<aside>` 为空即可）
2. 前端展示 6+ 图形化卡片
3. 增加采集成功率、活跃数字员工等指标

**Files:**
- Modify: `controller/dashboard_controller.py`（补充活跃数字员工计数、情感倾向分布等指标）
- Modify: `static/im-console.html`（替换硬编码内容为 API 驱动的仪表盘卡片）
- Modify: `seed.py`（补充用户/会话/采集数据让仪表盘有数据可展示）

**Interfaces:**
- Consumes: `DashboardMetrics` (schema/api.py), `GET /api/dashboard/metrics`
- Produces: 扩展的 `DashboardMetrics`（新增 `active_agents`, `total_collected`）

- [ ] **Step 1: 扩展 DashboardMetrics**

在 `schema/api.py` 中添加新字段：
```python
class DashboardMetrics(BaseModel):
    active_pipelines: int
    crawl_success_rate: float
    data_ingress_24h: str
    active_threats: int
    today_messages: int
    active_users: int
    audit_high: int
    audit_medium: int
    audit_low: int
    sentiment_positive: int
    trust_score: float
    # 新字段
    active_agents: int = 0       # 已发布的数字员工数
    total_collected: int = 0     # 采集数据总量
    online_users: int = 0        # 在线用户数（简化：7天内活跃即可）
    risk_distribution: str = ""  # JSON: {"high":x, "medium":y, "low":z}
```

- [ ] **Step 2: 扩展 dashboard_controller 指标计算**

在 `get_metrics()` 函数的 SQL 查询后补充：
```python
# 活跃数字员工（status=published）
active_agents = db.query(func.count(Agent.id)).filter(Agent.status == "published").scalar() or 0

# 采集数据总量
total_collected = db.query(func.count(CollectedData.id)).filter(CollectedData.saved == True).scalar() or 0

# 风险分布 JSON
risk_distribution = json.dumps({
    "high": audit_high, "medium": audit_medium, "low": audit_low
}, ensure_ascii=False)

# 加入 DashboardMetrics 返回
```

需要 import：`from models.agent import Agent`、`from models.data_collection import CollectedData`、`import json`。

- [ ] **Step 3: 重写 im-console.html 为图标驱动的控制台**

将 `static/im-console.html` 从当前雏形（可能包含硬编码 IM 界面）重写为管理控制台首页风格：
- 统一侧边栏（`<aside></aside>` 已存在）
- 顶部 6 卡片行：在线用户、今日消息、采集成功率、活跃员工、风险事件、信任分
- 中间部分：情感倾向饼图 + 审计风险柱状图（用 ECharts CDN）
- 底部：最近审计日志列表
- 所有数据通过 `apiGet('/api/dashboard/metrics')` 和 `apiGet('/api/audit/logs?limit=8')` 获取
- 加入 ECharts CDN: `<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>`

- [ ] **Step 4: 验收**

```bash
curl -s http://127.0.0.1:8001/api/dashboard/metrics -H "Authorization: Bearer $TOKEN"
```
Expected: 返回包含 `active_agents`、`total_collected`、`risk_distribution` 等完整指标。

- [ ] **Step 5: Commit**

```bash
git add schema/api.py controller/dashboard_controller.py static/im-console.html seed.py
git commit -m "feat(B): 扩展仪表盘指标+控制台UI (#12)"
```

---

### Task 3: 模型引擎多模态 (#14) — model_type 扩展 + 创意工坊

**Files:**
- Modify: `models/ai_model.py`（model_type 注释更新，实际已是 String 不限制枚举值）
- Modify: `schema/api.py`（AIModelCreate 和 AIModelOut 的 model_type 注释更新为 chat/image/video/embedding/rerank）
- Modify: `controller/model_controller.py`（按 type 分发 image/video 路由）
- Create: `controller/creative_controller.py`（创意工坊：调用 image/video 模型）
- Modify: `static/model-management.html`（表单按 type 切换字段，加 image/video 选项）
- Create: `static/creative-workshop.html`（创意工坊页面 + 对应路由）
- Modify: `controller/page_controller.py`（添加 /creative 路由）

**Interfaces:**
- Consumes: `AIModelCreate` (schema/api.py)
- Produces: `POST /api/creative/generate`（image/video 生成端点）

- [ ] **Step 1: 创建 CreativeController**

```python
# controller/creative_controller.py
"""
创意工坊：调用 image/video 模型生成内容
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from database.session import SessionLocal, get_db
from core.security import get_current_user
from core.openai_client import OpenAIClient
from dao.model_dao import get_model, get_default_model
from models.user import User
import json, httpx

creative_router = APIRouter(prefix="/api/creative", tags=["创意工坊"])

class CreativeIn(BaseModel):
    prompt: str
    model_id: int | None = None
    type: str = "image"  # image / video
    n: int = 1
    size: str = "1024x1024"

class CreativeOut(BaseModel):
    success: bool
    urls: list[str] = []
    error: str = ""

@creative_router.post("/generate", response_model=CreativeOut)
async def generate(body: CreativeIn, db: SessionLocal = Depends(get_db),
                   user: User = Depends(get_current_user)):
    model_id = body.model_id
    if not model_id:
        default = get_default_model(db)
        if not default or default.model_type != body.type:
            # fallback: 找第一个匹配 type 的模型
            m = db.query(AIModel).filter(
                AIModel.model_type == body.type, AIModel.is_active == True
            ).first()
            if not m:
                raise HTTPException(400, f"无可用 {body.type} 模型")
            model_id = m.id
        else:
            model_id = default.id

    m = get_model(model_id, db)
    if not m:
        raise HTTPException(404, "模型不存在")
    if m.model_type != body.type:
        raise HTTPException(400, f"模型类型不匹配：需要 {body.type}，实际 {m.model_type}")

    try:
        client = OpenAIClient(api_key=m.api_key, endpoint=m.endpoint,
                              model_name=m.model_name, timeout=60)
        if body.type == "image":
            # 调 /v1/images/generations
            payload = {
                "model": m.model_name,
                "prompt": body.prompt,
                "n": body.n,
                "size": body.size,
            }
            async with httpx.AsyncClient(timeout=60) as http:
                resp = await http.post(
                    f"{m.endpoint.rstrip('/')}/v1/images/generations",
                    json=payload,
                    headers={"Authorization": f"Bearer {m.api_key}"}
                )
                data = resp.json()
            urls = [item["url"] for item in data.get("data", [])]
            await client.close()
            return CreativeOut(success=True, urls=urls)
        elif body.type == "video":
            # 视频生成端点（通用格式）
            payload = {
                "model": m.model_name,
                "prompt": body.prompt,
            }
            async with httpx.AsyncClient(timeout=120) as http:
                resp = await http.post(
                    f"{m.endpoint.rstrip('/')}/v1/video/generations",
                    json=payload,
                    headers={"Authorization": f"Bearer {m.api_key}"}
                )
                data = resp.json()
            urls = [item.get("url", item.get("video_url", "")) for item in data.get("data", [])]
            return CreativeOut(success=True, urls=urls)
        else:
            raise HTTPException(400, f"不支持的类型: {body.type}")
    except Exception as e:
        return CreativeOut(success=False, error=str(e))
```

- [ ] **Step 2: 更新 model-management.html 表单**

修改 `static/model-management.html` 中 type 下拉框选项：
```html
<select id="mType">
  <option value="chat">对话</option>
  <option value="image">图片生成</option>
  <option value="video">视频生成</option>
  <option value="embedding">嵌入</option>
  <option value="rerank">重排序</option>
</select>
```
并在选择 image/video 时显示额外字段（如 size/quality）：

```javascript
document.getElementById('mType').addEventListener('change', function() {
  const extra = document.getElementById('typeExtra');
  if (this.value === 'image') {
    extra.innerHTML = `<div><label class="text-xs text-on-surface-variant block mb-1">图片尺寸</label>
      <select id="mSize" class="w-full bg-surface-container-high/50 border rounded-lg px-3 py-2 text-sm">
        <option value="1024x1024">1024×1024</option><option value="1024x1792">1024×1792</option>
        <option value="1792x1024">1792×1024</option></select></div>`;
    extra.classList.remove('hidden');
  } else if (this.value === 'video') {
    extra.innerHTML = `<div><label class="text-xs text-on-surface-variant block mb-1">视频时长(秒)</label>
      <input id="mDuration" type="number" value="5" class="w-full bg-surface-container-high/50 border rounded-lg px-3 py-2 text-sm"/></div>`;
    extra.classList.remove('hidden');
  } else {
    extra.classList.add('hidden');
  }
});
```

- [ ] **Step 3: 创建创意工坊 HTML 页面**

`static/creative-workshop.html` — 简洁的输入 prompt → 展示生成结果页面，调用 `/api/creative/generate`。

- [ ] **Step 4: 注册路由 + 菜单**

在 `main.py`：
```python
from controller.creative_controller import creative_router
app.include_router(creative_router)
```

在 `controller/page_controller.py` 添加：
```python
@page_router.get("/creative", include_in_schema=False)
def creative_page():
    return FileResponse(os.path.join(STATIC_DIR, "creative-workshop.html"))
```

在 `seed.py` 的 `_seed_menus()` 中为 ROOT/OPS 添加：
```python
Menu(name="创意工坊", icon="palette", path="/creative", sort_order=14, role_codes="ROOT,OPS,USER"),
```

- [ ] **Step 5: Commit**

```bash
git add controller/creative_controller.py static/creative-workshop.html controller/page_controller.py seed.py main.py static/model-management.html
git commit -m "feat(B): 模型多模态扩展+创意工坊 (#14)"
```

---

### Task 4: 瞭源管理 (#17) + 数据采集 (#15) — 采集源 UI + 采集执行

**Files:**
- Modify: `static/data-collection.html`（现状：144 行轻壳，需改为完整的管理页面）
- Modify: `controller/dc_controller.py`（现状 301 行已有完整 CRUD + 采集 + 仓库，需微调）
- Modify: `models/data_collection.py`（可能补充字段）

**现状评估：** `dc_controller.py` 已完整实现了 `/sources` CRUD、`/crawl` 采集执行、`/warehouse` 数据仓库、`/deep-collect` 深度采集。`data-collection.html` 已有 4 个 tab 的壳（数据源/规则/采集/仓库），只需将 UI 打磨完整（添加源模板预填、测试连接等）。

- [ ] **Step 1: 补充 DataSourceConfig 模型：添加模板字段**

在 `models/data_collection.py` 添加字段：
```python
template = Column(String(50), default="")  # baidu/rss/custom
```

- [ ] **Step 2: 增强 data-collection.html**

将 `static/data-collection.html` 增强为完整的管理界面：
- **数据源管理 tab**：源列表卡片 + "添加数据源"按钮弹出模态框
  - 模态框顶部有 3 个模板按钮：「百度新闻」「RSS」「自定义网页」
  - 选择模板自动预填 name/url/parse_type/parse_rule
  - 保存后调 `POST /api/dc/sources`
  - 每个源卡片有"测试连接"按钮（调 `POST /api/dc/sources/{id}/test`）
- **清洗规则 tab**：规则列表 + 添加/删除
- **数据采集 tab**：关键词输入 + 源选择 + 规则选择 + "开始采集"按钮 → 展示结果
- **数据仓库 tab**：已保存数据列表 + 搜索 + 深度采集 + 删除

- [ ] **Step 3: 添加测试连接端点**

在 `controller/dc_controller.py` 添加：
```python
@dc_router.post("/sources/{ds_id}/test")
async def test_source(ds_id: int, db: SessionLocal = Depends(get_db),
                       user: User = Depends(get_current_user)):
    ds = db.query(DataSourceConfig).filter(DataSourceConfig.id == ds_id).first()
    if not ds: raise HTTPException(404, "数据源不存在")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(ds.url, headers=json.loads(ds.headers) if ds.headers else {})
        return {"success": resp.status_code < 500, "status_code": resp.status_code}
    except Exception as e:
        return {"success": False, "error": str(e)}
```

- [ ] **Step 4: 确保采集种子源包含百度新闻 + RSS + 自定义网页**

更新 `seed.py` 的 `_seed_sources_and_rules()`：
```python
DataSourceConfig(name="百度新闻搜索", url="https://news.baidu.com/ns?word={keyword}&tn=news",
                 method="GET", parse_type="selector", parse_rule=".result",
                 headers='{"User-Agent":"Mozilla/5.0"}', template="baidu"),
DataSourceConfig(name="36氪RSS", url="https://36kr.com/feed",
                 method="GET", parse_type="crawl4ai", parse_rule="",
                 headers='{"User-Agent":"Mozilla/5.0"}', template="rss"),
DataSourceConfig(name="知乎热门", url="https://www.zhihu.com/api/v3/feed/topstory?limit=20",
                 method="GET", parse_type="selector", parse_rule=".TopstoryItem",
                 headers='{"User-Agent":"Mozilla/5.0"}', template="custom"),
```

- [ ] **Step 5: Commit**

```bash
git add static/data-collection.html controller/dc_controller.py models/data_collection.py seed.py
git commit -m "feat(B): 瞭源管理UI增强+采集任务执行 (#17 #15)"
```

---

### Task 5: 用户/功能/权限/菜单管理 CRUD (#13)

**Files:**
- Modify: `static/permissions.html`（现状 555 行已有大壳，需补充 CRUD 交互）
- Modify: `controller/permission_controller.py`（现状已有角色 CRUD + 菜单 CRUD，需补充用户管理端点）
- Controller 端可能补充：`user_management` 端点

**现状评估：** `permission_controller.py` 已有角色 CRUD（/roles）和菜单 CRUD（/menus）、权限树（/tree）。前端 `permissions.html` 需要：
1. 用户管理 tab → 对接 `/api/smart-audit/users`（已有）加编辑用户角色
2. 角色管理 tab → 对接现有的 `/api/permissions/roles`
3. 菜单管理 tab → 对接现有的 `/api/permissions/menus`
4. 权限管理 tab → 显示权限树

- [ ] **Step 1: 补充用户管理端点（修改用户信息/启停用）**

在 `controller/permission_controller.py` 添加：
```python
@permission_router.get("/users")
def list_perm_users(search: str = Query(None), db: SessionLocal = Depends(get_db),
                     user: User = Depends(get_current_user)):
    q = db.query(User)
    if search:
        q = q.filter((User.username.contains(search)) | (User.nickname.contains(search)))
    return [{"id": u.id, "username": u.username, "nickname": u.nickname,
             "email": u.email, "role": u.role, "is_active": u.is_active,
             "created_at": u.created_at.isoformat() if u.created_at else None} for u in q.all()]

class UserUpdateIn(BaseModel):
    nickname: str | None = None
    email: str | None = None
    role: str | None = None
    is_active: bool | None = None

@permission_router.put("/users/{user_id}")
def update_perm_user(user_id: int, body: UserUpdateIn, db: SessionLocal = Depends(get_db),
                      user: User = Depends(get_current_user)):
    target = db.query(User).filter(User.id == user_id).first()
    if not target: raise HTTPException(404, "用户不存在")
    for k, v in body.model_dump().items():
        if v is not None: setattr(target, k, v)
    db.commit()
    log_action("user_update", f"管理员更新用户 {target.username}", user.username, db)
    return {"id": target.id, "username": target.username, "role": target.role, "is_active": target.is_active}
```

- [ ] **Step 2: 重写 permissions.html 为 4-Tab 管理页**

Tab1 - 用户管理：用户表格（用户名/昵称/邮箱/角色/状态/操作），支持搜索、编辑角色、启停用
Tab2 - 角色管理：角色列表 + 添加/编辑/删除角色 modal
Tab3 - 菜单管理：菜单列表 + 添加/编辑/删除菜单 modal
Tab4 - 权限树：调用 `/api/permissions/tree` 展示树形结构

所有操作调用已有的 API 端点，操作后刷新列表。

- [ ] **Step 3: Commit**

```bash
git add controller/permission_controller.py static/permissions.html
git commit -m "feat(B): 用户/角色/菜单管理CRUD (#13)"
```

---

### Task 6: 数据仓库深度采集 + 进度日志 (#16) — collection_task 表

**Files:**
- Create: `models/collection_task.py`
- Modify: `controller/dc_controller.py`（批量深度采集 + 进度查询）
- Modify: `static/data-collection.html`（在 warehouse tab 增加批量操作和进度条）

**Interfaces:**
- Consumes: `CollectedData`, `DataSourceConfig`
- Produces: `CollectionTask` model (id, source_id, keyword, total_count, completed_count, status, log, created_at, updated_at)
- Produces: `POST /api/dc/batch-deep-collect`, `GET /api/dc/tasks/{task_id}`, `GET /api/dc/tasks`

- [ ] **Step 1: 创建 CollectionTask 模型**

```python
# models/collection_task.py
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Text
from database.session import Base

class CollectionTask(Base):
    __tablename__ = "collection_tasks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    keyword = Column(String(200), default="")
    source_ids = Column(String(200), default="")     # 逗号分隔
    total_count = Column(Integer, default=0)
    completed_count = Column(Integer, default=0)
    status = Column(String(20), default="pending")   # pending/running/completed/failed
    log = Column(Text, default="")                    # 日志内容
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
```

- [ ] **Step 2: 批量深度采集端点**

在 `controller/dc_controller.py` 添加：
```python
@dc_router.post("/batch-deep-collect")
async def batch_deep_collect(body: CrawlIn, db: SessionLocal = Depends(get_db),
                              user: User = Depends(get_current_user)):
    """批量深度采集：创建任务，异步采集"""
    task = CollectionTask(keyword=body.keyword, source_ids=",".join(str(s) for s in body.source_ids),
                          status="running", log=f"开始批量深度采集: keyword={body.keyword}\n")
    db.add(task)
    db.commit()
    db.refresh(task)

    # 同步执行（简化版：实际项目可用后台任务）
    import asyncio
    sources = db.query(DataSourceConfig).filter(
        DataSourceConfig.id.in_(body.source_ids)
    ).all() if body.source_ids else db.query(DataSourceConfig).all()
    items_to_collect = db.query(CollectedData).filter(
        CollectedData.keyword == body.keyword,
        CollectedData.saved == True,
        CollectedData.deep_collected == False
    ).all()

    task.total_count = len(items_to_collect)
    completed = 0
    for item in items_to_collect:
        try:
            # 复用单个深度采集逻辑
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(item.url, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True)
                soup = BeautifulSoup(resp.text, "html.parser")
                for tag in soup(["script", "style", "nav", "footer"]): tag.decompose()
                item.content = soup.get_text(separator="\n", strip=True)[:8000]
                item.deep_collected = True
            completed += 1
            task.completed_count = completed
            task.log += f"[OK] {item.title or item.url[:50]}... 深度采集完成\n"
        except Exception as e:
            task.log += f"[FAIL] {item.title or item.url[:50]}... 错误: {str(e)}\n"
        db.commit()

    task.status = "completed" if completed == task.total_count else "failed"
    task.log += f"批量深度采集结束: {completed}/{task.total_count} 完成\n"
    db.commit()
    return {"task_id": task.id, "status": task.status, "completed": completed, "total": task.total_count}
```

- [ ] **Step 3: 任务进度查询端点**

```python
@dc_router.get("/tasks")
def list_tasks(db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(CollectionTask).order_by(CollectionTask.created_at.desc()).limit(20).all()

@dc_router.get("/tasks/{task_id}")
def get_task(task_id: int, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    task = db.query(CollectionTask).filter(CollectionTask.id == task_id).first()
    if not task: raise HTTPException(404, "任务不存在")
    return task
```

- [ ] **Step 4: 更新 data-collection.html 仓库 tab 增加进度条**

在 warehouse tab 列表上方增加批量深度采集按钮和进度条。
```html
<div id="batchProgress" class="hidden bg-surface-container-high/50 rounded-xl p-4 mb-4">
  <div class="flex items-center justify-between mb-2">
    <span class="text-sm font-bold">批量深度采集进度</span>
    <span id="batchStatus" class="text-xs text-secondary">运行中...</span>
  </div>
  <div class="w-full bg-surface-container rounded-full h-2">
    <div id="batchBar" class="bg-secondary h-2 rounded-full transition-all" style="width:0%"></div>
  </div>
  <pre id="batchLog" class="mt-2 text-[10px] text-on-surface-variant max-h-32 overflow-y-auto"></pre>
</div>
```

- [ ] **Step 5: Commit**

```bash
git add models/collection_task.py controller/dc_controller.py static/data-collection.html main.py
git commit -m "feat(B): 数据仓库深度采集+进度日志 (#16)"
```

---

### Task 7: 接口管理 (#18) — api_registry + 接口型数字员工联动

**Files:**
- Create: `models/api_registry.py`
- Create: `controller/api_controller.py`
- Create: `static/api-registry.html`
- Modify: `controller/page_controller.py`（添加 /api-registry 路由）
- Modify: `controller/agent_controller.py`（添加"从接口生成数字员工"端点）
- Modify: `main.py`（注册 router）
- Modify: `seed.py`（菜单）

**Interfaces:**
- Produces: `ApiRegistry` model (id, name, method, url, headers, body_template, response_path, description, created_at)
- Produces: `CRUD /api/registry/*` + `POST /api/registry/{id}/test` + `POST /api/registry/{id}/create-agent`

- [ ] **Step 1: 创建 ApiRegistry 模型**

```python
# models/api_registry.py
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Text
from database.session import Base

class ApiRegistry(Base):
    __tablename__ = "api_registry"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    method = Column(String(10), default="GET")
    url = Column(String(1000), nullable=False)
    headers = Column(Text, default="{}")
    body_template = Column(Text, default="")
    response_path = Column(String(200), default="")       # JSONPath 如 data.result
    description = Column(String(500), default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
```

- [ ] **Step 2: 创建 API Registry Controller**

```python
# controller/api_controller.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from database.session import SessionLocal, get_db
from core.security import get_current_user
from dao.base_dao import log_action
from models.user import User
from models.api_registry import ApiRegistry
from models.agent import Agent
import json, httpx

api_registry_router = APIRouter(prefix="/api/registry", tags=["接口管理"])

# CRUD (遵循现有模式)
class ApiCreateIn(BaseModel):
    name: str; method: str = "GET"; url: str; headers: str = "{}"
    body_template: str = ""; response_path: str = ""; description: str = ""

class ApiUpdateIn(BaseModel):
    name: str | None = None; method: str | None = None; url: str | None = None
    headers: str | None = None; body_template: str | None = None
    response_path: str | None = None; description: str | None = None

@api_registry_router.get("")
def list_apis(db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(ApiRegistry).order_by(ApiRegistry.created_at.desc()).all()

@api_registry_router.post("", status_code=201)
def create_api(body: ApiCreateIn, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    api = ApiRegistry(**body.model_dump())
    db.add(api); db.commit(); db.refresh(api)
    log_action("api_create", f"创建接口: {body.name}", user.username, db)
    return {"id": api.id, "name": api.name}

@api_registry_router.put("/{api_id}")
def update_api(api_id: int, body: ApiUpdateIn, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    api = db.query(ApiRegistry).filter(ApiRegistry.id == api_id).first()
    if not api: raise HTTPException(404, "接口不存在")
    for k, v in body.model_dump().items():
        if v is not None: setattr(api, k, v)
    db.commit()
    return {"updated": True}

@api_registry_router.delete("/{api_id}")
def delete_api(api_id: int, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    db.query(ApiRegistry).filter(ApiRegistry.id == api_id).delete()
    db.commit()
    return {"deleted": True}

@api_registry_router.post("/{api_id}/test")
async def test_api(api_id: int, params: str = "{}", db: SessionLocal = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """在线测试接口"""
    api = db.query(ApiRegistry).filter(ApiRegistry.id == api_id).first()
    if not api: raise HTTPException(404, "接口不存在")
    try:
        headers = json.loads(api.headers) if api.headers else {}
        async with httpx.AsyncClient(timeout=30) as client:
            if api.method == "POST":
                body = api.body_template
                if params: body = body.replace("{params}", params)
                resp = await client.post(api.url, content=body, headers=headers)
            else:
                url = api.url.replace("{params}", params)
                resp = await client.get(url, headers=headers, follow_redirects=True)
        return {"success": resp.status_code < 500, "status_code": resp.status_code,
                "response": resp.text[:2000]}
    except Exception as e:
        return {"success": False, "error": str(e)}

@api_registry_router.post("/{api_id}/create-agent")
def create_agent_from_api(api_id: int, agent_name: str = "",
                           db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    """从接口生成数字员工"""
    api = db.query(ApiRegistry).filter(ApiRegistry.id == api_id).first()
    if not api: raise HTTPException(404, "接口不存在")
    name = agent_name or f"{api.name}员工"
    agent = Agent(
        name=name, base_model="", model_id=None,
        persona_prompt=f"你是一个接口助手，负责调用 {api.name} 接口回答用户问题。\n接口URL: {api.url}\n方法: {api.method}\n当用户询问相关内容时，调用该接口并返回结果。",
        skill_bindings=f"api_{api.id}",
        status="draft", description=f"由接口 [{api.name}] 自动生成的数字员工",
    )
    db.add(agent); db.commit(); db.refresh(agent)
    log_action("agent_create", f"从接口生成数字员工: {name}", user.username, db)
    return {"id": agent.id, "name": agent.name, "api_name": api.name}
```

- [ ] **Step 3: 创建接口管理 HTML 页面**

`static/api-registry.html` — 简洁的表格+模态框 CRUD 页面，调用 `/api/registry/*`。

- [ ] **Step 4: 注册路由 + 菜单**

在 `main.py` 注册 `api_registry_router`，在 `page_router` 添加 `/api-registry` 路由，在 `seed.py` `_seed_menus()` 添加菜单。

- [ ] **Step 5: Commit**

```bash
git add models/api_registry.py controller/api_controller.py static/api-registry.html controller/page_controller.py main.py seed.py
git commit -m "feat(B): 接口管理+接口型数字员工联动 (#18)"
```

---

### Task 8: 数字员工管理 (#19) — 模型型+接口型员工统一管理

**Files:**
- Modify: `static/agent-management.html`（现状 298 行，需增强为双 tab 管理）
- Modify: `controller/agent_controller.py`（现状 152 行已有完整 CRUD，接口型员工已有创建端点 #18）

**现状评估：** `agent_controller.py` 已有完整的 CRUD（list、create、update、delete）。前端 `agent-management.html` 已有基本壳，需：
- 分两个 tab：「大模型型员工」「接口型员工」
- 大模型型：对接 `/api/agents`，显示模型名称、技能列表、状态、发布/停用
- 接口型：对接 `/api/agents` 但显示绑定的接口信息（通过 `skill_bindings` 含 `api_` 前缀判断）
- 发布/停用按钮 → `PUT /api/agents/{id}` 改 status

- [ ] **Step 1: 重写 agent-management.html**

`static/agent-management.html` 改为：
- 顶部两个 tab 按钮
- 大模型型 tab：卡片列表（头像、名称、描述、模型、技能标签、状态badge、发布/停用/编辑/删除）
- 接口型 tab：卡片列表（同上，额外显示接口名称）
- 新增 modal：名称、描述、base_model、model_id（下拉选择）、skill_ids（多选）、persona_prompt
- 前端通过 `skill_bindings` 是否以 `api_` 开头判断类型

- [ ] **Step 2: 补充 agent_controller 返回 agent_type 字段**

在 `agent_controller.py` 的 `list_all()` 返回中添加：
```python
"agent_type": "api" if a.skill_bindings and a.skill_bindings.startswith("api_") else "model",
```

- [ ] **Step 3: Commit**

```bash
git add static/agent-management.html controller/agent_controller.py
git commit -m "feat(B): 数字员工管理双tab (#19)"
```

---

### Task 9: 会话管理 + 对话管理 (#20)

**Files:**
- Modify: `static/chat-management.html`（现状 91 行轻壳，需完整）
- Modify: `static/messages.html`（现状 320 行已有消息列表）
- Modify: `controller/message_controller.py` 或 `controller/im_controller.py`（补充管理端点）

**现状评估：** `chat-management.html` 很轻（群管理/聊天记录/群文件 3 tab），`messages.html` 已有 320 行消息列表。需要：
1. 会话列表（全用户会话）→ 新增端点 `GET /api/admin/conversations`
2. 消息检索/导出/删除 → 复用 `/api/messages/history` 和 `/api/smart-audit/messages`
3. 敏感会话标红 → 前端根据 `risk_level` 标红

- [ ] **Step 1: 创建管理员会话列表端点**

在 `controller/im_controller.py` 末尾或新文件 `controller/admin_controller.py`：
```python
@im_router.get("/admin/conversations")
def admin_conversations(limit: int = 50, db: SessionLocal = Depends(get_db),
                         user: User = Depends(get_current_user)):
    """管理员查看所有用户最近会话（按用户聚合）"""
    from sqlalchemy import func
    # 按 sender_id 分组取最近消息
    subq = db.query(
        Message.sender_id,
        Message.receiver_id,
        Message.group_id,
        func.max(Message.created_at).label("last_time")
    ).group_by(Message.sender_id).subquery()
    
    convs = []
    for row in db.query(Message).filter(
        Message.created_at.in_(db.query(subq.c.last_time))
    ).order_by(Message.created_at.desc()).limit(limit).all():
        sender = db.query(User).filter(User.id == row.sender_id).first()
        convs.append({
            "user_id": row.sender_id,
            "username": sender.username if sender else f"用户{row.sender_id}",
            "last_message": (row.content or "")[:100],
            "last_time": row.created_at.isoformat() if row.created_at else None,
            "is_sensitive": False,  # 前端根据 risk 判断标红
        })
    return convs
```

- [ ] **Step 2: 完善 chat-management.html**

将 `static/chat-management.html` 增强为完整管理页：
- 会话列表 tab：表格（用户/最后消息/最后时间/风险标签/操作），点击进入对话详情
- 对话详情 modal：显示该用户最近 20 条消息，按 risk_level 标红
- 消息检索 tab：搜索框 → 调 `/api/smart-audit/messages?limit=200` 前端过滤
- 敏感会话自动标红（`risk_level === 'high'` 时整行红色边框）

- [ ] **Step 3: Commit**

```bash
git add controller/im_controller.py static/chat-management.html
git commit -m "feat(B): 会话管理+对话管理 (#20)"
```

---

### Task 10: 数智大屏 (#21) — 3D 地球 + 词云 + 统计

**Files:**
- Modify: `static/digital-screen.html`（现状 572 行已有壳含 3D 地球占位）
- Modify: `controller/dashboard_controller.py`（补充大屏专用数据端点）

**约束：** 大屏放最后做，依赖 #15 #16（数据齐了再渲染）

- [ ] **Step 1: 创建大屏专用数据端点**

在 `controller/dashboard_controller.py` 或新建 `controller/screen_controller.py`：
```python
@dashboard_router.get("/screen-data")
def screen_data(db: SessionLocal = Depends(get_db), current: User = Depends(get_current_user)):
    """大屏专用：采集量/活跃员工/实时消息流+词云数据"""
    # 按 source_name 统计采集量（模拟国家分布）
    source_stats = db.query(
        CollectedData.source_name, func.count(CollectedData.id)
    ).filter(CollectedData.saved == True).group_by(CollectedData.source_name).all()
    
    # 词云数据
    keywords_all = []
    for cd in db.query(CollectedData.keywords_extracted).filter(
        CollectedData.keywords_extracted != "", CollectedData.saved == True
    ).limit(100).all():
        try:
            keywords_all.extend(json.loads(cd.keywords_extracted))
        except: pass
    wordcloud = {}
    for kw in keywords_all:
        wordcloud[kw] = wordcloud.get(kw, 0) + 1
    
    # 活跃员工
    active_agents = db.query(Agent).filter(Agent.status == "published").count()
    
    # 采集总量
    total_collected = db.query(CollectedData).filter(CollectedData.saved == True).count()
    
    # 实时消息流（最近20条消息）
    recent_msgs = db.query(Message).order_by(Message.created_at.desc()).limit(20).all()
    
    return {
        "source_stats": [{"name": s[0], "value": s[1]} for s in source_stats],
        "wordcloud": [{"name": k, "value": v} for k, v in sorted(wordcloud.items(), key=lambda x: -x[1])[:50]],
        "active_agents": active_agents,
        "total_collected": total_collected,
        "total_messages": db.query(Message).count(),
        "recent_messages": [{"content": (m.content or "")[:50], "time": m.created_at.isoformat() if m.created_at else ""} for m in recent_msgs],
    }
```
需 import: `from models.agent import Agent`, `from models.message import Message`, `import json`。

- [ ] **Step 2: 重写 digital-screen.html**

保留现有大屏布局框架，替换为三个核心区域：
1. **左上：3D 地球**（ECharts GL geo3D，展示采集源国家分布）
   - 用 `source_stats` 数据在地球上散点标注
   - CDN: `https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js`
   - CDN: `https://cdn.jsdelivr.net/npm/echarts-gl@2/dist/echarts-gl.min.js`
2. **右上：数据统计卡片 + 滚动数字**（采集量/活跃员工/消息总数）
3. **底部：词云**（ECharts Wordcloud，用 `wordcloud` 数据）
   - CDN: `https://cdn.jsdelivr.net/npm/echarts-wordcloud@2/dist/echarts-wordcloud.min.js`

布局：全屏（`h-screen`），grid 划分三个区域，数据每 30 秒刷新一次。

- [ ] **Step 3: 填充种子数据使大屏有内容**

在 `seed.py` 的 `_seed_sources_and_rules()` 末尾添加采集样本数据（使大屏不为空）：
```python
if not db.query(CollectedData).first():
    sample_keywords = json.dumps(["数据治理", "人工智能", "大模型", "安全", "云计算", "物联网"], ensure_ascii=False)
    for i in range(30):
        cd = CollectedData(
            source_name=random.choice(["百度新闻", "新浪新闻", "36氪"]),
            keyword="AI",
            title=f"AI行业动态第{i+1}条",
            content=f"这是AI行业动态第{i+1}条的内容摘要...",
            summary=f"AI行业第{i+1}条摘要",
            keywords_extracted=sample_keywords,
            sentiment=random.choice(["positive", "neutral", "negative"]),
            saved=True, deep_collected=True,
        )
        db.add(cd)
    print("[seed] 采集样本数据写入完成")
```
注意：`random` 需 import。

- [ ] **Step 4: Commit**

```bash
git add controller/dashboard_controller.py static/digital-screen.html seed.py
git commit -m "feat(B): 数智大屏-3D地球+词云+统计 (#21)"
```

---

### Task 11: 舆情大屏 (#22) — 敏感词预警 + AI 风险分析

**Files:**
- Modify: `static/smart-audit.html`（现状 53 行最轻壳 → 完整大屏）
- Modify: `controller/smart_audit_controller.py`（补充 AI 风险分析端点）
- Modify: `core/sensitive_filter.py`（如需要扩展）

**现状评估：** `smart-audit.html` 只有 53 行（最轻的壳），`smart_audit_controller.py` 已有 203 行完整实现（消息审计、采集数据审计、封禁管理）。

- [ ] **Step 1: 补充 AI 风险分析端点**

在 `controller/smart_audit_controller.py` 末尾添加：
```python
@smart_audit.post("/ai-analyze")
async def ai_risk_analyze(
    conversation_id: str = Query(""), data_id: int = Query(None),
    db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    """将当前会话或采集数据送 LLM 做风险分析"""
    chat_model = get_default_model(db)
    if not chat_model or "placeholder" in chat_model.api_key:
        return {"analysis": "无法执行 AI 分析：未配置有效的 API Key"}
    
    content = ""
    if data_id:
        d = db.query(CollectedData).filter(CollectedData.id == data_id).first()
        if d: content = (d.title or "") + "\n" + (d.content or "")[:3000]
    elif conversation_id:
        msgs = db.query(Message).filter(...).limit(20).all()
        content = "\n".join(m.content for m in msgs if m.content)[:4000]
    
    if not content:
        raise HTTPException(400, "无可分析的内容")
    
    client = OpenAIClient(api_key=chat_model.api_key, endpoint=chat_model.endpoint,
                          model_name=chat_model.model_name, temperature=0.3, max_tokens=1024)
    try:
        prompt = f"""请对以下内容进行安全风险分析，以JSON格式返回：
{{
  "risk_level": "high/medium/low",
  "risk_types": ["涉政", "涉黄", "涉恐", "暴恐", "广告", "正常"],
  "analysis": "分析结论（100字以内）",
  "suggestions": "建议措施"
}}
内容：{content[:4000]}"""
        resp = await client.chat_completion([{"role": "user", "content": prompt}])
        text = OpenAIClient.extract_content(resp)
        try:
            result = json.loads(text.strip().strip("`").strip("json").strip())
        except:
            result = {"risk_level": "unknown", "analysis": text[:200], "suggestions": ""}
        return result
    finally:
        await client.close()
```

- [ ] **Step 2: 重写 smart-audit.html**

`static/smart-audit.html` 重写为舆情大屏风格：
1. **顶部**：敏感词实时命中数字滚动 + 风险等级分布饼图（ECharts）
2. **中部**：最近敏感消息列表（调 `/api/smart-audit/messages`），按 risk_level 颜色区分
3. **右侧**：AI 一键分析面板（输入会话ID → 调用 `/api/smart-audit/ai-analyze` → 展示分析结果）
4. **底部**：采集数据情感分布柱状图（调 `/api/smart-audit/data`）

布局：类似于数字大屏但更紧凑，适合监控场景。

- [ ] **Step 3: 用户端敏感词预警联动**

在 `core/sensitive_filter.py` 已有的 `filter_content()` 基础上，确保：
- 对话消息经过敏感词过滤时，若命中 `action=block` 的词，返回 warning 给前端
- 在 `de-chat.html` 中，前端检测到 `warning` 响应时弹 toast 预警

此步骤跨 A 线，简化为：后端 `sensitive_filter.py` 已在 `de_controller.py` 的聊天流程中被调用（需确认）→ 只需在前端 `app.js` 中统一处理 `warning` 字段。

- [ ] **Step 4: Commit**

```bash
git add controller/smart_audit_controller.py static/smart-audit.html core/sensitive_filter.py
git commit -m "feat(B): 舆情大屏-敏感词预警+AI风险分析 (#22)"
```

---

### Task 12: 种子数据补齐 + 整体验收

**Files:**
- Modify: `seed.py`（确认所有种子数据完整，菜单覆盖所有 B 线页面）

- [ ] **Step 1: 确认 seed.py 覆盖以下集合**

- 5 角色（ROOT/AUDIT/OPS/USER/GUEST）
- 4+ 用户（admin/demo/zhang_san/li_si）
- 4+ AI 模型（GPT-4o/DeepSeek/embedding/Claude）
- 4+ 技能（时间/计算器/天气/审计）
- 6+ 数字员工（金融/舆情/审计/运维/天气助手/代码助手）
- 8+ 审计日志
- 5+ 敏感词
- 3+ 采集源（百度/RSS/自定义）
- 5+ 清洗规则
- 30+ 采集样本数据（CollectedData）以使大屏有内容
- 19+ 菜单（覆盖所有 B 线页面）
- 7+ 系统设置

- [ ] **Step 2: 启动验收**

```bash
rm -f data_outlook_v2.db
python main.py
```

依次验证：
- [ ] 登录 admin（POST /api/auth/login → 200 + token）
- [ ] 仪表盘指标（GET /api/dashboard/metrics → 包含 active_agents/total_collected）
- [ ] 权限菜单 CRUD（GET /api/permissions/menus → 19+ 条）
- [ ] 模型列表（GET /api/models → 4+ 条含 image/video 类型）
- [ ] 数据采集源（GET /api/dc/sources → 3+ 条）
- [ ] 系统设置（GET /api/settings → 7+ 条）
- [ ] 接口注册（POST/GET /api/registry → CRUD 正常）
- [ ] 数字员工（GET /api/agents → 6+ 条）
- [ ] 会话管理（GET /api/im/admin/conversations → 返回数据）
- [ ] 大屏数据（GET /api/dashboard/screen-data → 包含 wordcloud/source_stats）
- [ ] 所有页面 HTML（/dashboard /de /models /skills /agent-management /permissions /data-collection /settings /screen /smart-audit /chat-management /messages → 全部 200）

- [ ] **Step 3: Commit final**

```bash
git add seed.py
git commit -m "feat(B): 种子数据补齐+全链路验收 (#ALL)"
git push origin feat/B
```

---

## 依赖拓扑

```
Task1 (#23 系统设置)     — 无前驱，可最早开始
Task2 (#12 仪表盘)       — 依赖 #3（底座，已合入）
Task3 (#14 多模态)       — 依赖 #3
Task4 (#17+#15 采集)     — 依赖 #3
Task5 (#13 权限CRUD)     — 依赖 #2（底座菜单）
Task6 (#16 深度采集)     — 依赖 Task4 (#15)
Task7 (#18 接口管理)     — 无前驱
Task8 (#19 员工管理)     — 依赖 Task3 (#14) + Task7 (#18)
Task9 (#20 会话管理)     — 无前驱
Task10 (#21 数智大屏)    — 依赖 Task4 (#15) + Task6 (#16)
Task11 (#22 舆情大屏)    — 依赖 Task9 (#20)
Task12 (种子+验收)       — 依赖全部
```

**推荐并行：** Task1 + Task7 + Task9 可同时进行（无前驱）；Task4 + Task5 可同时进行；Task3 独立。全部完成后执行 Task12 统一验收。
