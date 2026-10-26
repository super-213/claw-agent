import { useId, type ReactNode } from 'react';
import { ArrowLeft } from 'lucide-react';
import { useDialog } from './useDialog';

export function HomeDialog({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  children: ReactNode | ((dismiss: () => void) => ReactNode);
  onClose: () => void;
  wide?: boolean;
}) {
  const id = useId();
  const { ref, dismiss } = useDialog(true, onClose);
  return (
    <div
      className="home-dialog-backdrop"
      onClick={(event) => {
        if (event.target === event.currentTarget) dismiss();
      }}
    >
      <div
        className={`home-dialog${wide ? ' wide' : ''}`}
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={id}
        tabIndex={-1}
      >
        <header>
          <button type="button" onClick={dismiss} aria-label="返回">
            <ArrowLeft size={19} />
          </button>
          <h2 id={id}>{title}</h2>
        </header>
        <div className="home-dialog-content">
          {typeof children === 'function' ? children(dismiss) : children}
        </div>
      </div>
    </div>
  );
}
