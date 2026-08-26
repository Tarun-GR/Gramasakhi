import { Pressable, StyleSheet, Text, View } from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { GramSakhiLogo } from '../GramSakhiLogo';
import { LanguageSelector } from './LanguageSelector';
import { useLanguage } from '../../context/LanguageContext';
import { colors, spacing, touchTargetMin, typography } from '../../theme';

interface ChatHeaderProps {
  title?: string;
  onOpenConversations: () => void;
  onNewConsultation: () => void;
  onSignOut: () => void;
  creatingConsultation?: boolean;
}

export function ChatHeader({
  title,
  onOpenConversations,
  onNewConsultation,
  onSignOut,
  creatingConsultation,
}: ChatHeaderProps) {
  const insets = useSafeAreaInsets();
  const { t } = useLanguage();

  return (
    <>
      <View style={[styles.wrap, { paddingTop: Math.max(insets.top, spacing.sm) }]}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={t('header.openConversations')}
        onPress={onOpenConversations}
        style={styles.iconBtn}
      >
        <MaterialCommunityIcons name="history" size={24} color={colors.secondary} />
      </Pressable>

      <View style={styles.center}>
        <GramSakhiLogo size="sm" />
        <Text style={styles.title} numberOfLines={1} accessibilityRole="header">
          {title || 'GramSakhi'}
        </Text>
      </View>

      <View style={styles.actions}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={t('header.newConsultation')}
          accessibilityState={{ disabled: creatingConsultation }}
          disabled={creatingConsultation}
          onPress={onNewConsultation}
          style={styles.iconBtn}
        >
          <MaterialCommunityIcons name="plus-circle-outline" size={24} color={colors.secondary} />
        </Pressable>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={t('header.signOut')}
          onPress={onSignOut}
          style={styles.iconBtn}
        >
          <MaterialCommunityIcons name="logout" size={22} color={colors.onSurfaceVariant} />
        </Pressable>
      </View>
      </View>
      <LanguageSelector />
    </>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.sm,
    paddingBottom: spacing.sm,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.surfaceVariant,
    gap: spacing.xs,
  },
  center: {
    flex: 1,
    alignItems: 'center',
    gap: 2,
    minWidth: 0,
  },
  title: {
    ...typography.caption,
    fontWeight: '700',
    color: colors.onSurfaceVariant,
    maxWidth: '100%',
  },
  actions: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  iconBtn: {
    minWidth: touchTargetMin,
    minHeight: touchTargetMin,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
