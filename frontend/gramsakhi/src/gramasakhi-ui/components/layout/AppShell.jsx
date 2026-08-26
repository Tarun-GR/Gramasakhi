'use client';

import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useLanguageStore } from '@/stores/language-store';
import { useUiStore } from '@/stores/ui-store';
import { Sidebar } from './Sidebar';
import { MobileSidebar } from './MobileSidebar';
import { MobileHeader } from './MobileHeader';
import { MobileNav } from './MobileNav';
import { ChatHeader } from '@/components/chat/ChatHeader';
import { MessageList } from '@/components/chat/MessageList';
import { MessageComposer } from '@/components/chat/MessageComposer';
import { SchemeDirectoryModal } from '@/components/schemes/SchemeDirectoryModal';
import { SchemeEligibilityModal } from '@/components/schemes/SchemeEligibilityModal';
import { SavedDocsModal } from '@/components/profile/SavedDocsModal';
import { UserProfileModal } from '@/components/profile/UserProfileModal';

function BackHomeLink() {
  return (
    <Link
      to="/"
      className="text-sm font-semibold text-secondary hover:text-primary transition-colors focus:outline-none focus-visible:underline"
    >
      Back to home
    </Link>
  );
}

function TopLinkBar({ className = '' }) {
  return (
    <div
      className={`w-full flex justify-center items-center px-4 py-2.5 relative z-50 shrink-0 bg-surface ${className}`}
    >
      <BackHomeLink />
    </div>
  );
}

export function AppShell() {
  const { initLanguageFromStorage } = useLanguageStore();
  const { initProfileFromStorage } = useUiStore();

  useEffect(() => {
    initLanguageFromStorage();
    initProfileFromStorage();
  }, [initLanguageFromStorage, initProfileFromStorage]);

  return (
    <div className="bg-background text-on-background h-screen overflow-hidden flex flex-col md:flex-row antialiased font-sans select-none">
      {/* Desktop Sidebar */}
      <Sidebar />

      {/* Mobile: back link row above liquid-glass header */}
      <div className="md:hidden fixed top-0 inset-x-0 z-50 flex flex-col">
        <TopLinkBar className="border-b border-surface-variant/30" />
        <MobileHeader />
      </div>

      {/* Mobile Drawer */}
      <MobileSidebar />

      {/* Main Chat Workspace Area */}
      <main className="flex-1 md:ml-72 flex flex-col bg-surface h-full mt-28 md:mt-0 relative overflow-hidden select-text">
        {/* Desktop: back link row above liquid-glass chat header */}
        <TopLinkBar className="hidden md:flex border-b border-surface-variant/30" />
        <ChatHeader />

        {/* Scrollable Conversation Canvas */}
        <div className="flex-1 overflow-y-auto custom-scrollbar p-margin-mobile md:p-margin-desktop pb-36 md:pb-40">
          <MessageList />
        </div>

        {/* Fixed Bottom Composer */}
        <MessageComposer />
      </main>

      {/* Mobile Bottom Navigation */}
      <MobileNav />

      {/* Reusable Modals & Dialogs */}
      <SchemeDirectoryModal />
      <SchemeEligibilityModal />
      <SavedDocsModal />
      <UserProfileModal />
    </div>
  );
}
