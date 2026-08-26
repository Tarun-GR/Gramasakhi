import { create } from 'zustand';
import { LANGUAGES, TRANSLATIONS } from '@/lib/i18n/translations';

export const useLanguageStore = create((set, get) => ({
  currentLanguage: 'kn', // default to Kannada as in Stitch reference
  isTtsEnabled: true,

  setLanguage: (langCode) => {
    if (TRANSLATIONS[langCode]) {
      set({ currentLanguage: langCode });
      if (typeof window !== 'undefined') {
        localStorage.setItem('gramsakhi_lang', langCode);
      }
    }
  },

  toggleTts: () => {
    set((state) => ({ isTtsEnabled: !state.isTtsEnabled }));
  },

  getTranslation: () => {
    const lang = get().currentLanguage;
    return TRANSLATIONS[lang] || TRANSLATIONS.en;
  },

  getCurrentLanguageObj: () => {
    const lang = get().currentLanguage;
    return LANGUAGES.find((l) => l.code === lang) || LANGUAGES[0];
  },

  initLanguageFromStorage: () => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('gramsakhi_lang');
      if (saved && TRANSLATIONS[saved]) {
        set({ currentLanguage: saved });
      }
    }
  }
}));
