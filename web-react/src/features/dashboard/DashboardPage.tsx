import { RefreshCw, Search, X } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import type React from 'react';
import { dashboardApi, type DashboardRange, type WordScope } from '../../api/dashboard';
import type { DashboardSessionDetail, DashboardSummary, HomeTaskSummary } from '../../api/types';
import { formatNumber, formatTime } from '../../utils/format';

const colors = ['#007aff', '#34c759', '#ff9500', '#ff3b30', '#af52de', '#30b0c7', '#5856d6'];
const categoryLabels: Record<string, string> = {
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

const asNumber = (value: unknown) => Number(value || 0);
const labelOf = (item: Record<string, any>) => String(item.label || item.title || item.word || item.category || '-');

function EmptyNote({ text = '暂无数据' }: { text?: string }) {
  return <div className="empty-note">{text}</div>;
}

function KpiTile({ label, value, hint }: { label: string; value: unknown; hint: string }) {
  return (
    <article className="kpi-tile">
      <span className="kpi-label">{label}</span>
      <strong>{typeof value === 'string' ? value : formatNumber(value)}</strong>
      <small>{hint}</small>
    </article>
  );
}

function LineChart({ rows }: { rows: Array<Record<string, any>> }) {
  const width = 720;
  const height = 260;
  const pad = { left: 48, right: 18, top: 20, bottom: 34 };
  const points = rows.map((item) => ({ label: String(item.date || ''), value: asNumber(item.tokens) }));
  const max = Math.max(...points.map((item) => item.value), 1);
  const innerWidth = width - pad.left - pad.right;
  const innerHeight = height - pad.top - pad.bottom;
  const xFor = (index: number) => pad.left + (points.length === 1 ? innerWidth / 2 : (innerWidth * index) / Math.max(1, points.length - 1));
  const yFor = (value: number) => pad.top + innerHeight - (value / max) * innerHeight;
  const linePoints = points.map((item, index) => `${xFor(index)},${yFor(item.value)}`);
  const areaD = points.length
    ? [`M ${xFor(0)} ${pad.top + innerHeight}`, `L ${linePoints.join(' L ')}`, `L ${xFor(points.length - 1)} ${pad.top + innerHeight}`, 'Z'].join(' ')
    : '';

  return (
    <svg className="line-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Token 趋势图">
      {!points.length ? (
        <text x={width / 2} y={height / 2} className="chart-label" textAnchor="middle">
          暂无趋势数据
        </text>
      ) : (
        <>
          {[0, 1, 2, 3, 4].map((index) => {
            const y = pad.top + (innerHeight * index) / 4;
            return (
              <g key={index}>
                <line x1={pad.left} x2={width - pad.right} y1={y} y2={y} className="grid-line" />
                <text x={8} y={y + 4} className="chart-label">
                  {formatNumber(max * (1 - index / 4))}
                </text>
              </g>
            );
          })}
          <path d={areaD} className="area-path" />
          <path d={`M ${linePoints.join(' L ')}`} className="line-path" />
          {points.map((item, index) => (
            <circle key={`${item.label}-${index}`} cx={xFor(index)} cy={yFor(item.value)} r={4} className="chart-dot">
              <title>
                {item.label}: {formatNumber(item.value)} tokens
              </title>
            </circle>
          ))}
          <text x={pad.left} y={height - 8} className="chart-label">
            {points[0]?.label.slice(5)}
          </text>
          <text x={width - pad.right} y={height - 8} className="chart-label" textAnchor="end">
            {points[points.length - 1]?.label.slice(5)}
          </text>
        </>
      )}
    </svg>
  );
}

function Donut({ rows }: { rows: Array<Record<string, any>> }) {
  const data = rows.filter((item) => asNumber(item.tokens) > 0);
  const total = data.reduce((sum, item) => sum + asNumber(item.tokens), 0);
  const circumference = 2 * Math.PI * 78;
  let offset = 0;
  return (
    <div className="donut-wrap">
      <svg className="donut-chart" viewBox="0 0 220 220" role="img" aria-label="Token 构成图">
        <circle cx={110} cy={110} r={78} className="donut-bg" />
        {data.map((item, index) => {
          const ratio = asNumber(item.tokens) / Math.max(1, total);
          const dash = `${Math.max(1, ratio * circumference)} ${circumference}`;
          const segmentOffset = offset;
          offset += ratio * circumference;
          return (
            <circle
              key={labelOf(item)}
              cx={110}
              cy={110}
              r={78}
              className="donut-segment"
              stroke={colors[index % colors.length]}
              strokeDasharray={dash}
              strokeDashoffset={-segmentOffset}
            />
          );
        })}
        <text x={110} y={106} className="donut-center-title">
          Token
        </text>
        <text x={110} y={132} className="donut-center-value">
          {formatNumber(total)}
        </text>
      </svg>
      <div className="legend-list">
        {data.length ? (
          data.map((item, index) => (
            <div className="legend-item" key={labelOf(item)}>
              <span className="legend-dot" style={{ background: colors[index % colors.length] }} />
              <span>{labelOf(item)}</span>
              <strong>{formatNumber(item.tokens)}</strong>
            </div>
          ))
        ) : (
          <EmptyNote />
        )}
      </div>
    </div>
  );
}

function BarList({
  rows,
  valueKey = 'value',
  limit = 10,
  suffix = '',
  emptyText = '暂无数据',
}: {
  rows?: Array<Record<string, any>>;
  valueKey?: string;
  limit?: number;
  suffix?: string;
  emptyText?: string;
}) {
  const data = (rows || []).slice(0, limit);
  const max = Math.max(...data.map((item) => asNumber(valueKey.split('.').reduce((acc, key) => acc?.[key], item))), 0);
  if (!data.length || !max) return <EmptyNote text={emptyText} />;
  return (
    <>
      {data.map((item, index) => {
        const value = asNumber(valueKey.split('.').reduce((acc, key) => acc?.[key], item));
        return (
          <div className="bar-row" key={`${labelOf(item)}-${index}`}>
            <div className="bar-row-head">
              <span className="bar-label" title={labelOf(item)}>
                {labelOf(item)}
              </span>
              <strong>
                {formatNumber(value)}
                {suffix}
              </strong>
            </div>
            <div className="bar-track">
              <div className="bar-fill" style={{ width: `${Math.max(3, (value / max) * 100)}%`, background: colors[index % colors.length] }} />
            </div>
          </div>
        );
      })}
    </>
  );
}

function ToolFeed({ rows }: { rows?: Array<Record<string, any>> }) {
  if (!rows?.length) return <EmptyNote text="暂无工具调用" />;
  return (
    <>
      {rows.map((item, index) => {
        const statusClass = item.success === false ? 'failed' : item.success === null ? 'unknown' : '';
        const statusText = item.success === false ? '失败' : item.success === null ? '未知' : '成功';
        return (
          <div className="tool-item" key={`${item.command_preview || index}`}>
            <span className={`tool-status ${statusClass}`} />
            <div className="tool-main">
              <div className="tool-command" title={String(item.command || '')}>
                {String(item.command_preview || item.command || '-')}
              </div>
              <div className="tool-session">{String(item.session_title || '新对话')}</div>
            </div>
            <div className="tool-meta">
              {statusText} · {categoryLabels[String(item.category)] || String(item.category || '未知')}
            </div>
          </div>
        );
      })}
    </>
  );
}

function WordCloud({ rows }: { rows?: Array<Record<string, any>> }) {
  const data = (rows || []).slice(0, 72);
  if (!data.length) return <EmptyNote text="暂无词云数据" />;
  const palette = ['#007aff', '#34c759', '#ff9500', '#af52de', '#30b0c7', '#ff3b30'];
  return (
    <>
      {data.map((item, index) => {
        const angle = index * 2.399963;
        const radius = Math.sqrt(index / Math.max(1, data.length)) * 45;
        const x = 50 + Math.cos(angle) * radius;
        const y = 50 + Math.sin(angle) * radius * 0.72;
        return (
          <span
            key={`${item.word}-${index}`}
            title={`${item.word}: ${item.count}`}
            style={{
              left: `${Math.max(8, Math.min(92, x))}%`,
              top: `${Math.max(12, Math.min(88, y))}%`,
              fontSize: `${Math.max(13, Math.min(48, asNumber(item.weight || 20)))}px`,
              color: palette[index % palette.length],
              animationDelay: `${Math.min(420, index * 18)}ms`,
            }}
          >
            {String(item.word)}
          </span>
        );
      })}
    </>
  );
}

function Heatmap({ rows }: { rows?: Array<Record<string, any>> }) {
  const map = new Map((rows || []).map((item) => [`${item.weekday}:${item.hour}`, asNumber(item.count)]));
  const max = Math.max(...map.values(), 1);
  const cells = [];
  for (let weekday = 0; weekday < 7; weekday += 1) {
    for (let hour = 0; hour < 24; hour += 1) {
      const value = map.get(`${weekday}:${hour}`) || 0;
      cells.push(
        <div
          key={`${weekday}-${hour}`}
          className="heat-cell"
          style={{ '--heat': `${Math.round((value / max) * 78)}%` } as React.CSSProperties}
          title={`周${weekdays[weekday]} ${String(hour).padStart(2, '0')}:00 · ${value} 条`}
        />,
      );
    }
  }
  return <>{cells}</>;
}

const healthClass = (score: number) => {
  if (score < 60) return 'danger';
  if (score < 82) return 'warn';
  return '';
};

function DetailDrawer({
  detail,
  open,
  onClose,
}: {
  detail: DashboardSessionDetail | null;
  open: boolean;
  onClose: () => void;
}) {
  const session = detail?.session || {};
  return (
    <>
      <aside className={`detail-drawer${open ? ' open' : ''}`} aria-hidden={!open}>
        <div className="drawer-head">
          <div>
            <span className="drawer-kicker">会话详情</span>
            <h2>{open ? session.title || '加载中' : '-'}</h2>
          </div>
          <button className="icon-button" type="button" aria-label="关闭详情" onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        <div className="drawer-body">
          {!detail ? (
            <EmptyNote text="读取会话详情..." />
          ) : (
            <>
              <section className="drawer-section">
                <div className="mini-kpis">
                  <div className="mini-kpi">
                    <span>Token</span>
                    <strong>{formatNumber(session.token_usage?.total_tokens || 0)}</strong>
                  </div>
                  <div className="mini-kpi">
                    <span>工具</span>
                    <strong>{formatNumber(session.tool_calls || 0)}</strong>
                  </div>
                  <div className="mini-kpi">
                    <span>健康度</span>
                    <strong>{formatNumber(session.health_score || 0)}</strong>
                  </div>
                </div>
              </section>
              <section className="drawer-section">
                <h3>Token 构成</h3>
                <div className="bar-list compact">
                  <BarList rows={detail.token_breakdown as Array<Record<string, any>>} valueKey="tokens" limit={8} emptyText="暂无 token 构成" />
                </div>
              </section>
              <section className="drawer-section">
                <h3>工具调用</h3>
                <div className="tool-feed">
                  <ToolFeed rows={detail.tool_calls} />
                </div>
              </section>
              <section className="drawer-section">
                <h3>最近消息</h3>
                <div className="tool-feed">
                  {(detail.recent_messages || []).map((item, index) => (
                    <div className="tool-item" key={index}>
                      <span className={`tool-status ${item.category === 'tool_result' ? 'unknown' : ''}`} />
                      <div className="tool-main">
                        <div className="tool-command">{String(item.preview || '').replace(/\s+/g, ' ').slice(0, 140) || '-'}</div>
                        <div className="tool-session">
                          {String(item.role || 'message')} · {String(item.category || '')}
                        </div>
                      </div>
                      <div className="tool-meta">{formatNumber(item.tokens || 0)} tok</div>
                    </div>
                  ))}
                </div>
              </section>
            </>
          )}
        </div>
      </aside>
      <div className={`drawer-backdrop${open ? ' open' : ''}`} aria-hidden="true" onClick={onClose} />
    </>
  );
}

export function DashboardPage() {
  const [range, setRange] = useState<DashboardRange>('all');
  const [scope, setScope] = useState<WordScope>('all');
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [homeSummary, setHomeSummary] = useState<HomeTaskSummary | null>(null);
  const [sessions, setSessions] = useState<Array<Record<string, any>>>([]);
  const [wordRows, setWordRows] = useState<Array<Record<string, any>>>([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [subtitle, setSubtitle] = useState('全局使用、Token、工具调用与主题分析');
  const [detail, setDetail] = useState<DashboardSessionDetail | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    document.body.classList.add('dashboard-route');
    return () => {
      document.body.classList.remove('dashboard-route');
    };
  }, []);

  const loadDashboard = useCallback(async () => {
    setLoading(true);
    try {
      const [nextSummary, nextSessions, nextHomeSummary] = await Promise.all([
        dashboardApi.summary(range),
        dashboardApi.sessions(range),
        dashboardApi.homeTaskSummary(),
      ]);
      setSummary(nextSummary);
      setHomeSummary(nextHomeSummary);
      setSessions(nextSessions.sessions || []);
      setSubtitle(`范围：${range === 'all' ? '全部' : range} · ${formatTime(nextSummary.generated_at)} 更新`);
      if (scope === 'all') setWordRows((nextSummary.word_cloud as Array<Record<string, any>>) || []);
      else {
        const data = await dashboardApi.wordCloud(scope);
        setWordRows(data.words || []);
      }
    } catch (caught) {
      setSubtitle((caught as Error).message || '看板加载失败');
    } finally {
      setLoading(false);
    }
  }, [range, scope]);

  useEffect(() => {
    void loadDashboard();
  }, [loadDashboard]);

  const filteredSessions = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return sessions;
    return sessions.filter((item) => `${item.title} ${item.id}`.toLowerCase().includes(query));
  }, [sessions, search]);

  const kpis = summary?.kpis || {};
  const toolSummary = (summary?.tool_summary || {}) as Record<string, any>;
  const trendTotal = ((summary?.timeseries as Array<Record<string, any>>) || []).reduce((sum, item) => sum + asNumber(item.tokens), 0);

  const openDetail = async (sessionId: string) => {
    setDrawerOpen(true);
    setDetail(null);
    const nextDetail = await dashboardApi.sessionDetail(sessionId);
    setDetail(nextDetail);
  };

  return (
    <div className="dashboard-shell">
      <aside className="dashboard-sidebar" aria-label="后台导航">
        <div className="dash-brand">
          <div className="dash-brand-mark">C</div>
          <div>
            <div className="dash-brand-name">Claw Agent</div>
            <div className="dash-brand-sub">后台看板</div>
          </div>
        </div>
        <nav className="dash-nav">
          {['overview', 'home', 'tokens', 'sessions', 'tools', 'words'].map((id, index) => (
            <a key={id} href={`#${id}`} className={`dash-nav-link${index === 0 ? ' active' : ''}`}>
              {['总览', '家庭', 'Token', '会话', '工具', '词云'][index]}
            </a>
          ))}
        </nav>
        <div className="dash-sidebar-footer">
          <a className="chat-link" href="/">
            返回对话
          </a>
          <div className="freshness">
            <span className="status-dot" />
            <span>{formatTime(summary?.generated_at) || '等待同步'}</span>
          </div>
        </div>
      </aside>

      <main className="dashboard-main">
        <header className="dashboard-topbar">
          <div>
            <h1>后台看板</h1>
            <p>{subtitle}</p>
          </div>
          <div className="topbar-actions">
            <div className="range-control" aria-label="时间范围">
              {(['all', '30d', '7d', 'today'] as DashboardRange[]).map((item) => (
                <button key={item} type="button" data-range={item} className={range === item ? 'active' : ''} onClick={() => setRange(item)}>
                  {item === 'all' ? '全部' : item === 'today' ? '今天' : item.replace('d', ' 天')}
                </button>
              ))}
            </div>
            <button className={`icon-button${loading ? ' loading' : ''}`} type="button" aria-label="刷新" onClick={() => void loadDashboard()}>
              <RefreshCw size={18} />
            </button>
          </div>
        </header>

        <section className="kpi-grid" id="overview" aria-label="核心指标">
          <KpiTile label="总 Token" value={kpis.total_tokens || 0} hint={`平均 ${formatNumber(kpis.avg_tokens_per_session || 0)} / 会话`} />
          <KpiTile label="会话" value={kpis.total_sessions || 0} hint={`${formatNumber(kpis.total_messages || 0)} 条消息`} />
          <KpiTile label="工具调用" value={kpis.tool_calls || 0} hint={`${formatNumber(kpis.tool_failures || 0)} 次失败`} />
          <KpiTile label="工具成功率" value={`${asNumber(kpis.tool_success_rate).toFixed(1)}%`} hint={`平均输出 ${formatNumber(toolSummary.avg_output_chars || 0)} 字符`} />
        </section>

        <section className="dashboard-grid" id="home">
          <article className="panel panel-wide">
            <div className="panel-head">
              <div>
                <h2>家庭任务总览</h2>
                <p>提醒、周期任务和未触达通知</p>
              </div>
              <span className="panel-stat">{formatNumber(homeSummary?.kpis?.total_tasks || 0)}</span>
            </div>
            <div className="mini-kpis">
              <div className="mini-kpi">
                <span>今日待执行</span>
                <strong>{formatNumber(homeSummary?.kpis?.due_today || 0)}</strong>
              </div>
              <div className="mini-kpi">
                <span>未来 7 天</span>
                <strong>{formatNumber(homeSummary?.kpis?.due_next_7_days || 0)}</strong>
              </div>
              <div className="mini-kpi">
                <span>逾期未发送</span>
                <strong>{formatNumber(homeSummary?.kpis?.overdue || 0)}</strong>
              </div>
              <div className="mini-kpi">
                <span>通知成功率</span>
                <strong>{formatNumber(homeSummary?.kpis?.notification_success_rate || 0)}%</strong>
              </div>
            </div>
          </article>
          <article className="panel">
            <div className="panel-head">
              <div>
                <h2>任务状态</h2>
                <p>按提醒状态聚合</p>
              </div>
            </div>
            <div className="bar-list compact">
              <BarList rows={homeSummary?.status_distribution as Array<Record<string, any>>} valueKey="value" limit={8} emptyText="暂无家庭任务" />
            </div>
          </article>
          <article className="panel">
            <div className="panel-head">
              <div>
                <h2>提醒渠道</h2>
                <p>站内、浏览器推送与备用渠道</p>
              </div>
            </div>
            <div className="bar-list compact">
              <BarList rows={homeSummary?.channel_distribution as Array<Record<string, any>>} valueKey="value" limit={8} emptyText="暂无渠道数据" />
            </div>
          </article>
        </section>

        <section className="dashboard-grid" id="tokens">
          <article className="panel panel-wide">
            <div className="panel-head">
              <div>
                <h2>Token 趋势</h2>
                <p>按消息时间聚合</p>
              </div>
              <span className="panel-stat">{formatNumber(trendTotal)}</span>
            </div>
            <LineChart rows={(summary?.timeseries as Array<Record<string, any>>) || []} />
          </article>
          <article className="panel">
            <div className="panel-head">
              <div>
                <h2>Token 构成</h2>
                <p>按来源拆分</p>
              </div>
            </div>
            <Donut rows={(summary?.token_breakdown as Array<Record<string, any>>) || []} />
          </article>
          <article className="panel panel-wide">
            <div className="panel-head">
              <div>
                <h2>会话 Token 排行</h2>
                <p>Top 会话</p>
              </div>
            </div>
            <div className="bar-list">
              <BarList rows={(summary?.top_sessions as Array<Record<string, any>>) || []} valueKey="token_usage.total_tokens" emptyText="暂无会话 token 数据" />
            </div>
          </article>
          <article className="panel">
            <div className="panel-head">
              <div>
                <h2>角色占比</h2>
                <p>系统、用户、助手、工具</p>
              </div>
            </div>
            <div className="bar-list compact">
              <BarList rows={(summary?.role_tokens as Array<Record<string, any>>) || []} valueKey="tokens" limit={8} emptyText="暂无角色 token 数据" />
            </div>
          </article>
        </section>

        <section className="dashboard-grid" id="tools">
          <article className="panel panel-wide">
            <div className="panel-head">
              <div>
                <h2>工具调用分布</h2>
                <p>按命令类型聚合</p>
              </div>
            </div>
            <div className="stacked-area">
              <BarList rows={(toolSummary.by_category as Array<Record<string, any>>) || []} valueKey="count" suffix=" 次" emptyText="暂无工具调用" />
            </div>
          </article>
          <article className="panel">
            <div className="panel-head">
              <div>
                <h2>Top 命令</h2>
                <p>按调用次数排序</p>
              </div>
            </div>
            <div className="bar-list compact">
              <BarList rows={(toolSummary.top_commands as Array<Record<string, any>>) || []} valueKey="count" limit={8} suffix=" 次" emptyText="暂无命令数据" />
            </div>
          </article>
          <article className="panel panel-wide">
            <div className="panel-head">
              <div>
                <h2>最近工具调用</h2>
                <p>命令、会话与状态</p>
              </div>
            </div>
            <div className="tool-feed">
              <ToolFeed rows={(summary?.recent_tool_calls as Array<Record<string, any>>) || []} />
            </div>
          </article>
          <article className="panel">
            <div className="panel-head">
              <div>
                <h2>异常</h2>
                <p>需要关注的会话与命令</p>
              </div>
            </div>
            <div className="alert-list">
              {((summary?.alerts as Array<Record<string, any>>) || []).length ? (
                ((summary?.alerts as Array<Record<string, any>>) || []).map((item, index) => (
                  <div className={`alert-item ${item.level || ''}`} key={index}>
                    <div className="alert-title">{String(item.title || '提示')}</div>
                    <div className="alert-message">{String(item.message || '')}</div>
                  </div>
                ))
              ) : (
                <EmptyNote text="暂无异常" />
              )}
            </div>
          </article>
        </section>

        <section className="dashboard-grid" id="words">
          <article className="panel panel-wide">
            <div className="panel-head">
              <div>
                <h2>词云</h2>
                <p>用户与助手消息主题</p>
              </div>
              <div className="scope-control" aria-label="词云范围">
                {(['all', 'user', 'assistant', 'tool'] as WordScope[]).map((item) => (
                  <button key={item} type="button" data-scope={item} className={scope === item ? 'active' : ''} onClick={() => setScope(item)}>
                    {item === 'all' ? '全部' : item === 'user' ? '用户' : item === 'assistant' ? '助手' : '工具'}
                  </button>
                ))}
              </div>
            </div>
            <div className="word-cloud">
              <WordCloud rows={wordRows} />
            </div>
          </article>
          <article className="panel">
            <div className="panel-head">
              <div>
                <h2>活跃热力</h2>
                <p>星期与小时</p>
              </div>
            </div>
            <div className="heatmap">
              <Heatmap rows={(summary?.heatmap as Array<Record<string, any>>) || []} />
            </div>
          </article>
        </section>

        <section className="panel" id="sessions">
          <div className="panel-head">
            <div>
              <h2>会话明细</h2>
              <p>Token、工具调用、分支与健康度</p>
            </div>
            <label className="search-box">
              <Search size={16} />
              <input type="search" placeholder="搜索会话" autoComplete="off" value={search} onChange={(event) => setSearch(event.target.value)} />
            </label>
          </div>
          <div className="session-table-wrap">
            <table className="session-table">
              <thead>
                <tr>
                  <th>会话</th>
                  <th>Token</th>
                  <th>消息</th>
                  <th>工具</th>
                  <th>分支</th>
                  <th>健康度</th>
                  <th>更新</th>
                </tr>
              </thead>
              <tbody>
                {filteredSessions.length ? (
                  filteredSessions.map((item) => (
                    <tr key={item.id} tabIndex={0} onClick={() => void openDetail(String(item.id))} onKeyDown={(event) => event.key === 'Enter' && void openDetail(String(item.id))}>
                      <td className="session-title-cell">
                        <div className="session-name">{String(item.title || '新对话')}</div>
                        <div className="session-id">{String(item.id || '').slice(0, 12)}</div>
                      </td>
                      <td>{formatNumber(item.token_usage?.total_tokens || 0)}</td>
                      <td>{formatNumber(item.message_count || 0)}</td>
                      <td>
                        {formatNumber(item.tool_calls || 0)} / {formatNumber(item.tool_failures || 0)}
                      </td>
                      <td>
                        {formatNumber(item.branch?.branch_points || 0)} 点 · 深度 {formatNumber(item.branch?.max_depth || 0)}
                      </td>
                      <td>
                        <span className={`health-pill ${healthClass(asNumber(item.health_score))}`}>{formatNumber(item.health_score)}</span>
                      </td>
                      <td>{formatTime(item.updated_at || item.created_at)}</td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={7}>
                      <EmptyNote text="暂无会话" />
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </main>
      <DetailDrawer detail={detail} open={drawerOpen} onClose={() => setDrawerOpen(false)} />
    </div>
  );
}
