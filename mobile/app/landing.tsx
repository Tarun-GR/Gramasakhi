import { useRouter } from 'expo-router';
import { useEffect } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { FeatureCard } from '../src/components/FeatureCard';
import { GramSakhiLogo } from '../src/components/GramSakhiLogo';
import { PrimaryButton } from '../src/components/PrimaryButton';
import { ScreenContainer } from '../src/components/ScreenContainer';
import { useAuth } from '../src/context/AuthContext';
import { useLanguage } from '../src/context/LanguageContext';
import { useApiHealth } from '../src/hooks/useApiHealth';
import type { StringKey } from '../src/i18n/strings';
import { colors, spacing, typography } from '../src/theme';

const FEATURES: ReadonlyArray<{
  icon: 'microphone' | 'book-open-variant' | 'translate' | 'shield-check';
  titleKey: StringKey;
  descriptionKey: StringKey;
}> = [
  {
    icon: 'microphone',
    titleKey: 'feature.voiceTitle',
    descriptionKey: 'feature.voiceDesc',
  },
  {
    icon: 'book-open-variant',
    titleKey: 'feature.groundedTitle',
    descriptionKey: 'feature.groundedDesc',
  },
  {
    icon: 'translate',
    titleKey: 'feature.multilingualTitle',
    descriptionKey: 'feature.multilingualDesc',
  },
  {
    icon: 'shield-check',
    titleKey: 'feature.evidenceTitle',
    descriptionKey: 'feature.evidenceDesc',
  },
];

export default function LandingScreen() {
  const router = useRouter();
  const { status } = useAuth();
  const { t } = useLanguage();
  const { state, message, check } = useApiHealth(true);

  useEffect(() => {
    if (status === 'authenticated') {
      router.replace('/chat');
    }
  }, [status, router]);

  return (
    <ScreenContainer>
      <View style={styles.hero}>
        <GramSakhiLogo size="lg" />
        <Text style={styles.eyebrow}>{t('landing.eyebrow')}</Text>
        <Text style={styles.headline} accessibilityRole="header">
          {t('landing.headline')}
        </Text>
        <Text style={styles.lead}>{t('landing.lead')}</Text>
        <View style={styles.ctaRow}>
          <PrimaryButton label={t('landing.signIn')} onPress={() => router.push('/login')} />
          <PrimaryButton
            label={t('landing.learnMore')}
            variant="secondary"
            onPress={() => router.push('/login')}
          />
        </View>
        {state === 'error' && message ? (
          <View style={styles.banner} accessibilityRole="alert">
            <Text style={styles.bannerText}>{message}</Text>
            <PrimaryButton
              label={t('landing.retryConnection')}
              variant="ghost"
              onPress={() => void check()}
            />
          </View>
        ) : null}
      </View>

      <View style={styles.featureGrid}>
        {FEATURES.map((feature) => (
          <FeatureCard
            key={feature.titleKey}
            icon={feature.icon}
            title={t(feature.titleKey)}
            description={t(feature.descriptionKey)}
          />
        ))}
      </View>
    </ScreenContainer>
  );
}

const styles = StyleSheet.create({
  hero: {
    paddingTop: spacing.xl,
    alignItems: 'flex-start',
    marginBottom: spacing.lg,
  },
  eyebrow: {
    ...typography.label,
    marginTop: spacing.lg,
    marginBottom: spacing.sm,
  },
  headline: {
    ...typography.display,
    fontSize: 34,
    lineHeight: 40,
    maxWidth: 520,
  },
  lead: {
    ...typography.body,
    marginTop: spacing.md,
    maxWidth: 480,
  },
  ctaRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
    marginTop: spacing.lg,
  },
  banner: {
    marginTop: spacing.md,
    backgroundColor: colors.errorContainer,
    borderRadius: 16,
    padding: spacing.md,
    width: '100%',
  },
  bannerText: {
    ...typography.caption,
    color: colors.onErrorContainer,
    marginBottom: spacing.sm,
  },
  featureGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
    paddingBottom: spacing.xl,
  },
});
