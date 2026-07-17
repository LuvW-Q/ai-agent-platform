/**
 * app.js — 智能数据瞭望系统前端公共库
 * 提供Token管理、API请求封装、路由守卫、工具函数
 */

/* ========== Token 管理 ========== */
const Token = {
  _access: sessionStorage.getItem('access_token'),
  get access() { return this._access || sessionStorage.getItem('access_token'); },
  get refresh() { return null; },
  set(v) {
    this._access = v.access_token;
    sessionStorage.setItem('access_token', v.access_token);
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
  },
  clear() {
    this._access = null;
    sessionStorage.removeItem('access_token');
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
  },
  exists() { return !!this.access; }
};

/* ========== 统一浅色科技主题 ========== */
function ensureTechLightTheme() {
  document.documentElement.classList.remove('dark');
  document.documentElement.classList.add('tech-light');
  document.body?.classList.add('tech-light');
  if (document.querySelector('link[data-tech-light-theme]')) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = '/static/css/tech-light.css?v=20260717-1';
  link.setAttribute('data-tech-light-theme', '');
  document.head.appendChild(link);
}

ensureTechLightTheme();

function preloadMaterialSymbols() {
  if (document.querySelector('[data-material-symbols-preload]')) return;
  const preload = document.createElement('span');
  preload.className = 'material-symbols-outlined';
  preload.setAttribute('data-material-symbols-preload', '');
  preload.setAttribute('aria-hidden', 'true');
  preload.textContent = String.fromCodePoint(0xe0c9);
  Object.assign(preload.style, {
    position: 'fixed', left: '-10000px', top: '0', width: '1px', height: '1px',
    overflow: 'hidden', pointerEvents: 'none'
  });
  document.body.appendChild(preload);
}

preloadMaterialSymbols();

/* ========== API 请求封装 ========== */
async function api(path, opts = {}) {
  const url = path.startsWith('http') ? path : path;
  const headers = { ...opts.headers };
  if (!(opts.body instanceof FormData)) {
    headers['Content-Type'] = headers['Content-Type'] || 'application/json';
  }
  if (Token.access) headers['Authorization'] = `Bearer ${Token.access}`;

  let res = await fetch(url, { ...opts, headers });

  // 401 → 尝试刷新令牌
  if (res.status === 401) {
    const refreshed = await tryRefresh();
    if (refreshed) {
      headers['Authorization'] = `Bearer ${Token.access}`;
      res = await fetch(url, { ...opts, headers });
    } else {
      Token.clear();
      window.location.href = '/login';
      throw new Error('未授权，请重新登录');
    }
  }

  if (!res.ok) {
    let message = `请求失败（HTTP ${res.status}）`;
    try {
      const errorBody = await res.clone().json();
      if (typeof errorBody.detail === 'string') message = errorBody.detail;
      else if (errorBody.detail !== undefined) message = JSON.stringify(errorBody.detail);
    } catch (error) {}
    const apiError = new Error(message);
    apiError.status = res.status;
    throw apiError;
  }
  return res;
}

async function apiGet(path) {
  const res = await api(path);
  return res.json();
}

async function apiPost(path, body) {
  const res = await api(path, {
    method: 'POST',
    body: JSON.stringify(body)
  });
  return res.json();
}

async function apiDelete(path) {
  const res = await api(path, { method: 'DELETE' });
  return res.json();
}

async function apiPut(path, body) {
  const res = await api(path, {
    method: 'PUT',
    body: JSON.stringify(body)
  });
  return res.json();
}

async function apiPatch(path, body) {
  const res = await api(path, {
    method: 'PATCH',
    body: JSON.stringify(body)
  });
  return res.json();
}

