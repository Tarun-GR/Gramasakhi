import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useLanguage } from '../../context/LanguageContext';
import { colors, radii, spacing, typography } from '../../theme';

export function GeneratingIndicator() {
  const { t } = useLanguage();

  return (
    <View
      style={styles.row}
      accessibilityRole="progressbar"
      accessibilityLabel={t('chat.generating')}
    >
      <View style={styles.avatar}>
        <MaterialCommunityIcons name="robot-outline" size={20} color={colors.primary} />
      </View>
      <View style={styles.bubble}>
        <ActivityIndicator color={colors.secondary} size="small" />
        <Text style={styles.text}>{t('chat.generating')}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  avatar: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: colors.primaryContainer,
    alignItems: 'center',
    justifyContent: 'center',
  },
  bubble: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: colors.surfaceContainerLowest,
    borderRadius: radii.xl,
    borderTopLeftRadius: radii.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderWidth: 1,
    borderColor: `${colors.surfaceVariant}99`,
  },
  text: {
    ...typography.caption,
    color: colors.onSurfaceVariant,
    fontWeight: '600',
  },
});
