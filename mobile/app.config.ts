import { ExpoConfig, ConfigContext } from 'expo/config';

/**
 * GramSakhi Android client configuration.
 * Set EXPO_PUBLIC_API_BASE_URL in .env (see .env.example).
 */
export default ({ config }: ConfigContext): ExpoConfig => ({
  ...config,
  name: 'GramSakhi',
  slug: 'gramsakhi',
  version: '1.0.0',
  orientation: 'portrait',
  scheme: 'gramsakhi',
  userInterfaceStyle: 'light',
  icon: './assets/icon.png',
  // @ts-expect-error Expo SDK 57 config typing omits splash in ExpoConfig
  splash: {
    image: './assets/icon.png',
    resizeMode: 'contain',
    backgroundColor: '#fff8f0',
  },
  ios: {
    supportsTablet: true,
    bundleIdentifier: 'com.gramsakhi.app',
  },
  android: {
    package: 'com.gramsakhi.app',
    allowBackup: false,
    softwareKeyboardLayoutMode: 'resize',
    adaptiveIcon: {
      backgroundColor: '#1f3b2e',
      foregroundImage: './assets/android-icon-foreground.png',
      backgroundImage: './assets/android-icon-background.png',
      monochromeImage: './assets/android-icon-monochrome.png',
    },
  },
  web: {
    favicon: './assets/favicon.png',
  },
  plugins: [
    'expo-router',
    'expo-secure-store',
    'expo-splash-screen',
    [
      'expo-audio',
      {
        microphonePermission:
          'GramSakhi needs microphone access so you can ask about government schemes by voice.',
      },
    ],
  ],
  experiments: {
    typedRoutes: true,
  },
  extra: {
    apiBaseUrl: process.env.EXPO_PUBLIC_API_BASE_URL ?? 'http://10.0.2.2:8000',
    eas: {
      projectId: process.env.EXPO_PUBLIC_EAS_PROJECT_ID ?? undefined,
    },
  },
});
