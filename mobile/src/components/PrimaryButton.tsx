import { ActivityIndicator, Pressable, PressableProps, StyleSheet, Text, ViewStyle } from 'react-native';
import { colors, radii, spacing, touchTargetMin } from '../theme';

type Variant = 'primary' | 'secondary' | 'ghost';

interface PrimaryButtonProps extends Omit<PressableProps, 'children' | 'style'> {
  label: string;
  variant?: Variant;
  loading?: boolean;
  buttonStyle?: ViewStyle;
}

export function PrimaryButton({
  label,
  variant = 'primary',
  loading = false,
  disabled,
  buttonStyle,
  ...rest
}: PrimaryButtonProps) {
  const isDisabled = disabled || loading;

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled: isDisabled, busy: loading }}
      disabled={isDisabled}
      style={({ pressed }) => {
        const merged: ViewStyle[] = [
          styles.base,
          styles[variant],
          ...(pressed && !isDisabled ? [styles.pressed] : []),
          ...(isDisabled ? [styles.disabled] : []),
          ...(buttonStyle ? [buttonStyle] : []),
        ];
        return merged;
      }}
      {...rest}
    >
      {loading ? (
        <ActivityIndicator color={variant === 'primary' ? colors.onPrimary : colors.secondary} />
      ) : (
        <Text style={[styles.label, variant !== 'primary' && styles.labelAlt]}>{label}</Text>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    minHeight: touchTargetMin,
    borderRadius: radii.pill,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
  },
  primary: {
    backgroundColor: colors.primary,
  },
  secondary: {
    backgroundColor: colors.secondaryContainer,
  },
  ghost: {
    backgroundColor: 'transparent',
  },
  pressed: {
    opacity: 0.9,
    transform: [{ scale: 0.98 }],
  },
  disabled: {
    opacity: 0.55,
  },
  label: {
    color: colors.onPrimary,
    fontSize: 15,
    fontWeight: '700',
  },
  labelAlt: {
    color: colors.secondary,
  },
});
