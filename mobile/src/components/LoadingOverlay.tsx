import { ActivityIndicator, Modal, StyleSheet, Text, View } from 'react-native';
import { colors, spacing, typography } from '../theme';

interface LoadingOverlayProps {
  visible: boolean;
  message?: string;
}

export function LoadingOverlay({ visible, message = 'Loading…' }: LoadingOverlayProps) {
  return (
    <Modal transparent visible={visible} animationType="fade" accessibilityViewIsModal>
      <View style={styles.backdrop}>
        <View style={styles.card} accessibilityRole="progressbar" accessibilityLabel={message}>
          <ActivityIndicator size="large" color={colors.secondary} />
          <Text style={styles.message}>{message}</Text>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(8, 37, 25, 0.35)',
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing.lg,
  },
  card: {
    backgroundColor: colors.surfaceContainerLowest,
    borderRadius: 24,
    paddingVertical: spacing.lg,
    paddingHorizontal: spacing.xl,
    alignItems: 'center',
    minWidth: 180,
    shadowColor: colors.primary,
    shadowOpacity: 0.12,
    shadowRadius: 16,
    shadowOffset: { width: 0, height: 8 },
    elevation: 6,
  },
  message: {
    ...typography.caption,
    marginTop: spacing.md,
    color: colors.onSurface,
  },
});
