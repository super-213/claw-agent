const SVG_NS = 'http://www.w3.org/2000/svg';

const state = {
  range: 'all',
  scope: 'all',
  summary: null,
  sessions: [],
};

const colors = ['#007aff', '#34c759', '#ff9500', '#ff3b30', '#af52de', '#30b0c7', '#5856d6'];
const categoryLabels = {
  shell_read: '读取',
  shell_write: '写入',
  test: '测试',
  server: '服务',
  network: '网络',
  git: 'Git',
  blocked: '拦截',
  unknown: '未知',
};
const weekdays = ['一', '二', '三', '四', '五', '六', '日'];

const els = {
  refresh: document.getElementById('refreshDashboardBtn'),
  freshness: document.getElementById('dashboardFreshness'),
  subtitle: document.getElementById('dashboardSubtitle'),
  totalTokens: document.getElementById('kpiTotalTokens'),
  sessions: document.getElementById('kpiSessions'),
  toolCalls: document.getElementById('kpiToolCalls'),
  toolRate: document.getElementById('kpiToolRate'),
  avgTokens: document.getElementById('kpiAvgTokens'),
  messages: document.getElementById('kpiMessages'),
  toolFailures: document.getElementById('kpiToolFailures'),
  avgOutput: document.getElementById('kpiAvgOutput'),
  trendTotal: document.getElementById('trendTotal'),
  tokenTrend: document.getElementById('tokenTrendChart'),
  tokenDonut: document.getElementById('tokenDonutChart'),
  tokenLegend: document.getElementById('tokenLegend'),
  sessionTokenBars: document.getElementById('sessionTokenBars'),
  roleTokenBars: document.getElementById('roleTokenBars'),
  toolCategoryBars: document.getElementById('toolCategoryBars'),
  topCommandBars: document.getElementById('topCommandBars'),
  recentToolCalls: document.getElementById('recentToolCalls'),
  alerts: document.getElementById('dashboardAlerts'),
  wordCloud: document.getElementById('wordCloud'),
  heatmap: document.getElementById('activityHeatmap'),
  sessionTable: document.getElementById('sessionTableBody'),
  search: document.getElementById('sessionSearchInput'),
  drawer: document.getElementById('sessionDetailDrawer'),
  drawerBackdrop: document.getElementById('drawerBackdrop'),
  drawerTitle: document.getElementById('drawerTitle'),
  drawerBody: document.getElementById('drawerBody'),
  closeDrawer: document.getElementById('closeDrawerBtn'),
};

const fetchJson = async (url) => {
  const response = await fetch(url, { headers: { Accept: 'application/json' } });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) {
      window.location.href = '/login';
      return {};
    }
    throw new Error(data.message || data.error || '请求失败');
  }
  return data;
};

const escapeHtml = (value) => String(value ?? '')
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#039;');

const formatNumber = (value) => {
  const number = Number(value || 0);
  if (number >= 100000000) return (number / 100000000).toFixed(1) + '亿';
  if (number >= 1000000) return (number / 1000000).toFixed(1) + 'M';
  if (number >= 10000) return (number / 10000).toFixed(1) + '万';
  return new Intl.NumberFormat('zh-CN').format(Math.round(number));
};

const formatTime = (value) => {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '-';
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
};

