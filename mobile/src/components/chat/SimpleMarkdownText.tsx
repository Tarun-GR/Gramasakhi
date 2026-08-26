import { Pressable, StyleSheet, Text, View } from 'react-native';
import { colors, spacing, typography } from '../../theme';
import { openSafeHttpUrl, safeHttpUrl } from '../../utils/safeUrl';

function isUrl(part: string): boolean {
  return safeHttpUrl(part) !== null;
}

interface SimpleMarkdownTextProps {
  content: string;
}

function openUrl(url: string) {
  openSafeHttpUrl(url.replace(/[)\].,;]+$/, ''));
}

export function SimpleMarkdownText({ content }: SimpleMarkdownTextProps) {
  const paragraphs = (content || '').split(/\n{2,}/);

  return (
    <View style={styles.wrap}>
      {paragraphs.map((paragraph, pIdx) => {
        const lines = paragraph.split('\n');
        return (
          <View key={`p-${pIdx}`} style={styles.paragraph}>
            {lines.map((line, lIdx) => {
              const trimmed = line.trim();
              if (!trimmed) return null;
              const isBullet = /^[-*•]\s+/.test(trimmed);
              const isNumbered = /^\d+\.\s+/.test(trimmed);
              const display = trimmed
                .replace(/^[-*•]\s+/, '')
                .replace(/^\d+\.\s+/, '')
                .replace(/\*\*(.+?)\*\*/g, '$1')
                .replace(/\*(.+?)\*/g, '$1');

              const parts = display.split(/(https?:\/\/[^\s]+)/g);
              const lineContent = (
                <Text style={styles.text}>
                  {isBullet ? '• ' : isNumbered ? `${trimmed.match(/^\d+/)?.[0]}. ` : ''}
                  {parts.map((part, idx) => {
                    if (isUrl(part)) {
                      return (
                        <Text
                          key={`url-${pIdx}-${lIdx}-${idx}`}
                          style={styles.link}
                          onPress={() => openUrl(part)}
                          accessibilityRole="link"
                        >
                          {part}
                        </Text>
                      );
                    }
                    return <Text key={`t-${pIdx}-${lIdx}-${idx}`}>{part}</Text>;
                  })}
                </Text>
              );

              return (
                <View key={`l-${pIdx}-${lIdx}`} style={styles.line}>
                  {lineContent}
                </View>
              );
            })}
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    gap: spacing.sm,
  },
  paragraph: {
    gap: spacing.xs,
  },
  line: {
    flexDirection: 'row',
    flexWrap: 'wrap',
  },
  text: {
    ...typography.body,
    color: colors.onSurface,
    flexShrink: 1,
  },
  link: {
    color: colors.secondary,
    textDecorationLine: 'underline',
    fontWeight: '600',
  },
});
