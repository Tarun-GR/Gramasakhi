import Constants from 'expo-constants';

// Emulator-only development fallback. Never used in a production build.
const DEV_FALLBACK_ORIGIN = 'http://10.0.2.2:8000';

const IS_DEV_BUILD = typeof __DEV__ !== 'undefined' ? __DEV__ : process.env.NODE_ENV !== 'production';

const DEV_HOST_PATTERN = /(^|\/\/)(10\.0\.2\.2|localhost|127\.0\.0\.1)(:|\/|$)/i;

const raw =
  (typeof process !== 'undefined' && process.env?.EXPO_PUBLIC_API_BASE_URL) ||
  (Constants.expoConfig?.extra?.apiBaseUrl as string | undefined) ||
  (IS_DEV_BUILD ? DEV_FALLBACK_ORIGIN : '');

/** Backend origin without trailing slash. */
export function getApiOrigin(): string {
  const origin = raw.replace(/\/$/, '');
  if (!IS_DEV_BUILD) {
    if (!origin) {
      throw new Error(
        'GramSakhi API URL is not configured for this build. Set EXPO_PUBLIC_API_BASE_URL.'
      );
    }
    if (DEV_HOST_PATTERN.test(origin)) {
      throw new Error(
        'A development API URL cannot be used in a production build. Set EXPO_PUBLIC_API_BASE_URL to the production HTTPS endpoint.'
      );
    }
  }
  return origin;
}

/** FastAPI API prefix used by the existing GramSakhi backend. */
export function getApiBaseUrl(): string {
  const origin = getApiOrigin();
  return origin.endsWith('/api') ? origin : `${origin}/api`;
}
