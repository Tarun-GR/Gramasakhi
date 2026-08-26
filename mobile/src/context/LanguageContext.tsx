import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import {
  DEFAULT_UI_LANGUAGE,
  LANGUAGE_OPTIONS,
  type LanguageOption,
  type UiLanguageCode,
} from '../constants/language';
import {
  loadLanguagePreference,
  saveLanguagePreference,
} from '../storage/languagePreference';
import { createTranslator, type Translator } from '../i18n/strings';
import { normalizeUiLanguage } from '../utils/language';

interface LanguageContextValue {
  language: UiLanguageCode;
  options: readonly LanguageOption[];
  ready: boolean;
  setLanguage: (code: string) => void;
  /** Look up a UI string for the current language (English fallback). */
  t: Translator;
}

const LanguageContext = createContext<LanguageContextValue | null>(null);

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<UiLanguageCode>(DEFAULT_UI_LANGUAGE);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const saved = await loadLanguagePreference();
      if (!cancelled && saved) {
        setLanguageState(saved);
      }
      if (!cancelled) setReady(true);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const setLanguage = useCallback((code: string) => {
    const next = normalizeUiLanguage(code, DEFAULT_UI_LANGUAGE);
    if (!next) return;
    setLanguageState((prev) => {
      if (prev === next) return prev;
      void saveLanguagePreference(next);
      return next;
    });
  }, []);

  const value = useMemo(
    () => ({
      language,
      options: LANGUAGE_OPTIONS,
      ready,
      setLanguage,
      t: createTranslator(language),
    }),
    [language, ready, setLanguage]
  );

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useLanguage(): LanguageContextValue {
  const ctx = useContext(LanguageContext);
  if (!ctx) throw new Error('useLanguage must be used within LanguageProvider');
  return ctx;
}

/**
 * Non-throwing variant for components that may render outside the provider
 * (e.g. the error-boundary fallback). Returns null when no provider is present.
 */
export function useOptionalLanguage(): LanguageContextValue | null {
  return useContext(LanguageContext);
}
