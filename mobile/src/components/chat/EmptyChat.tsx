import { StyleSheet, Text, View } from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { GramSakhiLogo } from '../GramSakhiLogo';
import { useLanguage } from '../../context/LanguageContext';
import { colors, spacing, typography } from '../../theme';

export function EmptyChat() {
  const { t } = useLanguage();

  return (
    <View style={styles.wrap} accessibilityLabel={t('empty.startA11y')}>
      <GramSakhiLogo size="md" />
      <Text style={styles.title}>{t('empty.title')}</Text>
      <Text style={styles.body}>{t('empty.body')}</Text>
      <View style={styles.hints}>
        <Hint text={t('empty.hint1')} />
        <Hint text={t('empty.hint2')} />
        <Hint text={t('empty.hint3')} />
      </View>
    </View>
  );
}

function Hint({ text }: { text: string }) {
  return (
    <View style={styles.hintRow}>
      <MaterialCommunityIcons name="message-text-outline" size={16} color={colors.secondary} />
      <Text style={styles.hintText}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    alignItems: 'center',
    paddingVertical: spacing.xl,
    paddingHorizontal: spacing.md,
    gap: spacing.sm,
  },
  title: {
    ...typography.title,
    textAlign: 'center',
  },
  body: {
    ...typography.body,
    textAlign: 'center',
    color: colors.onSurfaceVariant,
    maxWidth: 360,
  },
  hints: {
    marginTop: spacing.md,
    width: '100%',
    gap: spacing.sm,
  },
  hintRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: colors.surfaceContainerLowest,
    borderRadius: 16,
    padding: spacing.sm,
    borderWidth: 1,
    borderColor: colors.surfaceVariant,
  },
  hintText: {
    ...typography.caption,
    flex: 1,
    color: colors.onSurface,
  },
});
