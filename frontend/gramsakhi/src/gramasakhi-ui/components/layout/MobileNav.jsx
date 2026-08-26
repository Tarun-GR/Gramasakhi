'use client';

import { useUiStore } from '@/stores/ui-store';
import { useChatStore } from '@/stores/chat-store';
import { MessageSquare, Grid3X3, FolderArchive, User } from 'lucide-react';

export function MobileNav() {
  const { openModal } = useUiStore();
  const { newConversation } = useChatStore();

  return (
    <nav className="fixed bottom-0 left-0 w-full z-40 flex justify-around items-center px-2 pb-safe md:hidden bg-surface/95 backdrop-blur-md shadow-[0_-4px_20px_rgba(31,59,46,0.08)] rounded-t-2xl h-16 border-t border-surface-variant/40 select-none">
      <button
        type="button"
        onClick={() => newConversation()}
        aria-label="New chat"
        className="flex flex-col items-center justify-center text-primary font-bold px-3 py-1 rounded-xl active:scale-95 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
      >
        <MessageSquare className="w-5 h-5 text-primary" />
        <span className="text-[10px] mt-0.5 font-bold">Chat</span>
      </button>

      <button
        type="button"
        onClick={() => openModal('explore_schemes')}
        aria-label="Explore schemes"
        className="flex flex-col items-center justify-center text-on-surface-variant hover:text-primary px-3 py-1 rounded-xl active:scale-95 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
      >
        <Grid3X3 className="w-5 h-5" />
        <span className="text-[10px] mt-0.5 font-medium">Schemes</span>
      </button>

      <button
        type="button"
        onClick={() => openModal('saved_docs')}
        aria-label="Saved documents"
        className="flex flex-col items-center justify-center text-on-surface-variant hover:text-primary px-3 py-1 rounded-xl active:scale-95 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
      >
        <FolderArchive className="w-5 h-5" />
        <span className="text-[10px] mt-0.5 font-medium">Docs</span>
      </button>

      <button
        type="button"
        onClick={() => openModal('user_profile')}
        aria-label="Profile and settings"
        className="flex flex-col items-center justify-center text-on-surface-variant hover:text-primary px-3 py-1 rounded-xl active:scale-95 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
      >
        <User className="w-5 h-5" />
        <span className="text-[10px] mt-0.5 font-medium">Profile</span>
      </button>
    </nav>
  );
}
