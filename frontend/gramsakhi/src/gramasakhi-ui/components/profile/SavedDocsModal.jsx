'use client';

import { useUiStore } from '@/stores/ui-store';
import { useDialogA11y } from '@/lib/hooks/use-dialog-a11y';
import { X, FolderArchive } from 'lucide-react';

/** Document vault UI — informational only; no persisted citizen documents on server yet. */
export function SavedDocsModal() {
  const { activeModal, closeModal } = useUiStore();
  const isOpen = activeModal === 'saved_docs';
  const dialogRef = useDialogA11y(isOpen, closeModal);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="saved-docs-title"
        tabIndex={-1}
        className="bg-surface-container-lowest w-full max-w-md rounded-[32px] shadow-2xl flex flex-col overflow-hidden border border-surface-variant outline-none"
      >
        <div className="p-6 border-b border-surface-variant flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-secondary-container flex items-center justify-center">
              <FolderArchive className="w-5 h-5 text-secondary" />
            </div>
            <div>
              <h2 id="saved-docs-title" className="text-lg text-primary font-bold">Documents</h2>
              <p className="text-xs text-on-surface-variant">From verified chat sources</p>
            </div>
          </div>
          <button type="button" onClick={closeModal} aria-label="Close dialog" className="text-on-surface-variant focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 rounded-full p-1">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="p-6 text-sm text-on-surface-variant leading-relaxed">
          <p>
            Official scheme documents and PDF links appear in each assistant reply when the
            backend retrieves them from government sources. GramSakhi does not store a
            permanent document vault for citizens.
          </p>
        </div>
      </div>
    </div>
  );
}
