import { StyleSheet, Text, View } from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { colors, spacing } from '../theme';

interface GramSakhiLogoProps {
  size?: 'sm' | 'md' | 'lg';
}

const sizes = {
  sm: { outer: 56, icon: 28, badge: 18 },
  md: { outer: 72, icon: 36, badge: 22 },
  lg: { outer: 88, icon: 44, badge: 26 },
};

export function GramSakhiLogo({ size = 'md' }: GramSakhiLogoProps) {
  const dim = sizes[size];
  return (
    <View
      style={[styles.outer, { width: dim.outer, height: dim.outer, borderRadius: dim.outer / 2 }]}
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
    >
      <MaterialCommunityIcons name="sprout" size={dim.icon} color={colors.primary} />
      <View
        style={[
          styles.badge,
          {
            width: dim.badge,
            height: dim.badge,
            borderRadius: dim.badge / 2,
          },
        ]}
      >
        <MaterialCommunityIcons name="check-circle" size={dim.badge - 6} color={colors.secondary} />
      </View>
    </View>
  );
}

export function GramSakhiWordmark() {
  return (
    <Text style={styles.wordmark} accessibilityRole="header">
      GramSakhi
    </Text>
  );
}

const styles = StyleSheet.create({
  outer: {
    backgroundColor: colors.surfaceContainerHigh,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: `${colors.outlineVariant}99`,
    shadowColor: colors.primary,
    shadowOpacity: 0.08,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 3,
  },
  badge: {
    position: 'absolute',
    right: -2,
    bottom: -2,
    backgroundColor: colors.secondaryContainer,
    alignItems: 'center',
    justifyContent: 'center',
  },
  wordmark: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.primary,
    letterSpacing: 0.2,
  },
});
