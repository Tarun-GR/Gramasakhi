import { useEffect, useRef } from 'react';
import { ActivityIndicator, FlatList, StyleSheet, Text, View } from 'react-native';
import type { ChatMessage } from '../../types/chat';
import { AssistantMessage } from './AssistantMessage';
import { EmptyChat } from './EmptyChat';
import { GeneratingIndicator } from './GeneratingIndicator';
import { UserMessage } from './UserMessage';
import { useLanguage } from '../../context/LanguageContext';
import { colors, spacing, typography } from '../../theme';

interface MessageListProps {
  messages: ChatMessage[];
  loadingMessages: boolean;
  isGenerating: boolean;
  error: string | null;
}

export function MessageList({ messages, loadingMessages, isGenerating, error }: MessageListProps) {
  const listRef = useRef<FlatList<ChatMessage>>(null);
  const { t } = useLanguage();

  useEffect(() => {
    if (messages.length > 0 || isGenerating) {
      requestAnimationFrame(() => {
        listRef.current?.scrollToEnd({ animated: true });
      });
    }
  }, [messages.length, isGenerating, loadingMessages]);

  if (loadingMessages) {
    return (
      <View
        style={styles.center}
        accessibilityRole="progressbar"
        accessibilityLabel={t('list.loadingConversation')}
      >
        <ActivityIndicator size="large" color={colors.secondary} />
        <Text style={styles.loadingText}>{t('list.loadingConversation')}</Text>
      </View>
    );
  }

  const listHeader = error ? (
    <View style={styles.errorBanner} accessibilityRole="alert">
      <Text style={styles.errorText}>{error}</Text>
    </View>
  ) : null;

  const listFooter = isGenerating ? <GeneratingIndicator /> : null;

  if (messages.length === 0 && !isGenerating) {
    return (
      <View style={styles.flex}>
        {listHeader}
        <EmptyChat />
      </View>
    );
  }

  return (
    <FlatList
      ref={listRef}
      data={messages}
      keyExtractor={(item) => item.id}
      renderItem={({ item }) =>
        item.role === 'user' ? <UserMessage message={item} /> : <AssistantMessage message={item} />
      }
      contentContainerStyle={styles.listContent}
      keyboardShouldPersistTaps="handled"
      keyboardDismissMode="interactive"
      ListHeaderComponent={listHeader}
      ListFooterComponent={listFooter}
      maintainVisibleContentPosition={{ minIndexForVisible: 0 }}
    />
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    padding: spacing.lg,
  },
  loadingText: {
    ...typography.body,
    color: colors.onSurfaceVariant,
  },
  listContent: {
    paddingHorizontal: spacing.md,
    paddingTop: spacing.sm,
    paddingBottom: spacing.md,
  },
  errorBanner: {
    backgroundColor: colors.errorContainer,
    borderRadius: 16,
    padding: spacing.md,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: `${colors.error}44`,
  },
  errorText: {
    ...typography.caption,
    color: colors.onErrorContainer,
    fontWeight: '600',
  },
});
