import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { Plus, RefreshCcw } from 'lucide-react';
import { sessionsApi } from '../../api/sessions';
import { skillsApi } from '../../api/skills';
import type { Skill } from '../../api/types';
import { useAppStore } from '../../stores/appStore';
import { SkillModal } from './SkillModal';

export function SkillsView() {
  const navigate = useNavigate();
  const user = useAppStore((s) => s.currentUser);
  const [adding, setAdding] = useState(false);
  const [reloading, setReloading] = useState(false);
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState('');
  const query = useQuery({ queryKey: ['skills', user?.id], queryFn: skillsApi.list });
  const reload = async () => {
    setReloading(true);
    setError('');
    try {
      await skillsApi.reload();
      await query.refetch({ throwOnError: true });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '重载失败，请重试。');
    } finally {
      setReloading(false);
    }
  };
  const useSkill = async (skill: Skill) => {
    setOpening(true);
    setError('');
    try {
      const state = useAppStore.getState();
      const id = state.currentSessionId || state.sessions[0]?.id || (await sessionsApi.create()).id;
      if (useAppStore.getState().currentUser?.id !== user?.id) return;
      const current = useAppStore.getState();
      const draft = current.chatDrafts[id] || '';
      current.setChatDraft(id, `调用 ${skill.name} skill ${draft.trimStart()}`);
      navigate(`/sessions/${encodeURIComponent(id)}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '打开对话失败，请重试。');
    } finally {
      setOpening(false);
    }
  };
  return (
    <>
      <div className="home-skills-toolbar">
        <button className="home-primary" type="button" onClick={() => setAdding(true)}><Plus size={18} aria-hidden="true" />添加技能</button>
        <button type="button" disabled={reloading} onClick={() => void reload()}><RefreshCcw size={18} aria-hidden="true" />{reloading ? '正在重载…' : '重载技能'}</button>
      </div>
      {query.isPending && <p role="status">正在读取技能…</p>}
      {query.isError && <p role="alert">技能列表加载失败。<button type="button" onClick={() => void query.refetch()}>重试</button></p>}
      {error && <p role="alert">{error}</p>}
      <div className="home-list">
        {(query.data?.skills || []).map((skill) => (
          <button className="home-session-row" type="button" key={skill.name} disabled={opening} onClick={() => void useSkill(skill)} aria-label={`使用技能 ${skill.name}`}>
            <strong>{skill.name}</strong>
            {skill.summary && <small>{skill.summary}</small>}
          </button>
        ))}
      </div>
      {query.isSuccess && !query.data.skills.length && <p className="home-empty">暂无技能，可以添加一个。</p>}
      <SkillModal open={adding} onClose={() => setAdding(false)} onSaved={async () => { await query.refetch({ throwOnError: true }); }} />
    </>
  );
}