async function tryRefresh() {
  try {
    const res = await fetch('/api/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    });
    if (!res.ok) return false;
    const data = await res.json();
    Token.set(data);
    return true;
  } catch { return false; }
}

/* ========== 路由守卫 ========== */
function requireAuth() {
  if (!Token.exists()) {
    window.location.href = '/login';
    return false;
  }
  return true;
}

/* ========== 工具函数 ========== */
function fmtNum(n) {
  return new Intl.NumberFormat('en-US').format(n);
}

function fmtTime(iso) {
  const d = new Date(iso);
  return d.toLocaleString('zh-CN', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function timeAgo(iso) {
  const diff = Date.now() - new Date(iso).getTime();
  const min = Math.floor(diff / 60000);
  if (min < 1) return '刚刚';
  if (min < 60) return min + '分钟前';
  const hr = Math.floor(min / 60);
  if (hr < 24) return hr + '小时前';
  return Math.floor(hr / 24) + '天前';
}

function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s || '';
  return div.innerHTML;
}

const TRANSPARENT_PIXEL = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==';

function normalizeProtectedMediaUrl(url) {
  if (typeof url !== 'string') return '';
  if (url.startsWith('/uploads/')) return '/api/uploads/' + url.slice('/uploads/'.length);
  return url;
}

function protectedImageAttrs(url) {
  const normalized = normalizeProtectedMediaUrl(url);
  if (normalized.startsWith('/api/uploads/')) {
    return `src="${TRANSPARENT_PIXEL}" data-protected-src="${escapeHtml(normalized)}"`;
  }
  return `src="${escapeHtml(normalized)}"`;
}

async function setProtectedImage(img, url) {
  if (!img) return;
  const normalized = normalizeProtectedMediaUrl(url);
  if (!normalized.startsWith('/api/uploads/')) {
    img.src = normalized;
    return;
  }
  img.src = TRANSPARENT_PIXEL;
  img.dataset.protectedSrc = normalized;
  try {
    const response = await fetch(normalized, {
      headers: { 'Authorization': `Bearer ${Token.access}` }
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const objectUrl = URL.createObjectURL(await response.blob());
    const oldUrl = img.dataset.objectUrl;
    img.src = objectUrl;
    img.dataset.objectUrl = objectUrl;
    if (oldUrl) URL.revokeObjectURL(oldUrl);
  } catch (error) {
    console.warn('受保护图片加载失败:', error);
  }
}

function hydrateProtectedImages(root = document) {
  const images = [];
  if (root.matches?.('img[data-protected-src]')) images.push(root);
  root.querySelectorAll?.('img[data-protected-src]').forEach(img => images.push(img));
  images.forEach(img => {
    if (img.dataset.protectedLoading === '1' || img.dataset.objectUrl) return;
    img.dataset.protectedLoading = '1';
    setProtectedImage(img, img.dataset.protectedSrc).finally(() => {
      img.dataset.protectedLoading = '0';
    });
  });
}

const protectedImageObserver = new MutationObserver(mutations => {
  mutations.forEach(mutation => mutation.addedNodes.forEach(node => {
    if (node.nodeType === Node.ELEMENT_NODE) hydrateProtectedImages(node);
  }));
});

document.addEventListener('DOMContentLoaded', () => {
  hydrateProtectedImages();
  protectedImageObserver.observe(document.body, { childList: true, subtree: true });
});

const PAGE_META = {
  dashboard: { title: '控制台', desc: '在线用户、消息、采集、审计和数字员工运行态势', icon: 'space_dashboard' },
  'data-governance': { title: '数据治理', desc: '统一管理数据源、采集链路、治理规则与任务状态', icon: 'database' },
  screen: { title: '数字大屏', desc: '关键指标、风险事件与系统运行态势总览', icon: 'monitoring', fluid: true },
  models: { title: '模型管理', desc: '配置 OpenAI 协议兼容模型、嵌入模型与默认模型策略', icon: 'model_training' },
  skills: { title: '技能管理', desc: '维护工具调用、提示词技能、AI 生成技能与测试结果', icon: 'extension' },
  'agent-management': { title: '员工管理', desc: '创建、绑定模型/技能并发布数字员工', icon: 'precision_manufacturing' },
  agents: { title: '员工编排', desc: '面向任务流程编排数字员工能力与协作关系', icon: 'smart_toy' },
  de: { title: '数字员工', desc: '与已发布数字员工对话，查看技能调用链路', icon: 'forum', fluid: true },
  workflows: { title: '工作流', desc: '可视化编排节点、运行校验并保存自动化流程', icon: 'account_tree', fluid: true },
  rag: { title: 'RAG 管理', desc: '知识库、文档切片、嵌入模型和检索配置', icon: 'book_4' },
  permissions: { title: '权限管理', desc: '角色、权限树、用户授权和权限审计', icon: 'admin_panel_settings' },
  audit: { title: '审计管理', desc: '审计日志检索、风险分布和事件追踪', icon: 'security' },
  'smart-audit': { title: '智能审计', desc: '消息敏感度、舆情情感和封禁治理闭环', icon: 'gavel' },
  'chat-management': { title: '聊天管理', desc: '群组、聊天记录和文件消息集中管理', icon: 'chat_bubble' },
  'data-collection': { title: '数据采集', desc: '配置数据源、清洗规则、采集任务与数据仓库', icon: 'cloud_download' },
  messages: { title: '消息中心', desc: '查看最近会话、好友申请与系统通知', icon: 'chat' },
  im: { title: 'IM 控制台', desc: '即时通信、会话列表和消息收发控制台', icon: 'forum', fluid: true },
  query: { title: '智能问数', desc: '用自然语言查询数据，自动生成 SQL 与图表', icon: 'terminal' },
  settings: { title: '个人设置', desc: '账号资料、安全配置和通知偏好', icon: 'settings' },
};

function createPageHero(meta, active, main) {
  if (!meta || meta.fluid || main.querySelector(':scope > [data-app-page-hero]')) return;

  const hero = document.createElement('section');
  hero.className = 'app-page-hero';
  hero.setAttribute('data-app-page-hero', '');
  hero.innerHTML = `
    <div class="app-page-title">
      <div class="app-page-icon"><span class="material-symbols-outlined">${meta.icon}</span></div>
      <div>
        <p class="app-page-kicker">DATA OUTLOOK / ${active.toUpperCase()}</p>
        <h1>${meta.title}</h1>
        <p>${meta.desc}</p>
      </div>
    </div>
    <div class="app-page-actions"></div>`;

  const headerCandidates = Array.from(main.children);
  if (active === 'dashboard') {
    const dashboardContent = main.querySelector(':scope > div');
    headerCandidates.push(...Array.from(dashboardContent?.children || []));
  }

  const legacyHeader = headerCandidates.find(el => {
    if (el.matches('[data-app-page-hero], script, style')) return false;
    const hasTitle = !!el.querySelector('h1');
    const isLikelyHeader = /justify-between|items-center|mb-6|mb-8|mb-4/.test(el.className || '');
    const isComplexWorkspace = /glass-panel|h-screen|grid-cols-12/.test(el.className || '');
    return hasTitle && isLikelyHeader && !isComplexWorkspace;
  });

  if (legacyHeader) {
    const actionSource = legacyHeader.children.length > 1 ? legacyHeader.children[1] : null;
    if (actionSource) {
      actionSource.classList.add('app-page-actions-inner');
      hero.querySelector('.app-page-actions').appendChild(actionSource);
    }
    legacyHeader.setAttribute('data-legacy-page-header', '');
    legacyHeader.style.display = 'none';
  }

  main.prepend(hero);
}

function enhancePageLayout(active) {
  const main = document.querySelector('main');
  if (!main) return;

  const meta = PAGE_META[active] || PAGE_META.dashboard;
  main.dataset.page = active || 'unknown';
  main.classList.add('app-page');
  if (meta.fluid) {
    main.classList.add('app-page-fluid');
  } else {
    main.classList.remove('app-page-fluid');
    createPageHero(meta, active, main);
  }

  main.querySelectorAll('.glass-panel, section, article, [class*="bg-surface-container/"], [class*="bg-surface-container "], [class*="bg-surface-container-high/"]').forEach(el => {
    if (el.closest('[data-app-page-hero]')) return;
    el.classList.add('app-panel');
  });

  main.querySelectorAll('table').forEach(table => {
    table.classList.add('app-table');
    const parent = table.parentElement;
    if (parent && !parent.classList.contains('app-table-wrap')) parent.classList.add('app-table-wrap');
  });

  main.querySelectorAll('[id$="Grid"], [id$="List"], [id="tabContent"], [id="recResults"], [id="kbGrid"], [id="skillGrid"], [id="agentGrid"]').forEach(el => {
    el.classList.add('app-dynamic-region');
  });

  document.querySelectorAll('[id$="Modal"], .fixed.inset-0').forEach(el => {
    if (el.closest('[data-app-top-nav], [data-app-utility-rail]')) return;
    el.classList.add('app-modal-layer');
    const panel = el.querySelector('[class*="bg-surface-container"], .glass-panel');
    if (panel) panel.classList.add('app-modal-panel');
  });
}

function observeDynamicLayout(active) {
  if (window.__appLayoutObserver) window.__appLayoutObserver.disconnect();
  const main = document.querySelector('main');
  if (!main) return;
  window.__appLayoutObserver = new MutationObserver(() => {
    clearTimeout(window.__appLayoutTimer);
    window.__appLayoutTimer = setTimeout(() => enhancePageLayout(active), 80);
  });
  window.__appLayoutObserver.observe(main, { childList: true, subtree: true });
}

function closeAppFloatingPanel() {
  document.querySelectorAll('[data-app-floating-panel]').forEach(el => el.remove());
}

function renderAppFloatingPanel(title, icon, bodyHtml, footerHtml = '') {
  closeAppFloatingPanel();
  const panel = document.createElement('div');
  panel.className = 'app-floating-panel';
  panel.setAttribute('data-app-floating-panel', '');
  panel.innerHTML = `
    <div class="app-floating-panel-head">
      <div class="flex items-center gap-2">
        <span class="material-symbols-outlined text-primary">${icon}</span>
        <h3>${title}</h3>
      </div>
      <button onclick="closeAppFloatingPanel()" title="关闭"><span class="material-symbols-outlined">close</span></button>
    </div>
    <div class="app-floating-panel-body">${bodyHtml}</div>
    ${footerHtml ? `<div class="app-floating-panel-footer">${footerHtml}</div>` : ''}`;
  document.body.appendChild(panel);
  setTimeout(() => document.addEventListener('click', closeFloatingOnOutside, { once: true }), 0);
}

function closeFloatingOnOutside(event) {
  const panel = document.querySelector('[data-app-floating-panel]');
  if (!panel) return;
  if (panel.contains(event.target) || event.target.closest('[data-app-action]')) {
    document.addEventListener('click', closeFloatingOnOutside, { once: true });
    return;
  }
  closeAppFloatingPanel();
}

async function openNotificationPanel() {
  const loading = `
    <div class="app-empty-state">
      <span class="material-symbols-outlined animate-spin">progress_activity</span>
      <p>正在读取最近系统事件...</p>
    </div>`;
  renderAppFloatingPanel('通知中心', 'notifications', loading);

  try {
    const logs = Token.exists() ? await apiGet('/api/audit/logs?limit=8') : [];
    const items = logs.length ? logs.map(log => {
      const risk = log.risk_level || 'low';
      const icon = risk === 'high' ? 'error' : risk === 'medium' ? 'warning' : 'info';
      return `
        <a class="app-notice-item" href="/audit">
          <span class="material-symbols-outlined risk-${risk}">${icon}</span>
          <div>
            <div class="flex items-center gap-2">
              <strong>${escapeHtml(log.event_type || '系统事件')}</strong>
              <em class="risk-${risk}">${escapeHtml(risk)}</em>
            </div>
            <p>${escapeHtml(log.description || '')}</p>
            <small>${escapeHtml(log.operator || 'system')} · ${fmtTime(log.created_at)}</small>
          </div>
        </a>`;
    }).join('') : `
      <div class="app-empty-state">
        <span class="material-symbols-outlined">notifications_off</span>
        <p>当前没有新的系统通知</p>
      </div>`;

    renderAppFloatingPanel(
      '通知中心',
      'notifications',
      items,
      '<a href="/audit" class="app-panel-link">查看全部审计日志 <span class="material-symbols-outlined">arrow_forward</span></a>'
    );
  } catch (e) {
    renderAppFloatingPanel(
      '通知中心',
      'notifications',
      `<div class="app-empty-state">
        <span class="material-symbols-outlined text-error">cloud_off</span>
        <p>通知读取失败：${escapeHtml(e.message || '未知错误')}</p>
      </div>`,
      '<a href="/audit" class="app-panel-link">打开审计管理 <span class="material-symbols-outlined">arrow_forward</span></a>'
    );
  }
}

function openHelpPanel() {
  const modules = [
    ['数据治理', '/data-governance', 'database'],
    ['智能问数', '/query', 'terminal'],
    ['员工管理', '/agent-management', 'precision_manufacturing'],
    ['工作流', '/workflows', 'account_tree'],
    ['智能审计', '/smart-audit', 'gavel'],
    ['个人设置', '/settings', 'settings'],
  ].map(([name, href, icon]) => `
    <a class="app-help-link" href="${href}">
      <span class="material-symbols-outlined">${icon}</span>
      <span>${name}</span>
    </a>`).join('');

  renderAppFloatingPanel(
    '帮助与快捷入口',
    'help',
    `
      <div class="app-help-section">
        <h4>常用入口</h4>
        <div class="app-help-grid">${modules}</div>
      </div>
      <div class="app-help-section">
        <h4>操作说明</h4>
        <ul class="app-help-list">
          <li>顶部横向栏用于切换核心功能模块。</li>
          <li>左侧快捷控制保留搜索、通知、设置、帮助与账号操作。</li>
          <li>通知中心读取最近审计事件，高风险事件可跳转到审计管理查看。</li>
          <li>页面右上角按钮会自动收拢到页面标题区。</li>
        </ul>
      </div>
    `,
    '<a href="/settings" class="app-panel-link">打开个人设置 <span class="material-symbols-outlined">arrow_forward</span></a>'
  );
}

/* ========== 统一导航壳层注入 ========== */

/* 默认菜单定义（API 不可用时的降级） */
const DEFAULT_MENUS = [
  { name: '控制台', icon: 'space_dashboard', path: '/dashboard', key: 'dashboard' },
  { name: '数据治理', icon: 'database', path: '/data-governance', key: 'data-governance' },
  { name: '数字大屏', icon: 'monitoring', path: '/screen', key: 'screen' },
  { name: '智能对话', icon: 'forum', path: '/de', key: 'de' },
  { name: '智能问数', icon: 'terminal', path: '/query', key: 'query' },
  { name: '数字员工', icon: 'precision_manufacturing', path: '/employees', key: 'employees' },
  { name: '员工管理', icon: 'precision_manufacturing', path: '/agent-management', key: 'agent-management' },
  { name: '模型管理', icon: 'model_training', path: '/models', key: 'models' },
  { name: '技能管理', icon: 'extension', path: '/skills', key: 'skills' },
  { name: '员工编排', icon: 'smart_toy', path: '/agents', key: 'agents' },
  { name: '工作流', icon: 'account_tree', path: '/workflows', key: 'workflows' },
  { name: 'RAG 管理', icon: 'book_4', path: '/rag', key: 'rag' },
  { name: '权限管理', icon: 'admin_panel_settings', path: '/permissions', key: 'permissions' },
  { name: '审计管理', icon: 'security', path: '/audit', key: 'audit' },
  { name: '智能审计', icon: 'gavel', path: '/smart-audit', key: 'smart-audit' },
  { name: '聊天管理', icon: 'chat_bubble', path: '/chat-management', key: 'chat-management' },
  { name: '数据采集', icon: 'cloud_download', path: '/data-collection', key: 'data-collection' },
  { name: '消息中心', icon: 'chat', path: '/messages', key: 'messages' },
  { name: 'IM 控制台', icon: 'forum', path: '/im', key: 'im' },
  { name: '个人设置', icon: 'settings', path: '/settings', key: 'settings' },
];

/* 路径 → key 映射（用于 active 高亮） */
const PATH_TO_KEY = {};
DEFAULT_MENUS.forEach(m => { PATH_TO_KEY[m.path] = m.key; });
PATH_TO_KEY['/'] = '';
PATH_TO_KEY['/im/chat'] = 'im';
PATH_TO_KEY['/admin-login'] = '';
PATH_TO_KEY['/login'] = '';

/* 异步加载服务端菜单 */
async function fetchMenus() {
  if (!Token.exists()) return null;
  try {
    const data = await apiGet('/api/permissions/menus');
    if (Array.isArray(data)) {
      return data.map(m => ({
        name: m.path === '/settings' ? '个人设置' : m.name,
        icon: m.icon || 'circle',
        path: m.path,
        key: PATH_TO_KEY[m.path] || m.path.replace(/^\//, '') || 'dashboard',
      }));
    }
  } catch (e) {
    console.warn('[sidebar] API menus unavailable, using defaults');
  }
  return null;
}

function injectSidebar(active, menus) {
  if (!menus) menus = DEFAULT_MENUS;
  const nav = menus.map(l => {
    const base = [
      'group h-[46px] min-w-max',
      'inline-flex items-center gap-2.5 px-4',
      'rounded-xl border text-sm font-semibold leading-5',
      'transition-all duration-200'
    ].join(' ');
    const cls = l.key === active
      ? `${base} text-primary bg-secondary-container/10 border-primary/25 shadow-sm`
      : `${base} text-on-surface-variant border-transparent hover:bg-surface-container-high hover:text-primary hover:border-primary/10`;
    return `<a class="${cls}" href="${l.path}">
      <span class="material-symbols-outlined w-[21px] min-w-[21px] text-[21px] leading-[21px]">${l.icon}</span>
      <span class="block truncate text-[14px] leading-5 font-semibold">${l.name}</span>
    </a>`;
  }).join('');

  return `
  <header data-app-top-nav class="app-top-nav fixed left-0 top-0 right-0 h-[72px] border-b border-outline-variant bg-surface-container-low shadow-md z-50">
    <div class="h-full flex items-center gap-3 px-4">
      <div class="hidden md:flex items-center gap-3 shrink-0 w-[236px]">
        <div class="w-10 h-10 rounded-xl bg-primary-container/30 border border-primary/20 flex items-center justify-center shadow-lg">
          <span class="material-symbols-outlined text-primary text-[25px]">monitoring</span>
        </div>
        <div>
          <h1 class="text-[17px] leading-5 font-extrabold text-primary tracking-tight">数据瞭望系统</h1>
          <p class="text-[10px] text-on-surface-variant uppercase tracking-[0.18em]">Data Outlook</p>
        </div>
      </div>
      <nav class="app-top-nav-scroll min-w-0 flex-1 overflow-x-auto whitespace-nowrap flex items-center gap-2 py-2" tabindex="0" aria-label="功能导航">${nav}</nav>
    </div>
  </header>
  <aside data-app-utility-rail class="app-utility-rail fixed left-0 top-[72px] bottom-0 w-[252px] border-r border-outline-variant bg-surface-container-low shadow-md flex flex-col py-5 z-40">
    <div class="px-5 mb-5">
      <div class="flex items-center gap-3">
        <div class="w-11 h-11 rounded-xl bg-primary-container/30 border border-primary/20 flex items-center justify-center">
          <span class="material-symbols-outlined text-primary text-[25px]">tune</span>
        </div>
        <div>
          <h2 class="text-[16px] leading-5 font-extrabold text-primary">快捷控制</h2>
          <p class="text-[11px] text-on-surface-variant mt-0.5">常用操作与菜单检索</p>
        </div>
      </div>
      <div class="relative mt-5">
        <span class="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant text-[20px]">search</span>
        <input id="app-menu-search" oninput="filterTopNav(this.value)" onkeydown="if(event.key==='Enter')openFirstMatchedMenu()" class="w-full bg-surface-container-high border border-outline-variant rounded-xl pl-10 pr-3 py-2.5 text-sm outline-none focus:border-primary" placeholder="搜索功能菜单..." type="search" aria-label="搜索功能菜单"/>
      </div>
      <p id="app-menu-search-status" class="mt-2 min-h-4 text-[10px] text-on-surface-variant" aria-live="polite">输入名称可定位顶部菜单</p>
      <div class="grid grid-cols-3 gap-2 mt-4">
        <button onclick="openNotificationPanel()" data-app-action="notifications" class="h-11 rounded-xl border border-outline-variant bg-surface-container-high text-on-surface-variant hover:text-primary" title="通知">
          <span class="material-symbols-outlined text-[21px]">notifications</span>
        </button>
        <button onclick="window.location.href='/settings'" class="h-11 rounded-xl border border-outline-variant bg-surface-container-high text-on-surface-variant hover:text-primary" title="设置">
          <span class="material-symbols-outlined text-[21px]">settings</span>
        </button>
        <button onclick="openHelpPanel()" data-app-action="help" class="h-11 rounded-xl border border-outline-variant bg-surface-container-high text-on-surface-variant hover:text-primary" title="帮助">
          <span class="material-symbols-outlined text-[21px]">help</span>
        </button>
      </div>
      <div class="mt-4 rounded-xl border border-outline-variant bg-surface-container-high px-4 py-3">
        <div class="flex items-center justify-between">
          <span class="text-[11px] text-on-surface-variant">运行状态</span>
          <span class="inline-flex items-center gap-1 text-[11px] text-primary font-semibold">
            <i class="w-1.5 h-1.5 rounded-full bg-secondary inline-block"></i>ONLINE
          </span>
        </div>
        <div class="mt-3 flex items-center justify-between">
          <span class="text-[11px] text-on-surface-variant">版本</span>
          <span class="font-label-mono text-[11px] text-primary bg-secondary-container/20 px-2 py-1 rounded">V2.4.8</span>
        </div>
      </div>
    </div>
    <div class="mx-5 mt-auto pt-5 border-t border-outline-variant flex items-center gap-3" data-injected>
      <div class="w-10 h-10 rounded-full bg-primary-container/30 border border-primary/30 flex items-center justify-center">
        <span class="material-symbols-outlined text-primary">person</span>
      </div>
      <div id="sidebar-user">
        <p class="text-sm font-bold">加载中...</p>
        <p class="text-[10px] text-on-surface-variant">--</p>
      </div>
      <button onclick="logout()" class="ml-auto text-on-surface-variant hover:text-error transition-colors" title="退出登录">
        <span class="material-symbols-outlined text-xl">logout</span>
      </button>
    </div>
  </aside>`;
}

const TOP_NAV_SCROLL_STORAGE_KEY = 'data-outlook-top-nav-scroll-left';

function setupTopNavScrolling(header) {
  const nav = header?.querySelector('.app-top-nav-scroll');
  if (!nav) return;

  const previousInlineBehavior = nav.style.scrollBehavior;
  nav.style.scrollBehavior = 'auto';
  try {
    const savedLeft = Number(sessionStorage.getItem(TOP_NAV_SCROLL_STORAGE_KEY));
    if (Number.isFinite(savedLeft) && savedLeft >= 0) nav.scrollLeft = savedLeft;
  } catch (error) {}

  const activeLink = nav.querySelector('a[class*="bg-secondary-container"]');
  if (activeLink) {
    const navRect = nav.getBoundingClientRect();
    const activeRect = activeLink.getBoundingClientRect();
    if (activeRect.left < navRect.left + 8 || activeRect.right > navRect.right - 8) {
      nav.scrollLeft += activeRect.left + activeRect.width / 2 - (navRect.left + navRect.width / 2);
    }
  }
  nav.getBoundingClientRect();
  requestAnimationFrame(() => { nav.style.scrollBehavior = previousInlineBehavior; });

  let saveScheduled = false;
  const saveScrollPosition = () => {
    if (saveScheduled) return;
    saveScheduled = true;
    requestAnimationFrame(() => {
      saveScheduled = false;
      try { sessionStorage.setItem(TOP_NAV_SCROLL_STORAGE_KEY, String(nav.scrollLeft)); } catch (error) {}
    });
  };

  nav.addEventListener('wheel', event => {
    if (nav.scrollWidth <= nav.clientWidth || Math.abs(event.deltaX) >= Math.abs(event.deltaY)) return;
    event.preventDefault();
    nav.scrollLeft += event.deltaY;
  }, { passive: false });
  nav.addEventListener('scroll', saveScrollPosition, { passive: true });
  nav.addEventListener('click', event => {
    if (!event.target.closest('a')) return;
    try { sessionStorage.setItem(TOP_NAV_SCROLL_STORAGE_KEY, String(nav.scrollLeft)); } catch (error) {}
  });
}

function filterTopNav(value) {
  const nav = document.querySelector('.app-top-nav-scroll');
  if (!nav) return;
  const query = value.trim().toLocaleLowerCase('zh-CN');
  const links = [...nav.querySelectorAll('a')];
  const matches = [];
  links.forEach(link => {
    const matched = !query || link.textContent.trim().toLocaleLowerCase('zh-CN').includes(query);
    link.classList.toggle('app-menu-filtered-out', !matched);
    if (matched) matches.push(link);
  });
  window.__firstMatchedMenu = query && matches.length ? matches[0] : null;
  const status = document.getElementById('app-menu-search-status');
  if (status) status.textContent = query ? `找到 ${matches.length} 个功能菜单${matches.length ? '，按 Enter 打开第一个' : ''}` : '输入名称可定位顶部菜单';
  if (window.__firstMatchedMenu) {
    window.__firstMatchedMenu.scrollIntoView({ block: 'nearest', inline: 'center' });
  }
}

function openFirstMatchedMenu() {
  if (window.__firstMatchedMenu) window.location.href = window.__firstMatchedMenu.href;
}

/* 统一替换所有页面的侧边栏，保证一致性 */
async function replaceSidebar() {
  const path = window.location.pathname;
  if (path === '/' || path === '/login' || path === '/admin-login') {
    return false;
  }
  const activeMap = {
    '/dashboard': 'dashboard',
    '/data-governance': 'data-governance',
    '/screen': 'screen',
    '/models': 'models',
    '/skills': 'skills',
    '/agent-management': 'agent-management',
    '/agents': 'agents',
    '/de': 'de',
    '/workflows': 'workflows',
    '/rag': 'rag',
    '/permissions': 'permissions',
    '/audit': 'audit',
    '/smart-audit': 'smart-audit',
    '/chat-management': 'chat-management',
    '/admin-login': '',
    '/data-collection': 'data-collection',
    '/messages': 'messages',
    '/im': 'im',
    '/im/chat': 'im',
    '/query': 'query',
    '/settings': 'settings',
  };
  const active = activeMap[path] || '';

  // 异步加载服务端菜单（按角色过滤）
  const menus = await fetchMenus();

  document.querySelectorAll('[data-app-top-nav], [data-app-utility-rail]').forEach(el => el.remove());
  document.querySelectorAll('body > header, nav.fixed.top-0').forEach(el => el.remove());

  const oldAside = document.querySelector('aside');

  // 生成统一壳层：顶部功能导航 + 左侧工具栏
  const temp = document.createElement('div');
  temp.innerHTML = injectSidebar(active, menus);
  const newTopNav = temp.querySelector('[data-app-top-nav]');
  const newAside = temp.querySelector('[data-app-utility-rail]');

  if (oldAside) {
    oldAside.replaceWith(newAside);
  } else {
    const main = document.querySelector('main');
    if (main && main.parentNode) {
      main.parentNode.insertBefore(newAside, main);
    } else {
      document.body.prepend(newAside);
    }
  }
  document.body.prepend(newTopNav);
  setupTopNavScrolling(newTopNav);

  // 统一主内容区：顶部留给功能导航，左侧留给工具栏
  const main = document.querySelector('main');
  if (main) {
    main.style.marginLeft = '252px';
    main.style.paddingTop = '96px';
    main.classList.add('app-main-shell');
  }

  // 数字大屏特殊处理：保持全屏可视高度
  if (path === '/screen') {
    if (main) {
      main.style.paddingTop = '88px';
    }
  }

  enhancePageLayout(active);
  observeDynamicLayout(active);

  return true;
}

/* 加载用户信息到侧边栏 */
async function loadSidebarUser() {
  if (!Token.exists()) return;
  try {
    const user = await apiGet('/api/auth/profile');
    // 更新 injectSidebar 生成的 #sidebar-user
    const el = document.getElementById('sidebar-user');
    if (el) {
      el.innerHTML = `
        <p class="text-sm font-bold">${escapeHtml(user.nickname || user.username)}</p>
        <p class="text-[10px] text-on-surface-variant">${escapeHtml(user.role || '用户')}</p>`;
    }
    // 更新硬编码侧边栏中的用户信息（查找底部用户区域）
    const aside = document.querySelector('aside');
    if (aside) {
      // 查找侧边栏底部包含头像的区域，替换硬编码的用户名
      const userAreas = aside.querySelectorAll('.flex.items-center.space-x-3, .flex.items-center.gap-3');
      userAreas.forEach(area => {
        const nameEl = area.querySelector('p.text-sm.font-bold');
        const roleEl = area.querySelector('p.text-\\[10px\\]');
        if (nameEl) nameEl.textContent = user.nickname || user.username;
        if (roleEl) roleEl.textContent = user.role || '用户';
      });
    }
  } catch { /* 静默 */ }
  // 注入退出按钮和设置链接
  injectSidebarExtras();
}

/* 加载系统名称到侧边栏标题（与 settings 表 system_name 联动） */
async function loadSystemName() {
  if (!Token.exists()) return;
  try {
    const settings = await apiGet('/api/settings');
    const sysName = (settings || []).find(s => s.key === 'system_name');
    if (sysName && sysName.value) {
      document.querySelectorAll('.app-top-nav h1, .app-utility-rail h1').forEach(el => {
        el.textContent = sysName.value;
      });
    }
  } catch(e) { /* silent */ }
}

/* 给所有页面侧边栏注入退出按钮和设置链接（仅对未被replaceSidebar替换的旧侧边栏生效） */
function injectSidebarExtras() {
  const aside = document.querySelector('aside');
  if (!aside) return;

  // 避免重复注入（data-injected 来自 injectSidebar 或之前注入的按钮）
  if (aside.querySelector('[data-injected]')) return;
  // 也检查是否已有退出按钮
  if (aside.querySelector('[onclick*="logout"]')) return;

  // 0. 先修复所有侧边栏导航链接（支持中英文标签）
  fixSidebarNav(aside);

  // 1. 在导航区域末尾添加"个人设置"链接
  const nav = aside.querySelector('nav');
  if (nav && !nav.querySelector('[href="/settings"]') && !nav.querySelector('[data-nav-key="settings"]')) {
    const settingsLink = document.createElement('a');
    settingsLink.className = 'flex items-center px-md py-sm rounded-lg text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface transition-all';
    settingsLink.href = '/settings';
    settingsLink.innerHTML = '<span class="material-symbols-outlined mr-3">settings</span><span class="font-body-md text-body-md">个人设置</span>';
    nav.appendChild(settingsLink);
  }

  // 2. 在侧边栏底部添加退出登录按钮
  const logoutBtn = document.createElement('div');
  logoutBtn.className = 'px-lg border-t border-outline-variant pt-md pb-md flex items-center gap-3 cursor-pointer hover:bg-error/10 transition-colors';
  logoutBtn.setAttribute('data-injected', '');
  logoutBtn.setAttribute('onclick', 'logout()');
  logoutBtn.innerHTML = '<span class="material-symbols-outlined text-on-surface-variant hover:text-error">logout</span><span class="text-sm text-on-surface-variant hover:text-error">退出登录</span>';
  aside.appendChild(logoutBtn);
}

/* 通用侧边栏导航修复：匹配中英文标签，设置正确的href或onclick */
function fixSidebarNav(aside) {
  // 中文 → 路由
  const cnMap = {
    '数据治理': '/data-governance', '数字大屏': '/screen', '模型管理': '/models',
    '技能管理': '/skills', '员工管理': '/agent-management', '员工编排': '/agents',
    '数字员工': '/de', '权限管理': '/permissions', '审计管理': '/audit',
    '消息中心': '/messages', 'IM控制台': '/im', '智能问数': '/query',
    '个人设置': '/settings',
  };
  // 英文 → 路由
  const enMap = {
    'messages': '/messages', 'agents': '/agents', 'analyze': '/query',
    'data': '/data-governance', 'settings': '/settings', 'account': '/settings',
    'console': '/im',
  };

  function matchHref(text) {
    const t = text.trim();
    // 中文匹配
    for (const [key, href] of Object.entries(cnMap)) {
      if (t.includes(key)) return href;
    }
    // 英文匹配（用 includes，因为 textContent 包含图标名）
    const lower = t.toLowerCase();
    for (const [key, href] of Object.entries(enMap)) {
      if (lower.includes(key)) return href;
    }
    return null;
  }

  // 遍历 nav 的所有直接子元素（<a> 和 <div>）
  const nav = aside.querySelector('nav');
  if (!nav) return;
  Array.from(nav.children).forEach(el => {
    // 只处理 <a> 和 <div>，跳过其他元素
    if (el.tagName !== 'A' && el.tagName !== 'DIV') return;
    // 跳过没有图标子元素的（纯分隔线等）
    if (!el.querySelector('.material-symbols-outlined')) return;
    const text = el.textContent.trim();
    if (!text) return;
    const href = matchHref(text);
    if (!href) return;

    if (el.tagName === 'A') {
      el.setAttribute('href', href);
    } else {
      // div 元素：设置 onclick
      el.setAttribute('onclick', `window.location.href='${href}'`);
      el.style.cursor = 'pointer';
    }
  });

  // 也处理底部 footer 区域的链接（如 Account, Support）
  const footer = aside.querySelector('div.border-t');
  if (footer) {
    Array.from(footer.children).forEach(el => {
      if (el.tagName !== 'A' && el.tagName !== 'DIV') return;
      if (!el.querySelector('.material-symbols-outlined')) return;
      const text = el.textContent.trim();
      if (!text) return;
      const href = matchHref(text);
      if (!href) return;
      if (el.tagName === 'A') {
        el.setAttribute('href', href);
      } else {
        el.setAttribute('onclick', `window.location.href='${href}'`);
        el.style.cursor = 'pointer';
      }
    });
  }
}

/* 退出登录 */
function logout() {
  fetch('/api/auth/logout', { method: 'POST', keepalive: true }).catch(() => {});
  Token.clear();
  window.location.href = '/login';
}

/* ========== 通知 Toast ========== */
function showToast(msg, type = 'info') {
  const colors = { info: 'bg-primary-container', success: 'bg-secondary-container', error: 'bg-error-container' };
  const toast = document.createElement('div');
  toast.className = `fixed top-4 right-4 z-[9999] ${colors[type]} text-on-surface px-lg py-md rounded-xl shadow-2xl transition-all duration-300 opacity-0 translate-y-[-10px]`;
  toast.textContent = msg;
  document.body.appendChild(toast);
  requestAnimationFrame(() => {
    toast.classList.remove('opacity-0', 'translate-y-[-10px]');
  });
  setTimeout(() => {
    toast.classList.add('opacity-0', 'translate-y-[-10px]');
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

/* ========== 自动统一侧边栏 + 加载用户信息 ========== */
async function initSidebar() {
  // 尝试用统一侧边栏替换页面原有侧边栏
  const replaced = await replaceSidebar();
  if (replaced) {
    // 替换成功，加载用户信息到新侧边栏
    loadSidebarUser();
    loadSystemName();
  } else {
    // 替换失败（无 aside 或其他原因），回退到旧的注入方式
    injectSidebarExtras();
    loadSidebarUser();
    loadSystemName();
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initSidebar);
} else {
  initSidebar();
}

/* ========== WebSocket 即时通信客户端 ========== */
const IM = {
  ws: null,
  connected: false,
  reconnectAttempts: 0,
  maxReconnect: 3,
  pendingMessages: [],  // 待重发的消息
  handlers: {},
  _stopped: false,  // 手动停止标志，为 true 时不再重连

  async connect() {
    if (!Token.exists()) return;
    if (this.ws && this.ws.readyState === WebSocket.OPEN) return;

    // 重连时尝试刷新 token（失败不阻塞）
    if (this.reconnectAttempts > 0) {
      try { await tryRefresh(); } catch(e) { /* 静默失败 */ }
    }

    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${proto}//${location.host}/ws/chat`;

    try {
      this.ws = new WebSocket(url);
    } catch (e) {
      console.error('[IM] WebSocket连接失败:', e);
      this._scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this.ws.send(JSON.stringify({
        msg_id: this._genMsgId(),
        msg_type: 'auth',
        timestamp: new Date().toISOString(),
        body: { token: Token.access }
      }));
      this.connected = true;
      this.reconnectAttempts = 0;
      console.log('[IM] WebSocket已连接');
      this._emit('connected', {});
      // 重发pending消息
      this.pendingMessages.forEach(p => this._rawSend(p));
      this.pendingMessages = [];
    };

    this.ws.onmessage = (event) => {
      try {
        const packet = JSON.parse(event.data);
        this._emit(packet.msg_type, packet.body || {}, packet);
      } catch (e) {
        console.error('[IM] 消息解析失败:', e);
      }
    };

    this.ws.onclose = (event) => {
      this.connected = false;
      console.log('[IM] WebSocket断开, code:', event.code);
      if (event.code === 4001) return; // 认证失败，不重连
      this._emit('disconnected', {});
      this._scheduleReconnect();
    };

    this.ws.onerror = (error) => {
      if (!this._stopped && this.ws?.readyState !== WebSocket.CLOSING) {
        console.warn('[IM] WebSocket连接异常，将按重连策略处理');
      }
    };
  },

  disconnect() {
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.close();
      this.ws = null;
      this.connected = false;
    }
  },

  send(msgType, body) {
    const packet = {
      msg_id: this._genMsgId(),
      msg_type: msgType,
      timestamp: new Date().toISOString(),
      body: body,
    };
    if (this.connected) {
      this._rawSend(packet);
    } else {
      this.pendingMessages.push(packet);
    }
    return packet.msg_id;
  },

  sendChat(body) {
    return this.send('chat', body);
  },

  recall(dbId) {
    return this.send('recall', { db_id: dbId });
  },

  sendTyping(receiverId, groupId) {
    this.send('typing', { receiver_id: receiverId, group_id: groupId });
  },

  sendReadReceipt(senderId) {
    this.send('read_receipt', { sender_id: senderId });
  },

  on(msgType, callback) {
    if (!this.handlers[msgType]) this.handlers[msgType] = [];
    this.handlers[msgType].push(callback);
  },

  off(msgType, callback) {
    if (!this.handlers[msgType]) return;
    this.handlers[msgType] = this.handlers[msgType].filter(h => h !== callback);
  },

  _emit(msgType, data, raw) {
    (this.handlers[msgType] || []).forEach(h => {
      try { h(data, raw); } catch (e) { console.error('[IM] handler error:', e); }
    });
  },

  _rawSend(packet) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(packet));
    }
  },

  _genMsgId() {
    return 'msg_' + Date.now() + '_' + Math.random().toString(36).slice(2, 10);
  },

  _scheduleReconnect() {
    if (this._stopped) return;
    if (this.reconnectAttempts >= this.maxReconnect) {
      console.log('[IM] 达到最大重连次数(' + this.maxReconnect + ')，停止重连。刷新页面可重新连接。');
      this._emit('reconnect_failed', {});
      return;
    }
    this.reconnectAttempts++;
    const delay = Math.min(3000 * Math.pow(1.5, this.reconnectAttempts - 1), 15000);
    console.log('[IM] ' + Math.round(delay/1000) + 's后重连 (' + this.reconnectAttempts + '/' + this.maxReconnect + ')');
    setTimeout(() => this.connect(), delay);
  },

  /** 手动停止重连（页面卸载时调用） */
  stop() {
    this._stopped = true;
    if (this.ws) { try { this.ws.close(); } catch(e) {} }
  }
};

// 强制下线处理
IM.on('force_logout', (data) => {
  fetch('/api/auth/logout', { method: 'POST', keepalive: true }).catch(() => {});
  Token.clear();
  alert(data.reason || '账号在其他设备登录，您已被强制下线');
  window.location.href = '/login';
});

IM.on('ack', (data) => {
  if (data.status === 'blocked') {
    showToast(data.error || '消息包含敏感信息，已被拦截', 'error');
  }
});

// 自动连接（如果已登录且不在登录页）
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    if (Token.exists() && !location.pathname.startsWith('/login')) IM.connect();
  });
} else {
  if (Token.exists() && !location.pathname.startsWith('/login')) IM.connect();
}

// 页面卸载时停止 WebSocket 重连
window.addEventListener('beforeunload', () => { IM.stop(); });

/* ========== 自动侧边栏注入（统一所有页面） ========== */
async function autoInitSidebar() {
  if (!Token.exists() || window.location.pathname.startsWith('/login')) return;
  // 登录页不需要侧边栏
  if (window.location.pathname === '/login' || window.location.pathname === '/') return;
  await replaceSidebar();
  loadSidebarUser();
  loadSystemName();
}
// DOM 就绪后自动注入
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', autoInitSidebar);
} else {
  autoInitSidebar();
}
