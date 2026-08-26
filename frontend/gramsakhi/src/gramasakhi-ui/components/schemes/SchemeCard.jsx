'use client';

import { useChatStore } from '@/stores/chat-store';
import { useLanguageStore } from '@/stores/language-store';
import { Sprout, ChevronRight } from 'lucide-react';

/** Displays backend-detected scheme name only — no hard-coded catalogue. */
export function SchemeCard({ scheme }) {
  const { sendMessage } = useChatStore();
  const { currentLanguage, getTranslation } = useLanguageStore();
  const t = getTranslation();

  if (!scheme?.name) return null;

  const askAbout = () => {
    const prompts = {
      en: `Tell me more about ${scheme.name} — eligibility, documents, and how to apply.`,
      kn: `${scheme.name} ಬಗ್ಗೆ ಹೆಚ್ಚಿನ ಮಾಹಿತಿ ನೀಡಿ — ಅರ್ಹತೆ, ದಾಖಲೆಗಳು ಮತ್ತು ಅರ್ಜಿ ಹಂತಗಳು.`,
      hi: `${scheme.name} के बारे में अधिक बताएं — पात्रता, दस्तावेज़ और आवेदन प्रक्रिया।`,
    };
    sendMessage(prompts[currentLanguage] || prompts.en, currentLanguage);
  };

  return (
    <div className="bg-surface-container rounded-[28px] p-5 shadow-ambient border border-surface-variant max-w-md w-full mt-4">
      <div className="flex items-start justify-between mb-3">
        <div>
          <span className="inline-block px-3 py-1 bg-tertiary-fixed-dim text-on-tertiary-fixed font-semibold text-xs rounded-full mb-2">
            Detected scheme
          </span>
          <h3 className="text-lg font-bold text-primary tracking-tight">{scheme.name}</h3>
        </div>
        <div className="w-10 h-10 rounded-full bg-secondary-container flex items-center justify-center shrink-0">
          <Sprout className="w-6 h-6 text-secondary" />
        </div>
      </div>

      <button
        type="button"
        onClick={askAbout}
        className="w-full bg-primary text-on-primary py-2.5 px-4 rounded-full font-bold text-xs hover:bg-surface-tint transition-all flex items-center justify-center gap-1"
      >
        <span>{t.applyNow || 'Learn more'}</span>
        <ChevronRight className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}