const animateValue = (el, nextValue, formatter = formatNumber) => {
  const start = Number(el.dataset.value || 0);
  const end = Number(nextValue || 0);
  const startedAt = performance.now();
  const duration = 680;
  el.dataset.value = String(end);

  const step = (now) => {
    const progress = Math.min(1, (now - startedAt) / duration);
    const eased = 1 - Math.pow(1 - progress, 3);
    const value = start + (end - start) * eased;
    el.textContent = formatter(value);
    if (progress < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
};

const clear = (node) => {
  node.textContent = '';
};

const svgEl = (name, attrs = {}) => {
  const node = document.createElementNS(SVG_NS, name);
  Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
  return node;
};

const empty = (container, text = '暂无数据') => {
  container.innerHTML = `<div class="empty-note">${escapeHtml(text)}</div>`;
};

const renderKpis = (summary) => {
  const kpis = summary.kpis || {};
  const toolSummary = summary.tool_summary || {};
  animateValue(els.totalTokens, kpis.total_tokens || 0);
  animateValue(els.sessions, kpis.total_sessions || 0);
  animateValue(els.toolCalls, kpis.tool_calls || 0);
  animateValue(els.toolRate, kpis.tool_success_rate || 0, (value) => `${value.toFixed(1)}%`);
  els.avgTokens.textContent = `平均 ${formatNumber(kpis.avg_tokens_per_session || 0)} / 会话`;
  els.messages.textContent = `${formatNumber(kpis.total_messages || 0)} 条消息`;
  els.toolFailures.textContent = `${formatNumber(kpis.tool_failures || 0)} 次失败`;
  els.avgOutput.textContent = `平均输出 ${formatNumber(toolSummary.avg_output_chars || 0)} 字符`;
};

const renderLineChart = (svg, rows) => {
  clear(svg);
  const width = 720;
  const height = 260;
  const pad = { left: 48, right: 18, top: 20, bottom: 34 };
  const points = (rows || []).map((item) => ({
    label: item.date,
    value: Number(item.tokens || 0),
  }));
  const total = points.reduce((sum, item) => sum + item.value, 0);
  els.trendTotal.textContent = `${formatNumber(total)} tokens`;

  if (!points.length) {
    svg.appendChild(svgEl('text', { x: width / 2, y: height / 2, class: 'chart-label', 'text-anchor': 'middle' }));
    svg.lastChild.textContent = '暂无趋势数据';
    return;
  }

  const max = Math.max(...points.map((item) => item.value), 1);
  const innerWidth = width - pad.left - pad.right;
  const innerHeight = height - pad.top - pad.bottom;
  const xFor = (index) => pad.left + (points.length === 1 ? innerWidth / 2 : innerWidth * index / (points.length - 1));
  const yFor = (value) => pad.top + innerHeight - (value / max) * innerHeight;

  for (let i = 0; i <= 4; i++) {
    const y = pad.top + innerHeight * i / 4;
    svg.appendChild(svgEl('line', { x1: pad.left, x2: width - pad.right, y1: y, y2: y, class: 'grid-line' }));
    const label = svgEl('text', { x: 8, y: y + 4, class: 'chart-label' });
    label.textContent = formatNumber(max * (1 - i / 4));
    svg.appendChild(label);
  }

  const linePoints = points.map((item, index) => `${xFor(index)},${yFor(item.value)}`);
  const areaD = [
    `M ${xFor(0)} ${pad.top + innerHeight}`,
    `L ${linePoints.join(' L ')}`,
    `L ${xFor(points.length - 1)} ${pad.top + innerHeight}`,
    'Z',
  ].join(' ');
  svg.appendChild(svgEl('path', { d: areaD, class: 'area-path' }));

  const path = svgEl('path', { d: `M ${linePoints.join(' L ')}`, class: 'line-path' });
  svg.appendChild(path);
  const length = path.getTotalLength();
  path.style.strokeDasharray = String(length);
  path.style.strokeDashoffset = String(length);
  requestAnimationFrame(() => {
    path.style.transition = 'stroke-dashoffset 900ms cubic-bezier(.2,.8,.2,1)';
    path.style.strokeDashoffset = '0';
  });

  points.forEach((item, index) => {
    const dot = svgEl('circle', {
      cx: xFor(index),
      cy: yFor(item.value),
      r: 4,
      class: 'chart-dot',
    });
    const title = svgEl('title');
    title.textContent = `${item.label}: ${formatNumber(item.value)} tokens`;
    dot.appendChild(title);
    svg.appendChild(dot);
  });

  const first = svgEl('text', { x: pad.left, y: height - 8, class: 'chart-label' });
  first.textContent = points[0].label.slice(5);
  svg.appendChild(first);
  const last = svgEl('text', { x: width - pad.right, y: height - 8, class: 'chart-label', 'text-anchor': 'end' });
  last.textContent = points[points.length - 1].label.slice(5);
  svg.appendChild(last);
};

const renderDonut = (svg, legend, rows) => {
  clear(svg);
  clear(legend);
  const data = (rows || []).filter((item) => Number(item.tokens || 0) > 0);
  const total = data.reduce((sum, item) => sum + Number(item.tokens || 0), 0);
  svg.appendChild(svgEl('circle', { cx: 110, cy: 110, r: 78, class: 'donut-bg' }));
  if (!data.length || !total) {
    const title = svgEl('text', { x: 110, y: 106, class: 'donut-center-title' });
    title.textContent = 'Token';
    svg.appendChild(title);
    const value = svgEl('text', { x: 110, y: 132, class: 'donut-center-value' });
    value.textContent = '0';
    svg.appendChild(value);
    empty(legend);
    return;
  }

  const circumference = 2 * Math.PI * 78;
  let offset = 0;
  data.forEach((item, index) => {
    const ratio = Number(item.tokens || 0) / total;
    const segment = svgEl('circle', {
      cx: 110,
      cy: 110,
      r: 78,
      class: 'donut-segment',
      stroke: colors[index % colors.length],
      'stroke-dasharray': `${Math.max(1, ratio * circumference)} ${circumference}`,
      'stroke-dashoffset': -offset,
    });
    offset += ratio * circumference;
    svg.appendChild(segment);

    const row = document.createElement('div');
    row.className = 'legend-item';
    row.innerHTML = `
      <span class="legend-dot" style="background:${colors[index % colors.length]}"></span>
      <span>${escapeHtml(item.label)}</span>
      <strong>${formatNumber(item.tokens)}</strong>
    `;
    legend.appendChild(row);
  });

  const title = svgEl('text', { x: 110, y: 106, class: 'donut-center-title' });
  title.textContent = 'Token';
  svg.appendChild(title);
  const value = svgEl('text', { x: 110, y: 132, class: 'donut-center-value' });
  value.textContent = formatNumber(total);
  svg.appendChild(value);
};

const renderBars = (container, rows, options = {}) => {
  const {
    label = (item) => item.label,
    value = (item) => item.value,
    color = (_, index) => colors[index % colors.length],
    limit = 10,
    suffix = '',
    emptyText = '暂无数据',
  } = options;
  clear(container);
  const data = (rows || []).slice(0, limit);
  const max = Math.max(...data.map((item) => Number(value(item) || 0)), 0);
  if (!data.length || !max) {
    empty(container, emptyText);
    return;
  }

  data.forEach((item, index) => {
    const row = document.createElement('div');
    row.className = 'bar-row';
    const amount = Number(value(item) || 0);
    row.innerHTML = `
      <div class="bar-row-head">
        <span class="bar-label" title="${escapeHtml(label(item))}">${escapeHtml(label(item))}</span>
        <strong>${formatNumber(amount)}${suffix}</strong>
      </div>
      <div class="bar-track"><div class="bar-fill" style="background:${color(item, index)}"></div></div>
    `;
    container.appendChild(row);
    requestAnimationFrame(() => {
      row.querySelector('.bar-fill').style.width = `${Math.max(3, amount / max * 100)}%`;
    });
  });
};

const renderCategoryBars = (container, rows) => {
  clear(container);
  const data = rows || [];
  const max = Math.max(...data.map((item) => Number(item.count || 0)), 0);
  if (!data.length || !max) {
    empty(container, '暂无工具调用');
    return;
  }
  data.forEach((item, index) => {
    const row = document.createElement('div');
    row.className = 'category-row';
    const label = categoryLabels[item.category] || item.category;
    row.innerHTML = `
      <span>${escapeHtml(label)}</span>
      <div class="category-meter"><span style="background:${colors[index % colors.length]}"></span></div>
      <strong>${formatNumber(item.count)}</strong>
    `;
    container.appendChild(row);
    requestAnimationFrame(() => {
      row.querySelector('.category-meter span').style.width = `${Math.max(3, Number(item.count || 0) / max * 100)}%`;
    });
  });
};

const renderToolFeed = (container, rows) => {
  clear(container);
  const data = rows || [];
  if (!data.length) {
    empty(container, '暂无工具调用');
    return;
  }
  data.forEach((item) => {
    const statusClass = item.success === false ? 'failed' : item.success === null ? 'unknown' : '';
    const statusText = item.success === false ? '失败' : item.success === null ? '未知' : '成功';
    const row = document.createElement('div');
    row.className = 'tool-item';
    row.innerHTML = `
      <span class="tool-status ${statusClass}"></span>
      <div class="tool-main">
        <div class="tool-command" title="${escapeHtml(item.command || '')}">${escapeHtml(item.command_preview || item.command || '-')}</div>
        <div class="tool-session">${escapeHtml(item.session_title || '新对话')}</div>
      </div>
      <div class="tool-meta">${escapeHtml(statusText)} · ${escapeHtml(categoryLabels[item.category] || item.category || '未知')}</div>
    `;
    container.appendChild(row);
  });
};

const renderAlerts = (container, rows) => {
  clear(container);
  if (!rows?.length) {
    empty(container, '暂无异常');
    return;
  }
  rows.forEach((item) => {
    const row = document.createElement('div');
    row.className = `alert-item ${item.level || ''}`;
    row.innerHTML = `
      <div class="alert-title">${escapeHtml(item.title || '提示')}</div>
      <div class="alert-message">${escapeHtml(item.message || '')}</div>
    `;
    container.appendChild(row);
  });
};

const renderWordCloud = (container, words) => {
  clear(container);
  const data = (words || []).slice(0, 72);
  if (!data.length) {
    empty(container, '暂无词云数据');
    return;
  }
  const palette = ['#007aff', '#34c759', '#ff9500', '#af52de', '#30b0c7', '#ff3b30'];
  data.forEach((item, index) => {
    const span = document.createElement('span');
    const angle = index * 2.399963;
    const radius = Math.sqrt(index / Math.max(1, data.length)) * 45;
    const x = 50 + Math.cos(angle) * radius;
    const y = 50 + Math.sin(angle) * radius * 0.72;
    span.textContent = item.word;
    span.title = `${item.word}: ${item.count}`;
    span.style.left = `${Math.max(8, Math.min(92, x))}%`;
    span.style.top = `${Math.max(12, Math.min(88, y))}%`;
    span.style.fontSize = `${Math.max(13, Math.min(48, item.weight || 20))}px`;
    span.style.color = palette[index % palette.length];
    span.style.animationDelay = `${Math.min(420, index * 18)}ms`;
    container.appendChild(span);
  });
};

const renderHeatmap = (container, rows) => {
  clear(container);
  const map = new Map((rows || []).map((item) => [`${item.weekday}:${item.hour}`, Number(item.count || 0)]));
  const max = Math.max(...map.values(), 1);
  for (let weekday = 0; weekday < 7; weekday += 1) {
    for (let hour = 0; hour < 24; hour += 1) {
      const value = map.get(`${weekday}:${hour}`) || 0;
      const cell = document.createElement('div');
      cell.className = 'heat-cell';
      cell.style.setProperty('--heat', `${Math.round(value / max * 78)}%`);
      cell.title = `周${weekdays[weekday]} ${String(hour).padStart(2, '0')}:00 · ${value} 条`;
      container.appendChild(cell);
    }
  }
};

const healthClass = (score) => {
  if (score < 60) return 'danger';
  if (score < 82) return 'warn';
  return '';
};

const renderSessionTable = () => {
  clear(els.sessionTable);
  const query = els.search.value.trim().toLowerCase();
  const rows = state.sessions.filter((item) => {
    if (!query) return true;
    return `${item.title} ${item.id}`.toLowerCase().includes(query);
  });
  if (!rows.length) {
    const tr = document.createElement('tr');
    tr.innerHTML = '<td colspan="7"><div class="empty-note">暂无会话</div></td>';
    els.sessionTable.appendChild(tr);
    return;
  }
  rows.forEach((item) => {
    const tr = document.createElement('tr');
    tr.tabIndex = 0;
    tr.innerHTML = `
      <td class="session-title-cell">
        <div class="session-name">${escapeHtml(item.title || '新对话')}</div>
        <div class="session-id">${escapeHtml((item.id || '').slice(0, 12))}</div>
      </td>
      <td>${formatNumber(item.token_usage?.total_tokens || 0)}</td>
      <td>${formatNumber(item.message_count || 0)}</td>
      <td>${formatNumber(item.tool_calls || 0)} / ${formatNumber(item.tool_failures || 0)}</td>
      <td>${formatNumber(item.branch?.branch_points || 0)} 点 · 深度 ${formatNumber(item.branch?.max_depth || 0)}</td>
      <td><span class="health-pill ${healthClass(item.health_score)}">${formatNumber(item.health_score)}</span></td>
      <td>${escapeHtml(formatTime(item.updated_at || item.created_at))}</td>
    `;
    tr.addEventListener('click', () => openSessionDetail(item.id));
    tr.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') openSessionDetail(item.id);
    });
    els.sessionTable.appendChild(tr);
  });
};

