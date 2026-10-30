import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { homeApi, type InventoryLocation } from '../../api/home';
import type { HomeInventoryItem } from '../../api/types';
import { HomeDialog } from '../../components/ui/HomeDialog';
import { useAppStore } from '../../stores/appStore';
import { activeInventory, addDays, expiryLabel, locations } from './attention';

export function InventoryView({
  onAgent,
  showCreateAction = true,
}: {
  onAgent: (item: HomeInventoryItem) => void;
  showCreateAction?: boolean;
}) {
  const [params, setParams] = useSearchParams();
  const location: InventoryLocation =
    params.get('location') && params.get('location')! in locations
      ? (params.get('location') as InventoryLocation)
      : 'fridge';
  const filter = params.get('filter') || 'available';
  const user = useAppStore((s) => s.currentUser?.id);
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ['home', user, 'inventory', location],
    queryFn: () => homeApi.inventory(location),
  });
  const [editing, setEditing] = useState<HomeInventoryItem | 'new' | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [filterOpen, setFilterOpen] = useState(false);
  const [draftFilter, setDraftFilter] = useState(filter);
  const applyFilter = useRef<string | null>(null);
  const [remove, setRemove] = useState(false);
  const selected = query.data?.items.find(
    (item) => item.id === params.get('item'),
  );
  useEffect(() => {
    if (params.get('create')) setEditing('new');
  }, [params]);
  const updateParams = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    Object.entries(patch).forEach(([key, value]) =>
      value ? next.set(key, value) : next.delete(key),
    );
    setParams(next, { replace: true });
  };
  const run = async (action: () => Promise<unknown>, message: string) => {
    setBusy(true);
    setError('');
    try {
      await action();
      setNotice(message);
      setRemove(false);
      await client.invalidateQueries({ queryKey: ['home', user] });
      window.dispatchEvent(new CustomEvent('inventory_changed'));
      return true;
    } catch (e) {
      setError((e as Error).message || '保存失败，请重试');
      return false;
    } finally {
      setBusy(false);
    }
  };
  const today = query.data?.today;
  const rows = (query.data?.items || []).filter(
    (item) =>
      filter === 'all' ||
      (filter === 'available'
        ? activeInventory(item)
        : filter === 'expiring'
          ? activeInventory(item) &&
            item.expires_at &&
            today &&
            item.expires_at <= addDays(today, 3)
          : filter === 'low'
            ? activeInventory(item) && item.status === 'low'
            : item.status === filter),
  );
  return (
    <section className="home-section inventory-view">
      <div className="home-section-head">
        <h2>家庭物品</h2>
        {showCreateAction && <button
          type="button"
          className="home-primary"
          onClick={() => setEditing('new')}
        >
          添加物品
        </button>}
      </div>
      <div className="task-tabs" aria-label="存放位置">
        {Object.entries(locations).map(([value, label]) => (
          <button
            key={value}
            type="button"
            aria-pressed={location === value}
            onClick={() => {
              setError('');
              setNotice('');
              updateParams({ location: value, item: null });
            }}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="home-section-head home-list-toolbar">
        <span>
          {{
            available: '可用物品',
            expiring: '已过期与三天内到期',
            low: '明确标记为低库存',
            consumed: '已用完',
            all: '全部物品',
          }[filter] || filter}
          {query.data ? ` · ${rows.length} 项` : ''}
        </span>
        <button
          type="button"
          onClick={() => {
            setDraftFilter(filter);
            setFilterOpen(true);
          }}
        >
          筛选
        </button>
      </div>
      {filter !== 'available' && (
        <p className="task-filter-summary">
          已筛选{' '}
          <button type="button" onClick={() => updateParams({ filter: null })}>
            清除
          </button>
        </p>
      )}
      {query.isPending && <p role="status">正在读取物品…</p>}
      {query.isError && (
        <p role="alert">
          {query.data ? '更新失败，保留上次物品记录。' : '暂时无法读取物品。'}
          <button type="button" onClick={() => void query.refetch()}>
            重试
          </button>
        </p>
      )}
      {notice && (
        <p className="home-feedback" role="status">
          {notice}
        </p>
      )}
      {error && <p role="alert">{error}</p>}
      <div className="home-list inventory-grid">
        {rows.map((item) => (
          <article className="home-list-item" key={item.id}>
            <button
              type="button"
              className="home-row-title"
              onClick={() => {
                setRemove(false);
                updateParams({ item: item.id });
              }}
            >
              <strong>
                {item.name}
                {item.quantity != null
                  ? ` ${item.quantity}${item.unit || ''}`
                  : ''}
              </strong>
              <small>
                {!activeInventory(item)
                  ? {
                      consumed: '已用完',
                      discarded: '已丢弃',
                      expired: '已过期',
                    }[item.status || ''] || item.status
                  : today
                    ? expiryLabel(item, today)
                    : '到期日期待更新'}
                {item.status === 'low' ? ' · 低库存' : ''}
              </small>
            </button>
            {activeInventory(item) && (
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  void run(
                    () =>
                      homeApi.consumeInventoryItem(
                        item.id,
                        undefined,
                        location,
                      ),
                    `${item.name} 已标记用完`,
                  )
                }
              >
                用完
              </button>
            )}
          </article>
        ))}
      </div>
      {query.data && !rows.length && (
        <div className="home-empty">
          <p>
            {query.data.items.length
              ? '没有符合筛选的物品。'
              : '还没有记录物品。'}
          </p>
          {!query.data.items.length && (
            <button type="button" onClick={() => setEditing('new')}>
              添加第一件物品
            </button>
          )}
        </div>
      )}
      {filterOpen && (
        <HomeDialog
          title="筛选物品"
          onClose={() => {
            setFilterOpen(false);
            if (applyFilter.current) {
              updateParams({ filter: applyFilter.current });
              applyFilter.current = null;
            }
          }}
        >
          {(dismiss) => (
            <>
              <label>
                物品状态
                <select
                  value={draftFilter}
                  onChange={(e) => setDraftFilter(e.target.value)}
                >
                  <option value="available">可用物品</option>
                  <option value="expiring">已过期与三天内到期</option>
                  <option value="low">低库存</option>
                  <option value="consumed">已用完</option>
                  <option value="all">全部物品</option>
                </select>
              </label>
              <div className="home-form-actions">
                <button
                  type="button"
                  onClick={() => setDraftFilter('available')}
                >
                  重置
                </button>
                <button
                  type="button"
                  className="home-primary"
                  onClick={() => {
                    applyFilter.current = draftFilter;
                    dismiss();
                  }}
                >
                  应用
                </button>
              </div>
            </>
          )}
        </HomeDialog>
      )}
      {(selected || editing) && (
        <HomeDialog
          title={
            editing ? (editing === 'new' ? '添加物品' : '编辑物品') : '物品详情'
          }
          onClose={() => {
            setEditing(null);
            updateParams({ item: null, create: null });
            setRemove(false);
          }}
        >
          {(dismiss) =>
            editing ? (
              <InventoryForm
                key={editing === 'new' ? location : editing.id}
                item={editing === 'new' ? undefined : editing}
                location={location}
                busy={busy}
                error={error}
                onSave={async (payload) => {
                  const ok = await run(
                    () =>
                      editing === 'new'
                        ? homeApi.addInventoryItem(payload, location)
                        : homeApi.updateInventoryItem(
                            editing.id,
                            payload,
                            location,
                          ),
                    '物品已保存',
                  );
                  if (ok) dismiss();
                }}
              />
            ) : selected ? (
              <>
                <h3>{selected.name}</h3>
                <dl className="home-detail-facts">
                  <dt>位置</dt>
                  <dd>
                    {locations[location]} · {selected.zone || '未分区'}
                  </dd>
                  <dt>数量</dt>
                  <dd>
                    {selected.quantity ?? '未知'}
                    {selected.unit}
                  </dd>
                  <dt>到期</dt>
                  <dd>{selected.expires_at || '未记录'}</dd>
                  <dt>状态</dt>
                  <dd>
                    {{
                      available: '可用',
                      low: '低库存',
                      consumed: '已用完',
                      discarded: '已丢弃',
                      expired: '已过期',
                    }[selected.status || 'available'] || selected.status}
                  </dd>
                  <dt>可见范围</dt>
                  <dd>家庭共享</dd>
                </dl>
                {error && <p role="alert">{error}</p>}
                {notice && <p role="status">{notice}</p>}
                <div className="home-form-actions">
                  <button type="button" onClick={() => setEditing(selected)}>
                    编辑物品
                  </button>
                  <button type="button" onClick={() => onAgent(selected)}>
                    让 Agent 帮忙
                  </button>
                  {!activeInventory(selected) && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        void run(
                          () =>
                            homeApi.restoreInventoryItem(selected.id, location),
                          '物品已恢复',
                        )
                      }
                    >
                      恢复为可用
                    </button>
                  )}
                  <button type="button" onClick={() => setRemove(true)}>
                    删除物品
                  </button>
                </div>
                {remove && (
                  <div role="alert">
                    <p>确认删除“{selected.name}”？</p>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        void run(
                          () =>
                            homeApi.deleteInventoryItem(selected.id, location),
                          '物品已删除',
                        ).then((ok) => {
                          if (ok) dismiss();
                        })
                      }
                    >
                      确认删除
                    </button>
                    <button type="button" onClick={() => setRemove(false)}>
                      保留物品
                    </button>
                  </div>
                )}
              </>
            ) : null
          }
        </HomeDialog>
      )}
    </section>
  );
}

