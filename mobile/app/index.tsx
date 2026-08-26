import { useRouter } from 'expo-router';
import { useEffect } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import { GramSakhiLogo, GramSakhiWordmark } from '../src/components/GramSakhiLogo';
import { useAuth } from '../src/context/AuthContext';
import { colors, spacing } from '../src/theme';

export default function SplashScreenRoute() {
  const router = useRouter();
  const { status } = useAuth();

  useEffect(() => {
    if (status === 'loading') return undefined;

    const timer = setTimeout(() => {
      if (status === 'authenticated') {
        router.replace('/chat');
      } else {
        router.replace('/landing');
      }
    }, 1200);

    return () => clearTimeout(timer);
  }, [status, router]);

  return (
    <View style={styles.container} accessibilityRole="none">
      <GramSakhiLogo size="lg" />
      <GramSakhiWordmark />
      {status === 'loading' ? (
        <ActivityIndicator style={styles.spinner} color={colors.secondary} accessibilityLabel="Loading" />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.md,
    paddingHorizontal: spacing.lg,
  },
  spinner: {
    marginTop: spacing.md,
  },
});
