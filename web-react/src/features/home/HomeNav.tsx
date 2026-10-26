import { Link } from 'react-router-dom';
import {
  Home,
  Package,
  ListTodo,
  MoreHorizontal,
  MessageCircle,
} from 'lucide-react';
const menu = [
  { path: '/home', label: '今日', icon: Home },
  { path: '/home/items', label: '物品', icon: Package },
  { path: '/home/tasks', label: '事项', icon: ListTodo },
  { path: '/home/more', label: '更多', icon: MoreHorizontal },
];
export function HomeNav({
  view,
  mobile = false,
  onLeave,
  onRecent,
}: {
  view: string;
  mobile?: boolean;
  onLeave: () => void;
  onRecent: () => void;
}) {
  const isToday = view === 'today';
  return mobile ? (
    <nav className="home-bottom-nav" aria-label="手机家庭导航">
      {menu.map((item) => (
        <Link
          key={item.path}
          to={item.path}
          aria-current={
            view === item.path.split('/')[2] ||
            (item.path === '/home' && isToday)
              ? 'page'
              : undefined
          }
          onClick={() => {
            onLeave();
          }}
        >
          <item.icon size={20} />
          <span>{item.label}</span>
        </Link>
      ))}
    </nav>
  ) : (
    <aside className="home-side-nav" aria-label="家庭导航">
      <Link className="home-brand" to="/home" aria-label="家庭 Agent 首页">
        <Home size={23} />
        <span>
          家庭
          <br />
          Agent
        </span>
      </Link>
      <nav>
        {menu.map((item) => (
          <Link
            key={item.path}
            to={item.path}
            aria-current={
              view === item.path.split('/')[2] ||
              (item.path === '/home' && isToday)
                ? 'page'
                : undefined
            }
            onClick={() => {
              onLeave();
            }}
          >
            <item.icon size={21} />
            <span>{item.label}</span>
          </Link>
        ))}
      </nav>
      <button
        className="home-recent-entry"
        type="button"
        onClick={() => onRecent()}
      >
        <MessageCircle size={20} />
        <span>最近对话</span>
      </button>
    </aside>
  );
}
