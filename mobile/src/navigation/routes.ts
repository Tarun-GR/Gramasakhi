/** Route names for the mobile foundation (Expo Router file paths). */
export type MobileRoute =
  | '/'
  | '/landing'
  | '/login'
  | '/otp'
  | '/chat';

export const mobileRoutes = {
  splash: '/' as const,
  landing: '/landing' as const,
  login: '/login' as const,
  otp: '/otp' as const,
  chat: '/chat' as const,
};
