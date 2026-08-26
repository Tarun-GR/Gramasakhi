import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useLanguage } from '../../context/LanguageContext';
import { colors, radii, spacing, touchTargetMin, typography } from '../../theme';

export function LanguageSelector() {
  const { language, options, setLanguage, t } = useLanguage();

  return (
    <View
      style={styles.wrap}
      accessibilityRole="radiogroup"
      accessibilityLabel={t('language.select')}
    >
      {options.map((opt) => {
        const selected = language === opt.code;
        return (
          <Pressable
            key={opt.code}
            accessibilityRole="radio"
            accessibilityLabel={selected ? `${opt.label}, selected` : opt.label}
            accessibilityState={{ selected }}
            onPress={() => setLanguage(opt.code)}
            style={[styles.chip, selected && styles.chipSelected]}
          >
            <Text style={[styles.chipText, selected && styles.chipTextSelected]}>{opt.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'center',
    gap: spacing.xs,
    paddingHorizontal: spacing.sm,
    paddingBottom: spacing.xs,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.surfaceVariant,
  },
  chip: {
    minHeight: touchTargetMin,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: radii.pill,
    borderWidth: 1,
    borderColor: colors.surfaceVariant,
    backgroundColor: colors.surfaceContainerLowest,
    justifyContent: 'center',
  },
  chipSelected: {
    borderColor: colors.secondary,
    backgroundColor: colors.surfaceContainerLow,
  },
  chipText: {
    ...typography.caption,
    fontWeight: '600',
    color: colors.onSurfaceVariant,
  },
  chipTextSelected: {
    color: colors.secondary,
    fontWeight: '700',
  },
});