const renderSummary = (summary) => {
  state.summary = summary;
  renderKpis(summary);
  renderLineChart(els.tokenTrend, summary.timeseries || []);
  renderDonut(els.tokenDonut, els.tokenLegend, summary.token_breakdown || []);
  renderBars(els.sessionTokenBars, summary.top_sessions || [], {
    label: (item) => item.title,
    value: (item) => item.token_usage?.total_tokens || 0,
    color: (_, index) => colors[index % colors.length],
    emptyText: '暂无会话 token 数据',
  });
  renderBars(els.roleTokenBars, summary.role_tokens || [], {
    label: (item) => item.label,
    value: (item) => item.tokens || 0,
    limit: 8,
    emptyText: '暂无角色 token 数据',
  });
  renderCategoryBars(els.toolCategoryBars, summary.tool_summary?.by_category || []);
  renderBars(els.topCommandBars, summary.tool_summary?.top_commands || [], {
    label: (item) => item.label,
    value: (item) => item.count,
    limit: 8,
    suffix: ' 次',
    emptyText: '暂无命令数据',
  });
  renderToolFeed(els.recentToolCalls, summary.recent_tool_calls || []);
  renderAlerts(els.alerts, summary.alerts || []);
  renderWordCloud(els.wordCloud, summary.word_cloud || []);
  renderHeatmap(els.heatmap, summary.heatmap || []);
  els.subtitle.textContent = `范围：${rangeLabel(state.range)} · ${formatTime(summary.generated_at)} 更新`;
  els.freshness.textContent = formatTime(summary.generated_at);
};

