import { StyleSheet, Text, View } from 'react-native';
import type { ChatMessage } from '../../types/chat';
import { colors, radii, spacing, typography } from '../../theme';

interface UserMessageProps {
  message: ChatMessage;
}

export function UserMessage({ message }: UserMessageProps) {
  return (
    <View style={styles.row} accessibilityLabel="Your message">
      <View style={styles.bubble}>
        <Text style={styles.text}>{message.content}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    alignItems: 'flex-end',
    marginBottom: spacing.md,
  },
  bubble: {
    maxWidth: '88%',
    backgroundColor: colors.primary,
    borderRadius: radii.xl,
    borderBottomRightRadius: radii.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  text: {
    ...typography.body,
    color: colors.onPrimary,
  },
});
