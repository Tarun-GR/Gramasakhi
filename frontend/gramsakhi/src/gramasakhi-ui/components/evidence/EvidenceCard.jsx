'use client';

import { ExternalLink, CheckCircle2, Building2, FileText } from 'lucide-react';
import { safeHttpUrl } from '../../lib/utils';

export function EvidenceCard({ source }) {
  if (!source) return null;

  return (
    <div className="bg-surface-container-lowest hover:bg-surface-container rounded-xl p-3.5 border border-surface-variant text-xs shadow-ambient transition-all space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-1.5 text-secondary font-semibold">
          <CheckCircle2 className="w-4 h-4 text-tertiary-fixed-dim" />
          <span className="text-[11px] uppercase tracking-wider">{source.department || 'Official Government Source'}</span>
        </div>
        {source.url && (() => {
          const href = safeHttpUrl(source.url);
          if (!href) return null;
          return (
          <a
            href={href}
            target="_blank"
            rel="noreferrer"
            className="text-on-surface-variant hover:text-primary p-1 rounded hover:bg-surface-variant flex items-center gap-1 text-[11px] font-medium"
            title="Open official portal"
          >
            <span>View</span>
            <ExternalLink className="w-3 h-3" />
          </a>
          );
        })()}
      </div>

      <h5 className="font-bold text-primary text-xs leading-snug">{source.title}</h5>

      {source.excerpt && (
        <p className="text-on-surface-variant text-[11px] leading-relaxed italic border-l-2 border-secondary-container pl-2 py-0.5">
          "{source.excerpt}"
        </p>
      )}

      <div className="flex items-center gap-3 text-[10px] text-outline pt-1">
        <span className="flex items-center gap-1">
          <FileText className="w-3 h-3" />
          {source.documentType || 'Official Guidelines'}
        </span>
        {source.isOfficial && (
          <span className="text-secondary font-medium">• Verified Gazette Record</span>
        )}
      </div>
    </div>
  );
}
