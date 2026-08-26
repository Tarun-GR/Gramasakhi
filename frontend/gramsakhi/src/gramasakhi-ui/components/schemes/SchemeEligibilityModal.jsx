'use client';

import { useUiStore } from '@/stores/ui-store';
import { useChatStore } from '@/stores/chat-store';
import { useLanguageStore } from '@/stores/language-store';
import { useDialogA11y } from '@/lib/hooks/use-dialog-a11y';
import { X, Send, Sparkles } from 'lucide-react';

export function SchemeEligibilityModal() {
  const { activeModal, closeModal } = useUiStore();
  const { sendMessage } = useChatStore();
  const { currentLanguage, getTranslation } = useLanguageStore();
  const t = getTranslation();
  const isOpen = activeModal === 'eligibility_quiz';
  const dialogRef = useDialogA11y(isOpen, closeModal);

  if (!isOpen) return null;

  const prompts = {
    en: 'I want to check my eligibility for a government scheme. Please ask me the questions you need.',
    kn: 'ನಾನು ಸರ್ಕಾರಿ ಯೋಜನೆಗೆ ಅರ್ಹನಾಗಿದ್ದೇನೆಯೇ ಎಂದು ಪರಿಶೀಲಿಸಲು ಬಯಸುತ್ತೇನೆ. ಅಗತ್ಯವಾದ ಪ್ರಶ್ನೆಗಳನ್ನು ಕೇಳಿ.',
    hi: 'मैं सरकारी योजना के लिए अपनी पात्रता जांचना चाहता/चाहती हूँ। कृपया आवश्यक प्रश्न पूछें।',
  };

  const handleStart = () => {
    sendMessage(prompts[currentLanguage] || prompts.en, currentLanguage);
    closeModal();
  };

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="eligibility-modal-title"
        tabIndex={-1}
        className="bg-surface-container-lowest w-full max-w-md rounded-[32px] shadow-2xl flex flex-col overflow-hidden border border-surface-variant outline-none"
      >
        <div className="p-6 border-b border-surface-variant flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-secondary" />
            <h2 id="eligibility-modal-title" className="text-lg text-primary font-bold">{t.eligibilityChecker}</h2>
          </div>
          <button type="button" onClick={closeModal} aria-label="Close dialog" className="text-on-surface-variant focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 rounded-full p-1">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="p-6 space-y-4">
          <p className="text-sm text-on-surface-variant leading-relaxed">
            GramSakhi will ask a few questions based on official scheme rules, then evaluate
            eligibility from verified documents. No result is stored permanently.
          </p>
          <button
            type="button"
            onClick={handleStart}
            className="w-full flex items-center justify-center gap-2 bg-primary text-on-primary font-bold py-3 rounded-full"
          >
            <Send className="w-4 h-4" />
            Start in chat
          </button>
        </div>
      </div>
    </div>
  );
}
