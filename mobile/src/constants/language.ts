/** Supported UI/API language codes for GramSakhi Android (A4). */

export type UiLanguageCode = 'kn' | 'hi' | 'en';

export const DEFAULT_UI_LANGUAGE: UiLanguageCode = 'kn';

export const SUPPORTED_UI_LANGUAGES: readonly UiLanguageCode[] = ['kn', 'hi', 'en'] as const;

export interface LanguageOption {
  code: UiLanguageCode;
  label: string;
}

export const LANGUAGE_OPTIONS: readonly LanguageOption[] = [
  { code: 'kn', label: 'ಕನ್ನಡ' },
  { code: 'hi', label: 'हिन्दी' },
  { code: 'en', label: 'English' },
] as const;
