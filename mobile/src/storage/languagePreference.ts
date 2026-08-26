import { File, Paths } from 'expo-file-system';
import { DEFAULT_UI_LANGUAGE, type UiLanguageCode } from '../constants/language';
import { isSupportedLanguage } from '../utils/language';

const PREF_FILENAME = 'gramsakhi-language.pref';

/** App-level language preference (plain document file; not auth secure storage). */
export async function loadLanguagePreference(): Promise<UiLanguageCode | null> {
  try {
    const file = new File(Paths.document, PREF_FILENAME);
    if (!file.exists) return null;
    const text = (await file.text()).trim();
    return isSupportedLanguage(text) ? text : null;
  } catch {
    return null;
  }
}

export async function saveLanguagePreference(code: UiLanguageCode): Promise<void> {
  try {
    const file = new File(Paths.document, PREF_FILENAME);
    const stream = file.writableStream();
    const writer = stream.getWriter();
    await writer.write(new TextEncoder().encode(code));
    await writer.close();
  } catch {
    // best-effort; in-memory selection still works
  }
}

export async function clearLanguagePreference(): Promise<void> {
  try {
    const file = new File(Paths.document, PREF_FILENAME);
    if (file.exists) file.delete();
  } catch {
    // ignore
  }
}

export function defaultLanguagePreference(): UiLanguageCode {
  return DEFAULT_UI_LANGUAGE;
}
