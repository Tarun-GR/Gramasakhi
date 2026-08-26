import { Pressable, StyleSheet, Text, View } from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import type { ChatSource } from '../../types/chat';
import { useLanguage } from '../../context/LanguageContext';
import { colors, radii, spacing, typography } from '../../theme';
import { openSafeHttpUrl, safeHttpUrl } from '../../utils/safeUrl';

interface SourceListProps {
  sources: ChatSource[];
}

export function SourceList({ sources }: SourceListProps) {
  const { t } = useLanguage();

  if (!sources.length) return null;

  return (
    <View style={styles.wrap} accessibilityLabel={t('sources.title')}>
      <Text style={styles.title}>{t('sources.title')}</Text>
      {sources.map((source) => {
        const href = safeHttpUrl(source.url);
        const canOpen = Boolean(href);
        return (
        <Pressable
          key={source.id}
          accessibilityRole="link"
          accessibilityLabel={`Open source ${source.title}`}
          disabled={!canOpen}
          onPress={() => {
            if (href) openSafeHttpUrl(href);
          }}
          style={[styles.item, !canOpen && styles.itemDisabled]}
        >
          <MaterialCommunityIcons
            name={source.is_pdf ? 'file-pdf-box' : 'link-variant'}
            size={16}
            color={colors.secondary}
          />
          <View style={styles.textWrap}>
            <Text style={styles.itemTitle} numberOfLines={2}>
              {source.title}
            </Text>
            {source.department ? (
              <Text style={styles.dept} numberOfLines={1}>
                {source.department}
              </Text>
            ) : null}
          </View>
        </Pressable>
      );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    marginTop: spacing.md,
    gap: spacing.xs,
  },
  title: {
    ...typography.caption,
    fontWeight: '700',
    color: colors.onSurfaceVariant,
    textTransform: 'uppercase',
  },
  item: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.sm,
    backgroundColor: colors.surfaceContainerLowest,
    borderRadius: radii.md,
    padding: spacing.sm,
    borderWidth: 1,
    borderColor: colors.surfaceVariant,
  },
  textWrap: {
    flex: 1,
    minWidth: 0,
  },
  itemTitle: {
    ...typography.caption,
    color: colors.secondary,
    fontWeight: '600',
  },
  dept: {
    fontSize: 11,
    color: colors.onSurfaceVariant,
    marginTop: 2,
  },
  itemDisabled: {
    opacity: 0.55,
  },
});
