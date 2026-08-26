import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

/**
 * Secure key-value storage abstraction.
 * Uses expo-secure-store on native; avoids plain AsyncStorage for secrets.
 */
export async function secureGet(key: string): Promise<string | null> {
  try {
    if (Platform.OS === 'web') {
      return null;
    }
    return await SecureStore.getItemAsync(key);
  } catch {
    return null;
  }
}

export async function secureSet(key: string, value: string): Promise<void> {
  if (Platform.OS === 'web') {
    return;
  }
  await SecureStore.setItemAsync(key, value, {
    keychainAccessible: SecureStore.WHEN_UNLOCKED,
  });
}

export async function secureRemove(key: string): Promise<void> {
  if (Platform.OS === 'web') {
    return;
  }
  try {
    await SecureStore.deleteItemAsync(key);
  } catch {
    // ignore missing keys
  }
}