function InventoryForm({
  item,
  location,
  busy,
  error,
  onSave,
}: {
  item?: HomeInventoryItem;
  location: InventoryLocation;
  busy: boolean;
  error: string;
  onSave: (payload: Partial<HomeInventoryItem>) => Promise<void>;
}) {
  const [name, setName] = useState(item?.name || '');
  const [quantity, setQuantity] = useState(item?.quantity?.toString() || '');
  const [unit, setUnit] = useState(item?.unit || '个');
  const [expiry, setExpiry] = useState(item?.expires_at || '');
  const [zone, setZone] = useState(
    item?.zone || (location === 'fridge' ? '冷藏层' : locations[location]),
  );
  const [status, setStatus] = useState(item?.status || 'available');
  const submit = (event: FormEvent) => {
    event.preventDefault();
    void onSave({
      name: name.trim(),
      quantity: quantity ? Number(quantity) : null,
      unit,
      zone,
      expires_at: expiry || null,
      status,
    });
  };
  return (
    <form className="home-form" onSubmit={submit}>
      <label>
        名称
        <input
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </label>
      <div className="home-form-pair">
        <label>
          数量
          <input
            type="number"
            min="0"
            step="any"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
          />
        </label>
        <label>
          单位
          <input value={unit} onChange={(e) => setUnit(e.target.value)} />
        </label>
      </div>
      <p>{locations[location]} · 家庭共享</p>
      <details>
        <summary>更多选项：到期日期与存放位置</summary>
        <label>
          到期日期
          <input
            type="date"
            value={expiry}
            onChange={(e) => setExpiry(e.target.value)}
          />
        </label>
        <label>
          存放位置
          <input value={zone} onChange={(e) => setZone(e.target.value)} />
        </label>
        <label>
          库存状态
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="available">可用</option>
            <option value="low">低库存</option>
            <option value="consumed">已用完</option>
            <option value="discarded">已丢弃</option>
          </select>
        </label>
      </details>
      {error && <p role="alert">{error}</p>}
      <button
        type="submit"
        className="home-primary"
        disabled={busy || !name.trim()}
      >
        {busy ? '正在保存…' : '保存物品'}
      </button>
    </form>
  );
}
