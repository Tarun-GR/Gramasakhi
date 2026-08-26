'use client';

import { useEffect, useRef } from 'react';
import { Loader2 } from 'lucide-react';
import { useChatStore } from '@/stores/chat-store';
import { UserMessage } from './UserMessage';
import { AssistantMessage } from './AssistantMessage';
import { StreamingMessage } from './StreamingMessage';
import { EmptyChat } from './EmptyChat';

export function MessageList() {
  const { messages, isGenerating, currentStreamText, error, loadingMessages } = useChatStore();
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, currentStreamText, isGenerating, loadingMessages]);

  if (loadingMessages) {
    return (
      <div className="flex items-center justify-center py-20 text-on-surface-variant gap-2">
        <Loader2 className="w-5 h-5 animate-spin" />
        <span className="text-sm">Loading conversation…</span>
      </div>
    );
  }

  return (
    <div className="max-w-[840px] mx-auto w-full space-y-6">
      {error && (
        <div role="alert" className="p-4 rounded-2xl bg-error-container text-on-error-container text-xs md:text-sm font-medium border border-error/30 shadow-ambient flex items-center gap-2">
          <span>{error}</span>
        </div>
      )}

      {messages.length === 0 ? (
        <EmptyChat />
      ) : (
        <>
          {messages.map((msg) =>
            msg.role === 'user' ? (
              <UserMessage key={msg.id} message={msg} />
            ) : (
              <AssistantMessage key={msg.id} message={msg} />
            )
          )}

          {isGenerating && (
            <StreamingMessage streamText={currentStreamText} />
          )}
        </>
      )}

      <div ref={bottomRef} className="h-4" />
    </div>
  );
}
