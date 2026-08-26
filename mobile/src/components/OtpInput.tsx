import { useEffect, useRef, useState } from 'react';
import {
  NativeSyntheticEvent,
  StyleSheet,
  Text,
  TextInput,
  TextInputKeyPressEventData,
  View,
} from 'react-native';
import { colors, radii, spacing, typography } from '../theme';

interface OtpInputProps {
  value: string;
  onChange: (value: string) => void;
  error?: string | null;
  label?: string;
}

const DIGIT_COUNT = 6;

export function OtpInput({ value, onChange, error, label }: OtpInputProps) {
  const [digits, setDigits] = useState<string[]>(Array(DIGIT_COUNT).fill(''));
  const inputRefs = useRef<Array<TextInput | null>>([]);

  useEffect(() => {
    const next = Array(DIGIT_COUNT).fill('');
    const raw = (value || '').replace(/\D/g, '').slice(0, DIGIT_COUNT);
    for (let i = 0; i < raw.length; i += 1) next[i] = raw[i];
    setDigits(next);
  }, [value]);

  const emitChange = (nextDigits: string[]) => {
    setDigits(nextDigits);
    onChange(nextDigits.join(''));
  };

  const handleChange = (index: number, text: string) => {
    const numVal = text.replace(/\D/g, '');
    if (!numVal) {
      const next = [...digits];
      next[index] = '';
      emitChange(next);
      return;
    }

    const next = [...digits];
    if (numVal.length > 1) {
      const chunk = numVal.split('').slice(0, DIGIT_COUNT - index);
      chunk.forEach((char, offset) => {
        next[index + offset] = char;
      });
      emitChange(next);
      const target = Math.min(DIGIT_COUNT - 1, index + chunk.length);
      inputRefs.current[target]?.focus();
      return;
    }

    next[index] = numVal;
    emitChange(next);
    if (index < DIGIT_COUNT - 1) {
      inputRefs.current[index + 1]?.focus();
    }
  };

  const handleKeyPress = (index: number, e: NativeSyntheticEvent<TextInputKeyPressEventData>) => {
    if (e.nativeEvent.key !== 'Backspace') return;
    if (!digits[index] && index > 0) {
      const next = [...digits];
      next[index - 1] = '';
      emitChange(next);
      inputRefs.current[index - 1]?.focus();
      return;
    }
    const next = [...digits];
    next[index] = '';
    emitChange(next);
  };

  const hasError = Boolean(error);

  return (
    <View style={styles.wrap}>
      {label ? <Text style={styles.label}>{label}</Text> : null}
      <View
        style={styles.row}
        accessibilityLabel="One-time password input"
        accessibilityHint="Enter the 6 digit verification code"
      >
        {digits.map((digit, idx) => (
          <TextInput
            key={idx}
            ref={(el) => {
              inputRefs.current[idx] = el;
            }}
            value={digit}
            onChangeText={(text) => handleChange(idx, text)}
            onKeyPress={(e) => handleKeyPress(idx, e)}
            keyboardType="number-pad"
            maxLength={idx === 0 ? DIGIT_COUNT : 1}
            textContentType={idx === 0 ? 'oneTimeCode' : 'none'}
            autoComplete={idx === 0 ? 'sms-otp' : 'off'}
            accessibilityLabel={`OTP digit ${idx + 1} of ${DIGIT_COUNT}`}
            style={[styles.digit, hasError && styles.digitError]}
            selectTextOnFocus
          />
        ))}
      </View>
      {error ? (
        <Text style={styles.error} accessibilityRole="alert">
          {error}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    width: '100%',
  },
  label: {
    ...typography.subtitle,
    fontSize: 14,
    textAlign: 'center',
    marginBottom: spacing.sm,
    color: colors.primary,
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'center',
    gap: spacing.sm,
  },
  digit: {
    width: 44,
    height: 56,
    borderRadius: radii.lg,
    borderWidth: 1,
    borderColor: colors.surfaceVariant,
    backgroundColor: colors.surfaceContainerLowest,
    textAlign: 'center',
    fontSize: 20,
    fontWeight: '700',
    color: colors.onSurface,
  },
  digitError: {
    borderColor: colors.error,
  },
  error: {
    ...typography.caption,
    color: colors.error,
    textAlign: 'center',
    marginTop: spacing.sm,
    fontWeight: '600',
  },
});
