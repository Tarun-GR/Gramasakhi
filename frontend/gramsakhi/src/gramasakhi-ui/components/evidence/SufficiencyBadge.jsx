'use client';

import { useLanguageStore } from '@/stores/language-store';
import { ShieldCheck, AlertCircle, HelpCircle } from 'lucide-react';

export function SufficiencyBadge({ state = 'SUPPORTED' }) {
  const { getTranslation } = useLanguageStore();
  const t = getTranslation();

  if (state === 'INSUFFICIENT_EVIDENCE') {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-error-container text-on-error-container text-xs font-semibold">
        <AlertCircle className="w-3.5 h-3.5" />
        <span>{t.insufficientEvidence}</span>
      </span>
    );
  }

  if (state === 'UNSUPPORTED') {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-surface-variant text-on-surface-variant text-xs font-semibold">
        <HelpCircle className="w-3.5 h-3.5" />
        <span>{t.unsupported}</span>
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-secondary-container text-on-secondary-container text-xs font-semibold">
      <ShieldCheck className="w-3.5 h-3.5 text-secondary" />
      <span>{t.supported}</span>
    </span>
  );
}
