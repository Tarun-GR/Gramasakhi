'use client';

import { useUiStore } from '@/stores/ui-store';
import { useChatStore } from '@/stores/chat-store';
import { useLanguageStore } from '@/stores/language-store';
import { useDialogA11y } from '@/lib/hooks/use-dialog-a11y';
import {
  X,
  Sprout,
  Plus,
  MessageSquarePlus,
  FolderArchive,
  FileCheck2,
  MessageSquare,
} from 'lucide-react';

export function MobileSidebar() {
  const { isMobileSidebarOpen, closeMobileSidebar, openModal, userProfile } = useUiStore();
  const { conversations, selectConversation, newConversation } = useChatStore();
  const { getTranslation } = useLanguageStore();
  const t = getTranslation();
  const dialogRef = useDialogA11y(isMobileSidebarOpen, closeMobileSidebar);

  if (!isMobileSidebarOpen) return null;

  return (
    <div className="fixed inset-0 z-50 md:hidden flex select-none">
      <div
        role="presentation"
        onClick={closeMobileSidebar}
        className="fixed inset-0 bg-black/60 backdrop-blur-sm transition-opacity"
      />

      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="Navigation menu"
        tabIndex={-1}
        className="relative w-4/5 max-w-xs bg-surface-container-low h-full flex flex-col shadow-2xl z-10 border-r border-surface-variant outline-none"
      >
        <div className="p-5 flex items-center justify-between border-b border-surface-variant/40">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-primary-container text-on-primary-container flex items-center justify-center">
              <Sprout className="w-5 h-5 text-tertiary-fixed-dim" />
            </div>
            <div>
              <h2 className="text-base font-bold text-primary">GramSakhi</h2>
              <p className="text-[11px] text-on-surface-variant">{t.appSubtitle}</p>
            </div>
          </div>
          <button type="button" onClick={closeMobileSidebar} aria-label="Close navigation menu" className="p-1 rounded-full text-on-surface-variant hover:bg-surface-variant focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/30">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-4">
          <button
            type="button"
            onClick={() => {
              openModal('explore_schemes');
              closeMobileSidebar();
            }}
            className="w-full bg-primary text-on-primary font-bold text-xs py-3 px-4 rounded-full flex items-center justify-center gap-2 shadow-sm"
          >
            <Plus className="w-4 h-4" />
            <span>{t.exploreSchemes}</span>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto custom-scrollbar px-3 space-y-1">
          <button
            type="button"
            onClick={() => {
              newConversation();
              closeMobileSidebar();
            }}
            className="w-full flex items-center gap-3 px-4 py-3 text-primary font-bold bg-secondary-container rounded-xl text-left"
          >
            <MessageSquarePlus className="w-5 h-5 text-secondary" />
            <span className="text-xs font-semibold">{t.newChat}</span>
          </button>

          <button
            type="button"
            onClick={() => {
              openModal('eligibility_quiz');
              closeMobileSidebar();
            }}
            className="w-full flex items-center gap-3 px-4 py-2.5 text-on-surface-variant hover:bg-surface-variant rounded-xl text-left"
          >
            <FileCheck2 className="w-4 h-4 text-secondary" />
            <span className="text-xs font-medium">{t.eligibilityChecker}</span>
          </button>

          <button
            type="button"
            onClick={() => {
              openModal('saved_docs');
              closeMobileSidebar();
            }}
            className="w-full flex items-center gap-3 px-4 py-2.5 text-on-surface-variant hover:bg-surface-variant rounded-xl text-left"
          >
            <FolderArchive className="w-4 h-4" />
            <span className="text-xs font-medium">{t.savedDocs}</span>
          </button>

          <div className="pt-4 pb-1 px-4">
            <p className="text-[10px] font-bold text-on-surface-variant uppercase tracking-wider">
              {t.recentConsultations}
            </p>
          </div>

          {conversations.map((conv) => (
            <button
              key={conv.id}
              type="button"
              onClick={() => {
                selectConversation(conv.id);
                closeMobileSidebar();
              }}
              className="w-full flex items-center gap-2 px-4 py-2 text-on-surface-variant hover:bg-surface-variant rounded-lg text-left text-xs"
            >
              <MessageSquare className="w-3.5 h-3.5 shrink-0" />
              <span className="truncate">{conv.title}</span>
            </button>
          ))}
        </div>

        <div className="mt-auto border-t border-surface-variant p-3 bg-surface-container-low">
          <p className="text-xs font-bold text-primary px-2">{userProfile.name}</p>
        </div>
      </div>
    </div>
  );
}
