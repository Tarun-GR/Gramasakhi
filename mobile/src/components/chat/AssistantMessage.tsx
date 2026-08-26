import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import type { ChatMessage } from '../../types/chat';
import { useLanguage } from '../../context/LanguageContext';
import { useTtsPlayback } from '../../context/TtsPlaybackContext';
import { resolveTtsLanguage } from '../../utils/language';
import { AssistanceMetaPanel } from './AssistanceMetaPanel';
import { SimpleMarkdownText } from './SimpleMarkdownText';
import { SourceList } from './SourceList';
import type { StringKey } from '../../i18n/strings';
import { colors, radii, spacing, typography } from '../../theme';

interface AssistantMessageProps {
  message: ChatMessage;
}

function sufficiencyLabelKey(state?: string): StringKey {
  if (state === 'SUPPORTED') return 'badge.verified';
  if (state === 'UNSUPPORTED') return 'badge.limited';
  return 'badge.partial';
}

function sufficiencyColor(state?: string): string {
  if (state === 'SUPPORTED') return colors.secondary;
  if (state === 'UNSUPPORTED') return colors.error;
  return colors.tertiary;
}

export function AssistantMessage({ message }: AssistantMessageProps) {
  const { language: selectedLanguage, t } = useLanguage();
  const sufficiency = message.grounding?.sufficiency || 'PARTIAL';
  const { activeMessageId, phase, playMessage, stopPlayback } = useTtsPlayback();
  const isThisPlaying = activeMessageId === message.id && phase === 'playing';
  const isThisLoading = activeMessageId === message.id && phase === 'loading';

  const handleSpeak = () => {
    if (isThisPlaying || isThisLoading) {
      stopPlayback();
      return;
    }
    const ttsLanguage = resolveTtsLanguage(message.language, selectedLanguage);
    void playMessage(message.id, message.content, ttsLanguage);
  };

  return (
    <View style={styles.row} accessibilityLabel="GramSakhi response">
      <View style={styles.avatar}>
        <MaterialCommunityIcons name="robot-outline" size={20} color={colors.primary} />
      </View>
      <View style={styles.content}>
        {message.grounding ? (
          <View style={styles.badgeRow}>
            <View style={[styles.badge, { borderColor: sufficiencyColor(sufficiency) }]}>
              <Text style={[styles.badgeText, { color: sufficiencyColor(sufficiency) }]}>
                {t(sufficiencyLabelKey(sufficiency))}
              </Text>
            </View>
            {message.grounding.verificationNote ? (
              <Text style={styles.note} numberOfLines={2}>
                {message.grounding.verificationNote}
              </Text>
            ) : null}
          </View>
        ) : null}

        <View style={styles.bubble}>
          <View style={styles.speakRow}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={isThisPlaying ? t('speak.stopA11y') : t('speak.playA11y')}
              accessibilityState={{ busy: isThisLoading, selected: isThisPlaying }}
              onPress={handleSpeak}
              style={styles.speakBtn}
            >
              {isThisLoading ? (
                <ActivityIndicator size="small" color={colors.secondary} />
              ) : (
                <MaterialCommunityIcons
                  name={isThisPlaying ? 'stop-circle-outline' : 'volume-high'}
                  size={18}
                  color={colors.secondary}
                />
              )}
              <Text style={styles.speakText}>{isThisPlaying ? t('speak.stop') : t('speak.listen')}</Text>
            </Pressable>
          </View>
          <SimpleMarkdownText content={message.content} />
          {message.schemes?.map((scheme) => (
            <View key={scheme.id} style={styles.schemeChip}>
              <MaterialCommunityIcons name="sprout" size={14} color={colors.secondary} />
              <Text style={styles.schemeText}>{scheme.name}</Text>
            </View>
          ))}
          <SourceList sources={message.sources || []} />
          <AssistanceMetaPanel meta={message.meta} />
        </View>
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
    marginTop: 2,
  },
  content: {
    flex: 1,
    minWidth: 0,
  },
  badgeRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    gap: spacing.xs,
    marginBottom: spacing.xs,
  },
  badge: {
    borderWidth: 1,
    borderRadius: radii.pill,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
  },
  badgeText: {
    fontSize: 11,
    fontWeight: '700',
  },
  note: {
    ...typography.caption,
    color: colors.onSurfaceVariant,
    flex: 1,
  },
  bubble: {
    backgroundColor: colors.surfaceContainerLowest,
    borderRadius: radii.xl,
    borderTopLeftRadius: radii.sm,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: `${colors.surfaceVariant}99`,
  },
  speakRow: {
    flexDirection: 'row',
    marginBottom: spacing.sm,
  },
  speakBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    backgroundColor: colors.surfaceContainerLow,
    borderRadius: radii.pill,
    paddingHorizontal: spacing.sm,
    paddingVertical: 6,
    minHeight: 36,
  },
  speakText: {
    ...typography.caption,
    color: colors.secondary,
    fontWeight: '700',
  },
  schemeChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    marginTop: spacing.sm,
    backgroundColor: colors.surfaceContainerLow,
    borderRadius: radii.lg,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    alignSelf: 'flex-start',
  },
  schemeText: {
    ...typography.caption,
    fontWeight: '700',
    color: colors.primary,
  },
});
