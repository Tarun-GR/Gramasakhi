'use client';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Bot, Loader2 } from 'lucide-react';
import { safeMarkdownUrl } from '@/lib/utils';

export function StreamingMessage({ streamText }) {
  return (
    <div className="flex items-start gap-3 md:gap-4 mb-6 animate-fadeIn">
      <div className="w-10 h-10 rounded-full bg-primary-container text-on-primary-container flex-shrink-0 flex items-center justify-center mt-1 shadow-sm ring-1 ring-secondary-container">
        <Bot className="w-5 h-5 text-tertiary-fixed-dim animate-pulse" />
      </div>

      <div className="flex-1 space-y-3 max-w-[92%] md:max-w-[85%]">
        <div className="flex items-center gap-1.5 text-xs text-secondary font-semibold">
          <Loader2 className="w-3.5 h-3.5 animate-spin text-secondary" />
          <span>Sakhi is analyzing government documents...</span>
        </div>

        <div className="bg-surface-container-low md:bg-transparent p-4 md:p-0 rounded-2xl shadow-ambient md:shadow-none border md:border-none border-surface-variant/50">
          <div className="prose prose-sm md:prose-base max-w-none text-on-surface leading-relaxed prose-headings:font-bold prose-headings:text-primary prose-strong:text-primary">
            <ReactMarkdown remarkPlugins={[remarkGfm]} urlTransform={safeMarkdownUrl}>
              {streamText || ''}
            </ReactMarkdown>
          </div>
        </div>
      </div>
    </div>
  );
}
