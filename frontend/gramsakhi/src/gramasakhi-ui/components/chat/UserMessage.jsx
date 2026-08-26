'use client';

import { formatDate } from '@/lib/utils';
import { FileText } from 'lucide-react';

export function UserMessage({ message }) {
  return (
    <div className="flex justify-end mb-6">
      <div className="max-w-[85%] md:max-w-[75%] bg-surface-container-high text-on-surface rounded-2xl rounded-tr-sm px-5 py-3.5 shadow-ambient border border-surface-variant/40">
        {message.attachedFileName && (
          <div className="inline-flex items-center gap-1.5 px-2.5 py-1 mb-2 rounded-lg bg-surface-container-lowest text-xs text-primary border border-secondary">
            <FileText className="w-3.5 h-3.5 text-secondary" />
            <span className="font-semibold truncate max-w-[200px]">{message.attachedFileName}</span>
          </div>
        )}
        <p className="font-sans text-sm md:text-base leading-relaxed text-on-background">
          {message.content}
        </p>
        <div className="text-[10px] text-on-surface-variant/70 text-right mt-1 font-medium">
          {formatDate(message.timestamp)}
        </div>
      </div>
    </div>
  );
}