const rangeLabel = (range) => ({
  all: '全部',
  '30d': '30 天',
  '7d': '7 天',
  today: '今天',
}[range] || range);

const loadWordCloud = async () => {
  if (state.scope === 'all' && state.summary?.word_cloud) {
    renderWordCloud(els.wordCloud, state.summary.word_cloud);
    return;
  }
  const params = new URLSearchParams({ scope: state.scope, limit: '90' });
  const data = await fetchJson(`/api/dashboard/word-cloud?${params.toString()}`);
  renderWordCloud(els.wordCloud, data.words || []);
};

const loadDashboard = async () => {
  els.refresh.classList.add('loading');
  try {
    const params = new URLSearchParams({ range: state.range });
    const [summary, sessions] = await Promise.all([
      fetchJson(`/api/dashboard/summary?${params.toString()}`),
      fetchJson(`/api/dashboard/sessions?${params.toString()}&sort=total_tokens&limit=120`),
    ]);
    state.sessions = sessions.sessions || [];
    renderSummary(summary);
    renderSessionTable();
    await loadWordCloud();
  } catch (error) {
    els.subtitle.textContent = error.message || '看板加载失败';
  } finally {
    els.refresh.classList.remove('loading');
  }
};

const openDrawer = () => {
  els.drawer.classList.add('open');
  els.drawerBackdrop.classList.add('open');
  els.drawer.setAttribute('aria-hidden', 'false');
};

