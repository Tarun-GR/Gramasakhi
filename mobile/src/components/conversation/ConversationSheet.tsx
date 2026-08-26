import {
  ActivityIndicator,
  Modal,
  Pressable,
  FlatList,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import type { ConversationSummary } from '../../types/chat';
import { PrimaryButton } from '../PrimaryButton';
import { useLanguage } from '../../context/LanguageContext';
import { colors, radii, spacing, touchTargetMin, typography } from '../../theme';

interface ConversationSheetProps {
  visible: boolean;
  onClose: () => void;
  conversations: ConversationSummary[];
  activeConversationId: string | null;
  loading: boolean;
  onSelect: (id: string) => void;
  onNewConsultation: () => void;
  error?: string | null;
}

function formatDate(value?: string | null): string {
  if (!value) return '';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export function ConversationSheet({
  visible,
  onClose,
  conversations,
  activeConversationId,
  loading,
  onSelect,
  onNewConsultation,
  error,
}: ConversationSheetProps) {
  const insets = useSafeAreaInsets();
  const { t } = useLanguage();

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={onClose}
    >
      <View style={[styles.container, { paddingTop: insets.top }]}>
        <View style={styles.header}>
          <Text style={styles.heading} accessibilityRole="header">
            {t('sheet.heading')}
          </Text>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={t('sheet.closeA11y')}
            onPress={onClose}
            style={styles.closeBtn}
          >
            <MaterialCommunityIcons name="close" size={24} color={colors.onSurface} />
          </Pressable>
        </View>

        <PrimaryButton
          label={t('sheet.new')}
          onPress={() => {
            onNewConsultation();
            onClose();
          }}
          buttonStyle={styles.newBtn}
        />

        {error ? (
          <View style={styles.errorBox} accessibilityRole="alert">
            <Text style={styles.errorText}>{error}</Text>
          </View>
        ) : null}

        {loading ? (
          <View style={styles.center}>
            <ActivityIndicator color={colors.secondary} />
            <Text style={styles.loadingText}>{t('sheet.loading')}</Text>
          </View>
        ) : conversations.length === 0 ? (
          <View style={styles.center}>
            <MaterialCommunityIcons name="chat-outline" size={40} color={colors.outline} />
            <Text style={styles.emptyTitle}>{t('sheet.emptyTitle')}</Text>
            <Text style={styles.emptyBody}>{t('sheet.emptyBody')}</Text>
          </View>
        ) : (
          <FlatList
            data={conversations}
            keyExtractor={(item) => item.id}
            contentContainerStyle={styles.list}
            renderItem={({ item }) => {
              const active = String(item.id) === String(activeConversationId);
              return (
                <Pressable
                  accessibilityRole="button"
                  accessibilityState={{ selected: active }}
                  accessibilityLabel={`${item.title}${active ? ', currently active' : ''}`}
                  onPress={() => {
                    onSelect(item.id);
                    onClose();
                  }}
                  style={[styles.item, active && styles.itemActive]}
                >
                  <MaterialCommunityIcons
                    name={active ? 'chat' : 'chat-outline'}
                    size={20}
                    color={active ? colors.secondary : colors.onSurfaceVariant}
                  />
                  <View style={styles.itemText}>
                    <Text style={[styles.itemTitle, active && styles.itemTitleActive]} numberOfLines={2}>
                      {item.title}
                    </Text>
                    {item.createdAt ? (
                      <Text style={styles.itemDate}>{formatDate(item.createdAt)}</Text>
                    ) : null}
                  </View>
                  {active ? (
                    <MaterialCommunityIcons name="check-circle" size={18} color={colors.secondary} />
                  ) : null}
                </Pressable>
              );
            }}
          />
        )}
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.sm,
  },
  heading: {
    ...typography.title,
    fontSize: 20,
  },
  closeBtn: {
    minWidth: touchTargetMin,
    minHeight: touchTargetMin,
    alignItems: 'center',
    justifyContent: 'center',
  },
  newBtn: {
    marginHorizontal: spacing.md,
    marginBottom: spacing.md,
  },
  list: {
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.xl,
    gap: spacing.sm,
  },
  item: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: colors.surfaceContainerLowest,
    borderRadius: radii.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.surfaceVariant,
    marginBottom: spacing.sm,
  },
  itemActive: {
    borderColor: colors.secondary,
    backgroundColor: colors.surfaceContainerLow,
  },
  itemText: {
    flex: 1,
    minWidth: 0,
  },
  itemTitle: {
    ...typography.body,
    fontWeight: '600',
    color: colors.onSurface,
  },
  itemTitleActive: {
    color: colors.primary,
  },
  itemDate: {
    ...typography.caption,
    color: colors.onSurfaceVariant,
    marginTop: 2,
  },
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing.xl,
    gap: spacing.sm,
  },
  loadingText: {
    ...typography.body,
    color: colors.onSurfaceVariant,
  },
  emptyTitle: {
    ...typography.subtitle,
    textAlign: 'center',
  },
  emptyBody: {
    ...typography.body,
    textAlign: 'center',
    color: colors.onSurfaceVariant,
  },
  errorBox: {
    marginHorizontal: spacing.md,
    marginBottom: spacing.sm,
    backgroundColor: colors.errorContainer,
    borderRadius: radii.md,
    padding: spacing.sm,
  },
  errorText: {
    ...typography.caption,
    color: colors.onErrorContainer,
  },
});
