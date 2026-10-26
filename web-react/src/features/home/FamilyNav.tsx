import { useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ListTodo, Package, Plus } from 'lucide-react';
import { HomeDialog } from '../../components/ui/HomeDialog';
import type { FamilySection } from './familyNavigation';

export function FamilyNav({ section, onOpen }: {
  section: FamilySection;
  onOpen: (path: string) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [params] = useSearchParams();
  const destination = useRef<string | null>(null);
  const createPath = (target: FamilySection) => {
    const next = new URLSearchParams(section === target ? params : undefined);
    next.delete('item');
    next.delete('task');
    next.set('create', '1');
    return `/home/${target}?${next}`;
  };
  return (
    <div className="family-toolbar">
      <nav className="family-sections" aria-label="家庭信息分类">
        <Link to="/home/tasks" aria-current={section === 'tasks' ? 'page' : undefined}>
          <ListTodo size={18} />事项
        </Link>
        <Link to="/home/items" aria-current={section === 'items' ? 'page' : undefined}>
          <Package size={18} />物品
        </Link>
      </nav>
      <button type="button" className="home-primary" onClick={() => setAdding(true)}>
        <Plus size={18} />添加
      </button>
      {adding && (
        <HomeDialog title="添加家庭记录" onClose={() => {
          setAdding(false);
          if (destination.current) {
            onOpen(destination.current);
            destination.current = null;
          }
        }}>
          {(dismiss) => (
            <div className="family-add-options">
              <button type="button" onClick={() => {
                destination.current = createPath('tasks');
                dismiss();
              }}><ListTodo size={21} /><span><strong>新建事项</strong><small>安排日程、记录备忘和待办</small></span></button>
              <button type="button" onClick={() => {
                destination.current = createPath('items');
                dismiss();
              }}><Package size={21} /><span><strong>添加物品</strong><small>记录数量、存放位置和到期日期</small></span></button>
            </div>
          )}
        </HomeDialog>
      )}
    </div>
  );
}
