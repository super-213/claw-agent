import { useId } from 'react';
import { Monitor, Moon, Sun } from 'lucide-react';
import { useThemeStore } from '../../stores/themeStore';
import './theme-selector.css';

const modes = [
  { value: 'light', label: '浅色', icon: Sun },
  { value: 'auto', label: '自动', icon: Monitor },
  { value: 'dark', label: '深色', icon: Moon },
] as const;

export function ThemeSelector() {
  const id = useId();
  const preference = useThemeStore((state) => state.preference);
  const setPreference = useThemeStore((state) => state.setPreference);

  return (
    <fieldset className="theme-selector" aria-describedby={`${id}-description`}>
      <legend>外观</legend>
      <p id={`${id}-description`} className="home-muted">自动模式跟随系统，选择会保存在此浏览器。</p>
      <div className="theme-options">
        {modes.map(({ value, label, icon: Icon }) => (
          <label className="theme-option" key={value}>
            <input
              className="sr-only"
              type="radio"
              name={`${id}-theme`}
              value={value}
              checked={preference === value}
              onChange={() => setPreference(value)}
            />
            <Icon size={18} aria-hidden="true" />
            <span>{label}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
