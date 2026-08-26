/**
 * GramSakhi design tokens — aligned with web Material 3 palette (globals.css).
 */
export const colors = {
  primary: '#082519',
  onPrimary: '#ffffff',
  primaryContainer: '#1f3b2e',
  onPrimaryContainer: '#87a594',
  secondary: '#476645',
  onSecondary: '#ffffff',
  secondaryContainer: '#c6e9bf',
  onSecondaryContainer: '#4b6a49',
  tertiary: '#172400',
  tertiaryContainer: '#283b00',
  onTertiaryContainer: '#85aa3d',
  background: '#fff8f0',
  onBackground: '#1e1b13',
  surface: '#fff8f0',
  onSurface: '#1e1b13',
  onSurfaceVariant: '#424844',
  surfaceContainerLow: '#fbf3e5',
  surfaceContainer: '#f5ede0',
  surfaceContainerHigh: '#efe7da',
  surfaceContainerHighest: '#e9e2d5',
  surfaceContainerLowest: '#ffffff',
  surfaceVariant: '#e9e2d5',
  outline: '#727974',
  outlineVariant: '#c2c8c2',
  error: '#ba1a1a',
  errorContainer: '#ffdad6',
  onErrorContainer: '#93000a',
  forest: '#173A32',
  leaf: '#82A95A',
  cream: '#E7E2D3',
} as const;

export type ColorToken = keyof typeof colors;
