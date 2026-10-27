import { cloneElement, useEffect, useState, type ReactElement, type ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';
import { LayoutGrid, StickyNote } from 'lucide-react';
import { BoardPanel } from './BoardPanel';
import './board.css';

export function WorkbenchPanels({ userId, children }: { userId: string; children: ReactElement<{ panelSwitch?: ReactNode }> }) {
  const [params] = useSearchParams();
  const storageKey = `claw.home.panel.v1.${userId}`;
  const [panel, setPanel] = useState<'widgets' | 'board'>(() => {
    if (params.get('panel') === 'board') return 'board';
    try { return localStorage.getItem(storageKey) === 'board' ? 'board' : 'widgets'; } catch { return 'widgets'; }
  });
  useEffect(() => { if (params.get('panel') === 'board') setPanel('board'); }, [params]);
  const change = (value: 'widgets' | 'board') => { setPanel(value); try { localStorage.setItem(storageKey, value); } catch { /* Current view remains usable without persistence. */ } };
  const tabs = <div className="home-panel-tabs" role="group" aria-label="工作台内容">
    <button type="button" aria-pressed={panel === 'widgets'} onClick={() => change('widgets')}><LayoutGrid size={16} />我的小组件</button>
    <button type="button" aria-pressed={panel === 'board'} onClick={() => change('board')}><StickyNote size={16} />留言板</button>
  </div>;
  return <div className="workbench-panels"><div hidden={panel !== 'widgets'}>{cloneElement(children, { panelSwitch: tabs })}</div><BoardPanel active={panel === 'board'} panelSwitch={tabs} /></div>;
}
