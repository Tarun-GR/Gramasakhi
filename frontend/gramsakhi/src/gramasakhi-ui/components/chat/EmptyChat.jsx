'use client';

import { useLanguageStore } from '@/stores/language-store';
import { useChatStore } from '@/stores/chat-store';
import { Sprout, Home, HeartHandshake, Stethoscope, Sparkles, CheckCircle2, SunMedium, GraduationCap, Users } from 'lucide-react';

export function EmptyChat() {
  const { getTranslation, currentLanguage } = useLanguageStore();
  const { sendMessage } = useChatStore();
  const t = getTranslation();

  const handlePromptClick = (prompt) => {
    sendMessage(prompt, currentLanguage);
  };

  return (
    <div className="text-center py-6 md:py-10 space-y-6">
      {/* Central Spa Icon & Verified Badge matching Stitch design */}
      <div className="w-20 h-20 bg-surface-container-high rounded-full mx-auto flex items-center justify-center shadow-ambient border border-surface-variant/50 relative group">
        <Sprout className="w-10 h-10 text-primary transform group-hover:scale-110 transition-transform" />
        <div className="absolute -bottom-1 -right-1 w-6 h-6 rounded-full bg-secondary-container text-on-secondary-container flex items-center justify-center shadow-sm">
          <CheckCircle2 className="w-4 h-4 text-secondary" />
        </div>
      </div>

      <div className="space-y-2">
        <h2 className="text-2xl md:text-4xl text-primary font-bold tracking-tight">
          {t.howCanIHelp}
        </h2>
        <p className="text-sm md:text-base text-on-surface-variant max-w-lg mx-auto leading-relaxed">
          {t.welcomeDesc}
        </p>
      </div>

      {/* Suggested Prompt Cards (Stitch Grid Layout) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5 mt-6 text-left max-w-2xl mx-auto">
        <button
          onClick={() => handlePromptClick(t.samplePrompts.farmer)}
          className="p-4 rounded-2xl border border-surface-variant hover:bg-surface-container hover:border-secondary hover:shadow-md transition-all shadow-ambient bg-surface-container-lowest group active:scale-[0.98]"
        >
          <div className="flex items-center gap-3 mb-1.5">
            <div className="w-8 h-8 rounded-lg bg-secondary-container text-on-secondary-container flex items-center justify-center shrink-0 group-hover:scale-105 transition-transform">
              <Sprout className="w-4 h-4 text-secondary" />
            </div>
            <h3 className="font-bold text-primary text-sm">{t.categories.agriculture}</h3>
          </div>
          <p className="text-xs text-on-surface-variant pl-11">
            {t.samplePrompts.farmer}
          </p>
        </button>

        <button
          onClick={() => handlePromptClick(t.samplePrompts.housing)}
          className="p-4 rounded-2xl border border-surface-variant hover:bg-surface-container hover:border-secondary hover:shadow-md transition-all shadow-ambient bg-surface-container-lowest group active:scale-[0.98]"
        >
          <div className="flex items-center gap-3 mb-1.5">
            <div className="w-8 h-8 rounded-lg bg-secondary-container text-on-secondary-container flex items-center justify-center shrink-0 group-hover:scale-105 transition-transform">
              <Home className="w-4 h-4 text-secondary" />
            </div>
            <h3 className="font-bold text-primary text-sm">{t.categories.housing}</h3>
          </div>
          <p className="text-xs text-on-surface-variant pl-11">
            {t.samplePrompts.housing}
          </p>
        </button>

        <button
          onClick={() => handlePromptClick(t.samplePrompts.women)}
          className="p-4 rounded-2xl border border-surface-variant hover:bg-surface-container hover:border-secondary hover:shadow-md transition-all shadow-ambient bg-surface-container-lowest group active:scale-[0.98]"
        >
          <div className="flex items-center gap-3 mb-1.5">
            <div className="w-8 h-8 rounded-lg bg-secondary-container text-on-secondary-container flex items-center justify-center shrink-0 group-hover:scale-105 transition-transform">
              <HeartHandshake className="w-4 h-4 text-secondary" />
            </div>
            <h3 className="font-bold text-primary text-sm">{t.categories.women}</h3>
          </div>
          <p className="text-xs text-on-surface-variant pl-11">
            {t.samplePrompts.women}
          </p>
        </button>

        <button
          onClick={() => handlePromptClick(t.samplePrompts.health)}
          className="p-4 rounded-2xl border border-surface-variant hover:bg-surface-container hover:border-secondary hover:shadow-md transition-all shadow-ambient bg-surface-container-lowest group active:scale-[0.98]"
        >
          <div className="flex items-center gap-3 mb-1.5">
            <div className="w-8 h-8 rounded-lg bg-secondary-container text-on-secondary-container flex items-center justify-center shrink-0 group-hover:scale-105 transition-transform">
              <Stethoscope className="w-4 h-4 text-secondary" />
            </div>
            <h3 className="font-bold text-primary text-sm">{t.categories.health}</h3>
          </div>
          <p className="text-xs text-on-surface-variant pl-11">
            {t.samplePrompts.health}
          </p>
        </button>
      </div>

      {/* Mobile Horizontal Quick Filter Chips (Matching Stitch Mobile Screen) */}
      <div className="md:hidden flex overflow-x-auto gap-2.5 py-2 no-scrollbar -mx-margin-mobile px-margin-mobile">
        <button
          onClick={() => handlePromptClick('Show schemes for agricultural machinery and solar pump subsidies in Karnataka')}
          className="shrink-0 bg-surface-container-low border border-surface-variant rounded-full px-3.5 py-2 text-xs font-semibold text-primary flex items-center gap-1.5 shadow-sm active:bg-secondary-container"
        >
          <SunMedium className="w-3.5 h-3.5 text-secondary" />
          <span>Solar Pumps</span>
        </button>
        <button
          onClick={() => handlePromptClick('What student education scholarships are available in Karnataka?')}
          className="shrink-0 bg-surface-container-low border border-surface-variant rounded-full px-3.5 py-2 text-xs font-semibold text-primary flex items-center gap-1.5 shadow-sm active:bg-secondary-container"
        >
          <GraduationCap className="w-3.5 h-3.5 text-secondary" />
          <span>Scholarships</span>
        </button>
        <button
          onClick={() => handlePromptClick('How to apply for Old Age Pension and Sandhya Suraksha in Karnataka?')}
          className="shrink-0 bg-surface-container-low border border-surface-variant rounded-full px-3.5 py-2 text-xs font-semibold text-primary flex items-center gap-1.5 shadow-sm active:bg-secondary-container"
        >
          <Users className="w-3.5 h-3.5 text-secondary" />
          <span>Senior Pension</span>
        </button>
      </div>
    </div>
  );
}
