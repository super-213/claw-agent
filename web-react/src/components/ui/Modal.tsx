import { ReactNode } from 'react';
import { useDialog } from './useDialog';
import { X } from 'lucide-react';

export function Modal({
  open,
  title,
  children,
  className = '',
  onClose,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  className?: string;
  onClose: () => void;
}) {
  const { ref, dismiss } = useDialog(open, onClose);

  if (!open) return null;

  return (
    <div className="modal-backdrop open" aria-hidden={!open} onClick={dismiss}>
      <div
        className={`skill-modal ${className}`}
        ref={ref}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${title}-title`}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-head">
          <div className="modal-title" id={`${title}-title`}>
            {title}
          </div>
          <button
            className="modal-close"
            type="button"
            aria-label="关闭"
            onClick={dismiss}
          >
            <X size={18} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
