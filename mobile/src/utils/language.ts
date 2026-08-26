import {
  DEFAULT_UI_LANGUAGE,
  SUPPORTED_UI_LANGUAGES,
  type UiLanguageCode,
} from '../constants/language';

export function isSupportedLanguage(code?: string | null): code is UiLanguageCode {
  if (!code || typeof code !== 'string') return false;
  return (SUPPORTED_UI_LANGUAGES as readonly string[]).includes(code.toLowerCase());
}

/** Normalize to a supported UI code, or return null when invalid and no fallback applies. */
export function normalizeUiLanguage(
  code?: string | null,
  fallback?: UiLanguageCode | null
): UiLanguageCode | null {
  if (isSupportedLanguage(code)) return code.toLowerCase() as UiLanguageCode;
  if (fallback && isSupportedLanguage(fallback)) return fallback;
  if (fallback === null) return null;
  return DEFAULT_UI_LANGUAGE;
}

/**
 * TTS / playback language precedence:
 * 1. authoritative message language (if supported)
 * 2. selected mobile language
 * 3. default kn
 */
export function resolveTtsLanguage(
  messageLanguage?: string | null,
  selectedLanguage?: string | null
): UiLanguageCode {
  const fromMessage = normalizeUiLanguage(messageLanguage, null);
  if (fromMessage) return fromMessage;
  return normalizeUiLanguage(selectedLanguage, DEFAULT_UI_LANGUAGE) ?? DEFAULT_UI_LANGUAGE;
}
