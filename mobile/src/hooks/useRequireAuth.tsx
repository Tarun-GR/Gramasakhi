import { useRouter } from 'expo-router';
import { useEffect, type ReactNode } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import { useAuth } from '../context/AuthContext';
import { colors } from '../theme';

/** Redirect unauthenticated users away from protected screens. */
export function useRequireAuth(redirectTo: '/login' | '/landing' = '/login') {
  const router = useRouter();
  const { status } = useAuth();

  useEffect(() => {
    if (status === 'unauthenticated') {
      router.replace(redirectTo);
    }
  }, [status, router, redirectTo]);

  return status;
}

export function AuthLoadingGate({ children }: { children: ReactNode }) {
  const { status } = useAuth();

  if (status === 'loading') {
    return (
      <View style={styles.loading} accessibilityRole="progressbar" accessibilityLabel="Loading session">
        <ActivityIndicator size="large" color={colors.secondary} />
      </View>
    );
  }

  if (status === 'unauthenticated') {
    return null;
  }

  return <>{children}</>;
}

const styles = StyleSheet.create({
  loading: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.background,
  },
});
