import { ReactNode, useEffect } from 'react';
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
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="modal-backdrop open" aria-hidden={!open} onClick={onClose}>
      <div className={`skill-modal ${className}`} role="dialog" aria-modal="true" aria-labelledby={`${title}-title`} onClick={(event) => event.stopPropagation()}>
        <div className="modal-head">
          <div className="modal-title" id={`${title}-title`}>
            {title}
          </div>
          <button className="modal-close" type="button" aria-label="关闭" onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
