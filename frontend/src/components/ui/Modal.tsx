import type { ReactNode } from 'react';
import { cn } from '../../utils/cn';

interface ModalProps {
  isOpen: boolean;
  title?: string;
  children: ReactNode;
  footer?: ReactNode;
  onClose?: () => void;
  className?: string;
}

import { createPortal } from 'react-dom';

export function Modal({ isOpen, title, children, footer, onClose, className }: ModalProps) {
  if (!isOpen) return null;

  return createPortal(
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4 animate-modal-backdrop">
      <div
        className={cn(
          'rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] flex flex-col animate-modal-panel',
          className
        )}
        style={{ backgroundColor: 'var(--color-surface-primary)' }}
        onClick={(e) => e.stopPropagation()} // Prevent closing when clicking content
      >
        {title && (
          <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between flex-shrink-0">
            <h3 className="text-lg font-semibold text-gray-900">{title}</h3>
            {onClose && (
              <button
                onClick={onClose}
                className="text-gray-400 hover:text-gray-600 p-1 rounded-full hover:bg-gray-100 transition-colors"
                aria-label="Close modal"
              >
                <span className="text-xl leading-none">&times;</span>
              </button>
            )}
          </div>
        )}
        <div className="p-6 overflow-y-auto">{children}</div>
        {footer && <div className="px-6 py-4 border-t border-gray-200 flex-shrink-0">{footer}</div>}
      </div>

      {/* Backdrop click to close */}
      <div className="absolute inset-0 -z-10" onClick={onClose}></div>
    </div>,
    document.body
  );
}
