// 🎨 Design Tokens — Professional SaaS Palette Refresh
// Colors updated with deeper, more sophisticated palette while keeping Design.md structure

/** Color tokens — 50 (lightest) to 950 (darkest), professional SaaS palette */
export const COLOR = {
  primary: {
    50: '#faf5ff',
    100: '#f3e8ff',
    200: '#e9d8fd',
    300: '#d8b4fe',
    400: '#c4b5fd',
    500: '#a78bfa',
    600: '#8b5cf6',
    700: '#7c3aed',
    800: '#6d28d9',
    900: '#5b21b6',
    950: '#4c1d95',
  },
  secondary: {
    50: '#f8fafc',
    100: '#f1f5f9',
    200: '#e2e8f0',
    300: '#cbd5e1',
    400: '#94a3b8',
    500: '#64748b',
    600: '#475569',
    700: '#334155',
    800: '#1e293b',
    900: '#0f172a',
    950: '#081f41',
  },
  accent: {
    50: '#f0f9ff',
    100: '#e0f9ff',
    200: '#a5f3fc',
    300: '#67e8f5',
    400: '#22d3ee',
    500: '#0891b2',
    600: '#0e4f85',
    700: '#155e7e',
    800: '#164e6a',
    900: '#1a4a5e',
  },
  neutral: {
    50: '#f8fafc',
    100: '#f1f5f9',
    200: '#e2e8f0',
    300: '#cbd5e1',
    400: '#94a3b8',
    500: '#64748b',
    600: '#475569',
    700: '#334155',
    800: '#1e293b',
    900: '#0f172a',
    950: '#0f172a',
  },
  semantic: {
    success: '#0d9488',     // Deep teal — refined, professional, not "bright green"
    warning: '#f59e0b',    // Amber — kept (standard warning)
    error: '#7f1d1d',      // Red — kept (standard error)
  },
} as const;