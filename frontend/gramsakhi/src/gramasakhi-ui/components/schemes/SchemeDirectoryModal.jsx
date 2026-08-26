'use client';

import { useUiStore } from '@/stores/ui-store';
import { useLanguageStore } from '@/stores/language-store';
import { useChatStore } from '@/stores/chat-store';
import { useDialogA11y } from '@/lib/hooks/use-dialog-a11y';
import { X, Compass, MessageSquarePlus } from 'lucide-react';

export function SchemeDirectoryModal() {
  const { activeModal, closeModal } = useUiStore();
  const { getTranslation } = useLanguageStore();
  const { newConversation } = useChatStore();
  const t = getTranslation();
  const isOpen = activeModal === 'explore_schemes';
  const dialogRef = useDialogA11y(isOpen, closeModal);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="scheme-directory-title"
        tabIndex={-1}
        className="bg-surface-container-lowest w-full max-w-lg rounded-[32px] shadow-2xl flex flex-col overflow-hidden border border-surface-variant animate-fadeIn outline-none"
      >
        <div className="p-6 border-b border-surface-variant flex items-center justify-between bg-surface-container-low">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-secondary-container text-on-secondary-container flex items-center justify-center">
              <Compass className="w-6 h-6 text-secondary" />
            </div>
            <div>
              <h2 id="scheme-directory-title" className="text-xl text-primary font-bold">{t.exploreSchemes}</h2>
              <p className="text-xs text-on-surface-variant">Ask GramSakhi about any scheme</p>
            </div>
          </div>
          <button
            type="button"
            onClick={closeModal}
            aria-label="Close dialog"
            className="w-9 h-9 rounded-full hover:bg-surface-variant flex items-center justify-center text-on-surface-variant focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 space-y-4 text-sm text-on-surface-variant leading-relaxed">
          <p>
            GramSakhi finds schemes from verified government documents and official portals.
            Describe your situation in chat — for example agriculture support, housing, health
            coverage, or women&apos;s welfare — and GramSakhi will answer from real sources.
          </p>
          <button
            type="button"
            onClick={() => {
              closeModal();
              newConversation();
            }}
            className="w-full flex items-center justify-center gap-2 bg-primary text-on-primary font-bold py-3 px-5 rounded-full hover:bg-surface-tint transition-all"
          >
            <MessageSquarePlus className="w-5 h-5" />
            {t.newChat}
          </button>
        </div>
      </div>
    </div>
  );
}
