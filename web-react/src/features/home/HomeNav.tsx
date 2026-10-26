import { Link } from 'react-router-dom';
import { Home, House, MoreHorizontal, MessageCircle } from 'lucide-react';
import { useAppStore } from '../../stores/appStore';
import { familyPath } from './familyNavigation';
import './home-navigation.css';

const menu = [
  { path: '/home', view: 'today', label: '工作台', icon: Home },
  { path: '/chat', view: 'chat', label: '对话', icon: MessageCircle },
  { path: '/home/family', view: 'family', label: '家庭', icon: House },
  { path: '/home/more', view: 'more', label: '更多', icon: MoreHorizontal },
];

export function HomeNav({ view, mobile = false, onLeave }: {
  view: string;
  mobile?: boolean;
  onLeave?: () => void;
}) {
  const familyView = ['items', 'tasks', 'library', 'memories'].includes(view);
  const activeView = familyView ? 'family' : view;
  const userId = useAppStore((state) => state.currentUser?.id || 'guest');
  const links = menu.map((item) => (
    <Link key={item.path} to={item.view === 'family'
      ? (familyView ? `/home/${view}` : familyPath(userId))
      : item.path}
      aria-current={activeView === item.view ? 'page' : undefined} onClick={onLeave}>
      <item.icon size={mobile ? 20 : 21} />
      <span>{item.label}</span>
    </Link>
  ));
  return mobile ? (
    <nav className="home-bottom-nav" aria-label="手机主导航">{links}</nav>
  ) : (
    <aside className="home-side-nav">
      <Link className="home-brand" to="/home" aria-label="家庭 Agent 工作台" onClick={onLeave}>
        <Home size={23} />
        <span>家庭<br />Agent</span>
      </Link>
      <nav aria-label="主导航">{links}</nav>
    </aside>
  );
}
