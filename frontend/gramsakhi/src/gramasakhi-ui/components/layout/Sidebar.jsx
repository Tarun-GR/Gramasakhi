'use client';

import { useChatStore } from '@/stores/chat-store';
import { useUiStore } from '@/stores/ui-store';
import { useLanguageStore } from '@/stores/language-store';
import {
  Sprout,
  Plus,
  MessageSquarePlus,
  FolderArchive,
  FileCheck2,
  Settings,
  HelpCircle,
  ChevronRight,
  MessageSquare,
  Loader2,
} from 'lucide-react';

export function Sidebar() {
  const {
    conversations,
    activeConversationId,
    selectConversation,
    newConversation,
    loadingConversations,
  } = useChatStore();
  const { openModal, userProfile } = useUiStore();
  const { getTranslation, currentLanguage } = useLanguageStore();
  const t = getTranslation();

  return (
    <aside className="hidden md:flex flex-col h-screen fixed left-0 top-0 w-72 bg-surface-container-low border-r border-surface-variant z-40 select-none">
      <div className="p-6 flex items-center gap-3 border-b border-surface-variant/40">
        <div className="w-11 h-11 rounded-full bg-primary-container text-on-primary-container flex items-center justify-center shadow-inner ring-2 ring-secondary-container">
          <Sprout className="w-6 h-6 text-tertiary-fixed-dim" />
        </div>
        <div>
          <h1 className="text-lg text-primary font-bold tracking-tight">GramSakhi</h1>
          <p className="text-xs text-on-surface-variant font-normal">{t.appSubtitle}</p>
        </div>
      </div>

      <div className="px-4 py-4">
        <button
          type="button"
          onClick={() => openModal('explore_schemes')}
          className="w-full bg-primary hover:bg-surface-tint text-on-primary font-bold text-sm py-3 px-5 rounded-full flex items-center justify-center gap-2 transition-all duration-200 shadow-sm active:scale-95 group"
        >
          <Plus className="w-5 h-5 transition-transform group-hover:rotate-90" />
          <span>{t.exploreSchemes}</span>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto custom-scrollbar px-3 space-y-1">
        <button
          type="button"
          onClick={() => newConversation()}
          className="w-full flex items-center gap-3 px-4 py-3 text-primary font-bold bg-secondary-container rounded-xl scale-[0.99] transition-all duration-200 active:scale-95 text-left"
        >
          <MessageSquarePlus className="w-5 h-5 text-secondary" />
          <span className="text-sm font-semibold">{t.newChat}</span>
        </button>

        <button
          type="button"
          onClick={() => openModal('saved_docs')}
          className="w-full flex items-center gap-3 px-4 py-3 text-on-surface-variant hover:bg-surface-variant hover:text-primary rounded-xl transition-colors duration-200 text-left"
        >
          <FolderArchive className="w-5 h-5 text-on-surface-variant" />
          <span className="text-sm font-medium">{t.savedDocs}</span>
        </button>

        <button
          type="button"
          onClick={() => openModal('eligibility_quiz')}
          className="w-full flex items-center gap-3 px-4 py-3 text-on-surface-variant hover:bg-surface-variant hover:text-primary rounded-xl transition-colors duration-200 text-left"
        >
          <FileCheck2 className="w-5 h-5 text-secondary" />
          <span className="text-sm font-medium">{t.eligibilityChecker}</span>
        </button>

        <div className="pt-5 pb-2 px-4 flex items-center justify-between">
          <p className="text-[11px] font-bold text-on-surface-variant/80 uppercase tracking-wider">
            {t.recentConsultations}
          </p>
        </div>

        {loadingConversations && (
          <div className="flex items-center gap-2 px-4 py-2 text-on-surface-variant text-xs">
            <Loader2 className="w-4 h-4 animate-spin" />
            Loading…
          </div>
        )}

        <div className="space-y-1">
          {conversations.map((conv) => (
            <button
              key={conv.id}
              type="button"
              onClick={() => selectConversation(conv.id)}
              className={`w-full flex items-center gap-3 px-4 py-2.5 rounded-lg transition-colors duration-200 text-left group ${
                String(activeConversationId) === String(conv.id)
                  ? 'bg-surface-container text-primary font-bold border-l-2 border-secondary'
                  : 'text-on-surface-variant hover:bg-surface-variant hover:text-primary'
              }`}
            >
              <MessageSquare className="w-4 h-4 text-secondary shrink-0" />
              <span className="text-xs truncate flex-1">{conv.title}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="mt-auto border-t border-surface-variant p-3 space-y-1 bg-surface-container-low">
        <button
          type="button"
          onClick={() => openModal('user_profile')}
          className="w-full flex items-center gap-3 px-4 py-2.5 text-on-surface-variant hover:bg-surface-variant hover:text-primary rounded-lg transition-colors duration-200 text-left"
        >
          <Settings className="w-4 h-4" />
          <span className="text-sm font-medium">{t.settings}</span>
        </button>

        <button
          type="button"
          onClick={() => openModal('explore_schemes')}
          className="w-full flex items-center gap-3 px-4 py-2.5 text-on-surface-variant hover:bg-surface-variant hover:text-primary rounded-lg transition-colors duration-200 text-left"
        >
          <HelpCircle className="w-4 h-4" />
          <span className="text-sm font-medium">{t.helpCenter}</span>
        </button>

        <div
          role="button"
          tabIndex={0}
          onClick={() => openModal('user_profile')}
          onKeyDown={(e) => e.key === 'Enter' && openModal('user_profile')}
          className="mt-2 p-3 bg-surface-container hover:bg-surface-container-high rounded-xl flex items-center justify-between cursor-pointer transition-colors border border-surface-variant/60"
        >
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-primary-container text-on-primary-container flex items-center justify-center font-bold text-sm">
              C
            </div>
            <div>
              <p className="text-xs font-semibold text-primary">{userProfile.name}</p>
              {(userProfile.district || userProfile.state) && (
                <p className="text-[11px] text-on-surface-variant">
                  {[userProfile.district, userProfile.state].filter(Boolean).join(', ')}
                </p>
              )}
            </div>
          </div>
          <ChevronRight className="w-4 h-4 text-on-surface-variant" />
        </div>
      </div>
    </aside>
  );
}
