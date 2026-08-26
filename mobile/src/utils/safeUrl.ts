import { Linking } from 'react-native';

/** Allow only http(s) links — mirrors web GramSakhi safeHttpUrl behavior. */
export function safeHttpUrl(url: string | null | undefined): string | null {
  if (!url || typeof url !== 'string') return null;
  try {
    const parsed = new URL(url.trim());
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
      return parsed.href;
    }
  } catch {
    // ignore invalid URLs
  }
  return null;
}

export function openSafeHttpUrl(url: string): boolean {
  const safe = safeHttpUrl(url);
  if (!safe) return false;
  void Linking.openURL(safe);
  return true;
}
