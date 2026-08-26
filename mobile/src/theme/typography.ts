import { TextStyle } from 'react-native';
import { colors } from './colors';

export const typography = {
  display: {
    fontSize: 32,
    fontWeight: '700' as TextStyle['fontWeight'],
    lineHeight: 38,
    color: colors.primary,
    letterSpacing: -0.5,
  },
  title: {
    fontSize: 24,
    fontWeight: '700' as TextStyle['fontWeight'],
    lineHeight: 30,
    color: colors.primary,
  },
  subtitle: {
    fontSize: 16,
    fontWeight: '600' as TextStyle['fontWeight'],
    lineHeight: 22,
    color: colors.onSurface,
  },
  body: {
    fontSize: 15,
    fontWeight: '400' as TextStyle['fontWeight'],
    lineHeight: 22,
    color: colors.onSurfaceVariant,
  },
  label: {
    fontSize: 11,
    fontWeight: '700' as TextStyle['fontWeight'],
    lineHeight: 16,
    letterSpacing: 1.2,
    textTransform: 'uppercase' as TextStyle['textTransform'],
    color: colors.secondary,
  },
  caption: {
    fontSize: 12,
    fontWeight: '500' as TextStyle['fontWeight'],
    lineHeight: 16,
    color: colors.onSurfaceVariant,
  },
};
