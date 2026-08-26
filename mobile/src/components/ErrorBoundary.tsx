import React, { Component, ErrorInfo, ReactNode } from 'react';
import { StyleSheet, Text, View, Pressable } from 'react-native';
import { useOptionalLanguage } from '../context/LanguageContext';
import { ENGLISH_TRANSLATOR } from '../i18n/strings';
import { colors, radii, spacing, typography } from '../theme';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
}

/**
 * Localized fallback UI. Uses the optional language hook so it still renders
 * (in English) if the boundary is ever mounted outside LanguageProvider.
 */
function ErrorFallback({ onRetry }: { onRetry: () => void }) {
  const languageContext = useOptionalLanguage();
  const t = languageContext?.t ?? ENGLISH_TRANSLATOR;

  return (
    <View style={styles.container} accessibilityRole="alert">
      <Text style={styles.title}>{t('error.title')}</Text>
      <Text style={styles.body}>{t('error.body')}</Text>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={t('error.tryAgain')}
        onPress={onRetry}
        style={({ pressed }) => [styles.button, pressed && styles.buttonPressed]}
      >
        <Text style={styles.buttonText}>{t('error.tryAgain')}</Text>
      </Pressable>
    </View>
  );
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    if (__DEV__) {
      console.warn('GramSakhi UI error:', error.name, info.componentStack?.split('\n')[0]);
    }
  }

  private handleRetry = () => {
    this.setState({ hasError: false });
  };

  render() {
    if (this.state.hasError) {
      return <ErrorFallback onRetry={this.handleRetry} />;
    }
    return this.props.children;
  }
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing.lg,
  },
  title: {
    ...typography.title,
    textAlign: 'center',
    marginBottom: spacing.sm,
  },
  body: {
    ...typography.body,
    textAlign: 'center',
    marginBottom: spacing.lg,
  },
  button: {
    minHeight: 48,
    minWidth: 160,
    borderRadius: radii.pill,
    backgroundColor: colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.lg,
  },
  buttonPressed: {
    opacity: 0.88,
  },
  buttonText: {
    color: colors.onPrimary,
    fontSize: 15,
    fontWeight: '700',
  },
});