const closeDrawer = () => {
  els.drawer.classList.remove('open');
  els.drawerBackdrop.classList.remove('open');
  els.drawer.setAttribute('aria-hidden', 'true');
};

const renderMiniLine = (svg, points) => {
  clear(svg);
  const width = 510;
  const height = 160;
  const pad = 16;
  const values = (points || []).map((item, index) => ({
    x: index,
    y: Number(item.cumulative_tokens || item.tokens || 0),
  }));
  if (!values.length) return;
  const max = Math.max(...values.map((item) => item.y), 1);
  const xFor = (index) => pad + (values.length === 1 ? (width - pad * 2) / 2 : (width - pad * 2) * index / (values.length - 1));
  const yFor = (value) => height - pad - value / max * (height - pad * 2);
  const line = values.map((item, index) => `${xFor(index)},${yFor(item.y)}`).join(' L ');
  svg.appendChild(svgEl('path', {
    d: `M ${line}`,
    fill: 'none',
    stroke: '#007aff',
    'stroke-width': 3,
    'stroke-linecap': 'round',
    'stroke-linejoin': 'round',
  }));
};

const openSessionDetail = async (sessionId) => {
  openDrawer();
  els.drawerTitle.textContent = '加载中';
  els.drawerBody.innerHTML = '<div class="empty-note">读取会话详情…</div>';
  try {
    const detail = await fetchJson(`/api/dashboard/sessions/${encodeURIComponent(sessionId)}`);
    const session = detail.session || {};
    els.drawerTitle.textContent = session.title || '新对话';
    els.drawerBody.innerHTML = `
      <section class="drawer-section">
        <div class="mini-kpis">
          <div class="mini-kpi"><span>Token</span><strong>${formatNumber(session.token_usage?.total_tokens || 0)}</strong></div>
          <div class="mini-kpi"><span>工具</span><strong>${formatNumber(session.tool_calls || 0)}</strong></div>
          <div class="mini-kpi"><span>健康度</span><strong>${formatNumber(session.health_score || 0)}</strong></div>
        </div>
      </section>
      <section class="drawer-section">
        <h3>累计 Token</h3>
        <svg class="token-curve" id="drawerTokenCurve" viewBox="0 0 510 160"></svg>
      </section>
      <section class="drawer-section">
        <h3>Token 构成</h3>
        <div class="bar-list compact" id="drawerBreakdown"></div>
      </section>
      <section class="drawer-section">
        <h3>工具调用</h3>
        <div class="tool-feed" id="drawerTools"></div>
      </section>
      <section class="drawer-section">
        <h3>最近消息</h3>
        <div class="tool-feed" id="drawerMessages"></div>
      </section>
    `;
    renderMiniLine(document.getElementById('drawerTokenCurve'), detail.token_curve || []);
    renderBars(document.getElementById('drawerBreakdown'), detail.token_breakdown || [], {
      label: (item) => item.label,
      value: (item) => item.tokens || 0,
      limit: 8,
      emptyText: '暂无 token 构成',
    });
    renderToolFeed(document.getElementById('drawerTools'), detail.tool_calls || []);
    renderRecentMessages(document.getElementById('drawerMessages'), detail.recent_messages || []);
  } catch (error) {
    els.drawerTitle.textContent = '读取失败';
    els.drawerBody.innerHTML = `<div class="empty-note">${escapeHtml(error.message || '请求失败')}</div>`;
  }
};

