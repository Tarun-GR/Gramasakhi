import { ActivityIndicator, Platform, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useLanguage } from '../../context/LanguageContext';
import { colors, radii, spacing, touchTargetMin, typography } from '../../theme';
import type { VoiceInputPhase } from '../../types/voice';

interface MessageComposerProps {
  text: string;
  onChangeText: (value: string) => void;
  onSend: () => void;
  disabled?: boolean;
  isGenerating?: boolean;
  voicePhase?: VoiceInputPhase;
  voiceError?: string | null;
  voicePreview?: string | null;
  isVoiceProcessing?: boolean;
  isRecording?: boolean;
  recordingDurationMillis?: number;
  onVoicePress?: () => void;
  onVoiceStop?: () => void;
  onVoiceCancel?: () => void;
  onOpenVoiceSettings?: () => void;
}

function formatDuration(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  const mins = Math.floor(totalSec / 60);
  const secs = totalSec % 60;
  return `${mins}:${secs < 10 ? '0' : ''}${secs}`;
}

export function MessageComposer({
  text,
  onChangeText,
  onSend,
  disabled,
  isGenerating,
  voicePhase = 'idle',
  voiceError,
  voicePreview,
  isVoiceProcessing,
  isRecording,
  recordingDurationMillis = 0,
  onVoicePress,
  onVoiceStop,
  onVoiceCancel,
  onOpenVoiceSettings,
}: MessageComposerProps) {
  const { t } = useLanguage();
  const canSend = Boolean(text.trim()) && !disabled && !isGenerating && !isVoiceProcessing;
  const micDisabled = disabled || isGenerating || isVoiceProcessing;

  const voiceAccessibilityLabel = isRecording
    ? t('composer.stopRecordingA11y')
    : isVoiceProcessing
      ? t('composer.transcribingA11y')
      : t('composer.startVoiceA11y');

  return (
    <View style={styles.wrap}>
      {voicePreview ? (
        <View style={styles.preview} accessibilityLiveRegion="polite">
          <Text style={styles.previewLabel}>{t('composer.voiceTranscribed')}</Text>
          <Text style={styles.previewText}>{voicePreview}</Text>
        </View>
      ) : null}

      {voiceError ? (
        <View style={styles.voiceErrorBox} accessibilityRole="alert">
          <Text style={styles.voiceErrorText}>{voiceError}</Text>
          {voiceError.includes('settings') && onOpenVoiceSettings ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={t('composer.openSettings')}
              onPress={onOpenVoiceSettings}
            >
              <Text style={styles.settingsLink}>{t('composer.openSettings')}</Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}

      {isRecording ? (
        <View
          style={styles.recordingRow}
          accessibilityRole="alert"
          accessibilityLabel={t('composer.recording')}
        >
          <MaterialCommunityIcons name="record-circle" size={18} color={colors.error} />
          <Text style={styles.recordingText}>
            {t('composer.recording')} {formatDuration(recordingDurationMillis)}
          </Text>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={t('composer.cancelRecordingA11y')}
            onPress={onVoiceCancel}
            style={styles.cancelBtn}
          >
            <Text style={styles.cancelText}>{t('composer.cancel')}</Text>
          </Pressable>
        </View>
      ) : null}

      <View style={styles.composer}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={voiceAccessibilityLabel}
          accessibilityState={{ disabled: micDisabled, busy: isVoiceProcessing }}
          disabled={micDisabled}
          onPress={isRecording ? onVoiceStop : onVoicePress}
          style={[
            styles.micBtn,
            isRecording && styles.micBtnActive,
            micDisabled && styles.micBtnDisabled,
          ]}
        >
          {isVoiceProcessing ? (
            <ActivityIndicator size="small" color={colors.secondary} />
          ) : (
            <MaterialCommunityIcons
              name={isRecording ? 'stop-circle' : 'microphone'}
              size={22}
              color={isRecording ? colors.onErrorContainer : colors.secondary}
            />
          )}
        </Pressable>

        <TextInput
          accessibilityLabel={t('composer.inputA11y')}
          placeholder={
            isVoiceProcessing
              ? t('composer.transcribingPlaceholder')
              : t('composer.placeholder')
          }
          placeholderTextColor={colors.outline}
          value={text}
          onChangeText={onChangeText}
          editable={!disabled && !isGenerating && !isVoiceProcessing && !isRecording}
          multiline
          maxLength={8000}
          style={styles.input}
          returnKeyType="default"
          blurOnSubmit={false}
        />

        <Pressable
          accessibilityRole="button"
          accessibilityLabel={t('composer.sendA11y')}
          accessibilityState={{ disabled: !canSend }}
          disabled={!canSend}
          onPress={onSend}
          style={[styles.sendBtn, !canSend && styles.sendBtnDisabled]}
        >
          <MaterialCommunityIcons
            name="send"
            size={22}
            color={canSend ? colors.onPrimary : colors.outline}
          />
        </Pressable>
      </View>

      <Text style={styles.disclaimer}>{t('composer.disclaimer')}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    paddingHorizontal: spacing.md,
    paddingTop: spacing.sm,
    paddingBottom: Platform.OS === 'ios' ? spacing.sm : spacing.md,
    backgroundColor: colors.surface,
    borderTopWidth: 1,
    borderTopColor: colors.surfaceVariant,
  },
  preview: {
    backgroundColor: colors.surfaceContainerLow,
    borderRadius: radii.lg,
    padding: spacing.sm,
    marginBottom: spacing.sm,
    borderWidth: 1,
    borderColor: colors.surfaceVariant,
  },
  previewLabel: {
    ...typography.caption,
    fontWeight: '700',
    color: colors.secondary,
    marginBottom: 2,
  },
  previewText: {
    ...typography.body,
    color: colors.onSurface,
  },
  voiceErrorBox: {
    backgroundColor: colors.errorContainer,
    borderRadius: radii.md,
    padding: spacing.sm,
    marginBottom: spacing.sm,
  },
  voiceErrorText: {
    ...typography.caption,
    color: colors.onErrorContainer,
  },
  settingsLink: {
    ...typography.caption,
    color: colors.secondary,
    fontWeight: '700',
    marginTop: spacing.xs,
  },
  recordingRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.sm,
    paddingHorizontal: spacing.xs,
  },
  recordingText: {
    ...typography.caption,
    color: colors.error,
    fontWeight: '700',
    flex: 1,
  },
  cancelBtn: {
    minHeight: touchTargetMin,
    justifyContent: 'center',
    paddingHorizontal: spacing.xs,
  },
  cancelText: {
    ...typography.caption,
    color: colors.onSurfaceVariant,
    fontWeight: '600',
  },
  composer: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: spacing.sm,
    backgroundColor: colors.surfaceContainerHigh,
    borderRadius: radii.xl,
    borderWidth: 1,
    borderColor: colors.surfaceVariant,
    paddingLeft: spacing.xs,
    paddingRight: spacing.xs,
    paddingVertical: spacing.xs,
    minHeight: touchTargetMin,
  },
  micBtn: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: 'center',
    justifyContent: 'center',
  },
  micBtnActive: {
    backgroundColor: colors.errorContainer,
  },
  micBtnDisabled: {
    opacity: 0.5,
  },
  input: {
    flex: 1,
    ...typography.body,
    color: colors.onSurface,
    maxHeight: 120,
    paddingVertical: spacing.sm,
  },
  sendBtn: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sendBtnDisabled: {
    backgroundColor: colors.surfaceContainer,
  },
  disclaimer: {
    ...typography.caption,
    fontSize: 10,
    color: colors.outline,
    textAlign: 'center',
    marginTop: spacing.xs,
  },
});