const renderRecentMessages = (container, rows) => {
  clear(container);
  if (!rows.length) {
    empty(container, '暂无消息');
    return;
  }
  rows.forEach((item) => {
    const row = document.createElement('div');
    row.className = 'tool-item';
    row.innerHTML = `
      <span class="tool-status ${item.category === 'tool_result' ? 'unknown' : ''}"></span>
      <div class="tool-main">
        <div class="tool-command">${escapeHtml((item.preview || '').replace(/\s+/g, ' ').slice(0, 140) || '-')}</div>
        <div class="tool-session">${escapeHtml(item.role || 'message')} · ${escapeHtml(item.category || '')}</div>
      </div>
      <div class="tool-meta">${formatNumber(item.tokens || 0)} tok</div>
    `;
    container.appendChild(row);
  });
};

document.querySelectorAll('.range-control button').forEach((button) => {
  button.addEventListener('click', () => {
    document.querySelectorAll('.range-control button').forEach((item) => item.classList.remove('active'));
    button.classList.add('active');
    state.range = button.dataset.range || 'all';
    loadDashboard();
  });
});

document.querySelectorAll('.scope-control button').forEach((button) => {
  button.addEventListener('click', async () => {
    document.querySelectorAll('.scope-control button').forEach((item) => item.classList.remove('active'));
    button.classList.add('active');
    state.scope = button.dataset.scope || 'all';
    await loadWordCloud();
  });
});

document.querySelectorAll('.dash-nav-link').forEach((link) => {
  link.addEventListener('click', () => {
    document.querySelectorAll('.dash-nav-link').forEach((item) => item.classList.remove('active'));
    link.classList.add('active');
  });
});

els.refresh.addEventListener('click', loadDashboard);
els.search.addEventListener('input', renderSessionTable);
els.closeDrawer.addEventListener('click', closeDrawer);
els.drawerBackdrop.addEventListener('click', closeDrawer);
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') closeDrawer();
});

loadDashboard();
