/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/templates/**/*.html",
    "./app/static/js/**/*.js"
  ],
  theme: {
    extend: {
      colors: {
        'brand': {
          DEFAULT: '#3ECF8E',
          50: '#E6FAF2',
          100: '#CCF5E5',
          200: '#99EBCB',
          300: '#66E0B1',
          400: '#3ECF8E',
          500: '#3ECF8E',
          600: '#32A672',
          700: '#267D56',
          800: '#1A533A',
          900: '#0D2A1D',
        },
        'scale': {
          0: '#18181b',
          50: '#1f1f23',
          100: '#27272a',
          200: '#2e2e33',
          300: '#3a3a3f',
          400: '#52525b',
          500: '#71717a',
          600: '#a1a1aa',
          700: '#d4d4d8',
          800: '#e4e4e7',
          900: '#f4f4f5',
          1000: '#fafafa',
          1100: '#fcfcfc',
          1200: '#ffffff',
        },
        /* Trading Terminal Colors */
        'terminal': {
          'black': '#0a0a0c',
          'darker': '#0d0e12',
          'dark': '#12141a',
          'panel': '#161922',
          'border': '#1e222d',
          'muted': '#363a45',
          'text': '#787b86',
          'light': '#b2b5be',
          'white': '#d1d4dc',
        },
        'profit': {
          DEFAULT: '#26a69a',
          light: '#4db6ac',
          dark: '#00897b',
          glow: 'rgba(38, 166, 154, 0.3)',
        },
        'loss': {
          DEFAULT: '#ef5350',
          light: '#ff7043',
          dark: '#d32f2f',
          glow: 'rgba(239, 83, 80, 0.3)',
        },
        /* shadcn-equivalent tokens, verified against OpenAlgo's real rendered
           computed styles (not its dead legacy CSS block - see
           project_algomirror_ui_redesign_plan.md) so Button/Card/Badge/Input
           can be ported using OpenAlgo's exact utility class strings.
           <alpha-value> lets bg-primary/50 etc. work like Tailwind's own
           color opacity modifiers. */
        background: 'oklch(var(--background) / <alpha-value>)',
        foreground: 'oklch(var(--foreground) / <alpha-value>)',
        card: {
          DEFAULT: 'oklch(var(--card) / <alpha-value>)',
          foreground: 'oklch(var(--card-foreground) / <alpha-value>)',
        },
        popover: {
          DEFAULT: 'oklch(var(--popover) / <alpha-value>)',
          foreground: 'oklch(var(--popover-foreground) / <alpha-value>)',
        },
        oaprimary: {
          DEFAULT: 'oklch(var(--oa-primary) / <alpha-value>)',
          foreground: 'oklch(var(--oa-primary-foreground) / <alpha-value>)',
        },
        oasecondary: {
          DEFAULT: 'oklch(var(--oa-secondary) / <alpha-value>)',
          foreground: 'oklch(var(--oa-secondary-foreground) / <alpha-value>)',
        },
        muted: {
          DEFAULT: 'oklch(var(--muted) / <alpha-value>)',
          foreground: 'oklch(var(--muted-foreground) / <alpha-value>)',
        },
        oaaccent: {
          DEFAULT: 'oklch(var(--oa-accent) / <alpha-value>)',
          foreground: 'oklch(var(--oa-accent-foreground) / <alpha-value>)',
        },
        destructive: {
          DEFAULT: 'oklch(var(--destructive) / <alpha-value>)',
          foreground: 'oklch(var(--destructive-foreground) / <alpha-value>)',
        },
        border: 'oklch(var(--oa-border) / <alpha-value>)',
        input: 'oklch(var(--oa-input) / <alpha-value>)',
        ring: 'oklch(var(--oa-ring) / <alpha-value>)',
      },
      fontFamily: {
        'mono': ['JetBrains Mono', 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Code', 'monospace'],
        'terminal': ['JetBrains Mono', 'Consolas', 'Monaco', 'monospace'],
      },
      animation: {
        'slide-in': 'slideIn 0.2s ease-out',
        'fade-in': 'fadeIn 0.15s ease-out',
        'pulse-glow': 'pulseGlow 2s ease-in-out infinite',
        'ticker': 'ticker 20s linear infinite',
        'scan-line': 'scanLine 4s linear infinite',
      },
      keyframes: {
        slideIn: {
          '0%': { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(0)' },
        },
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        pulseGlow: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.6' },
        },
        ticker: {
          '0%': { transform: 'translateX(0)' },
          '100%': { transform: 'translateX(-50%)' },
        },
        scanLine: {
          '0%': { transform: 'translateY(-100%)' },
          '100%': { transform: 'translateY(100vh)' },
        },
      },
      boxShadow: {
        'subtle': '0 1px 2px 0 rgba(0, 0, 0, 0.05)',
        'medium': '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)',
        'large': '0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)',
        'terminal': '0 0 0 1px rgba(30, 34, 45, 1), 0 4px 16px rgba(0, 0, 0, 0.4)',
        'glow-cyan': '0 0 20px rgba(0, 212, 255, 0.15)',
        'glow-profit': '0 0 12px rgba(38, 166, 154, 0.25)',
        'glow-loss': '0 0 12px rgba(239, 83, 80, 0.25)',
        'inset-terminal': 'inset 0 1px 0 rgba(255,255,255,0.03), inset 0 -1px 0 rgba(0,0,0,0.3)',
      },
      backgroundImage: {
        'grid-pattern': 'linear-gradient(rgba(30, 34, 45, 0.5) 1px, transparent 1px), linear-gradient(90deg, rgba(30, 34, 45, 0.5) 1px, transparent 1px)',
        'noise': "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E\")",
      },
    },
  },
  plugins: [
    require('daisyui')
  ],
  daisyui: {
    themes: [
      {
        /* Light theme - verified against OpenAlgo's real rendered computed
           styles (see the note in src/input.css), not the dead legacy
           Bloomberg-terminal color block. info/warning reuse OpenAlgo's own
           real "buy"/"sell" semantic tokens rather than inventing new hues;
           success/error reuse its real "profit"/"destructive" tokens. */
        light: {
          "primary": "oklch(0.205 0 0)",
          "primary-content": "oklch(0.985 0 0)",
          "secondary": "oklch(0.97 0 0)",
          "secondary-content": "oklch(0.205 0 0)",
          "accent": "oklch(0.97 0 0)",
          "accent-content": "oklch(0.205 0 0)",
          "neutral": "oklch(0.556 0 0)",
          "neutral-content": "oklch(0.985 0 0)",
          "base-100": "oklch(1 0 0)",
          "base-200": "oklch(0.97 0 0)",
          "base-300": "oklch(0.922 0 0)",
          "base-content": "oklch(0.145 0 0)",
          "info": "hsl(217 91% 60%)",       /* OpenAlgo's real --buy token */
          "info-content": "#ffffff",
          "success": "hsl(142 76% 36%)",    /* OpenAlgo's real --profit token */
          "success-content": "#ffffff",
          "warning": "hsl(25 95% 53%)",     /* OpenAlgo's real --sell token */
          "warning-content": "#ffffff",
          "error": "oklch(0.577 0.245 27.325)", /* OpenAlgo's real --destructive token */
          "error-content": "#ffffff",
        },
        /* Dark theme - same verification as light. */
        dark: {
          "primary": "oklch(0.922 0 0)",
          "primary-content": "oklch(0.205 0 0)",
          "secondary": "oklch(0.269 0 0)",
          "secondary-content": "oklch(0.985 0 0)",
          "accent": "oklch(0.269 0 0)",
          "accent-content": "oklch(0.985 0 0)",
          "neutral": "oklch(0.708 0 0)",
          "neutral-content": "oklch(0.145 0 0)",
          "base-100": "oklch(0.145 0 0)",
          "base-200": "oklch(0.205 0 0)",
          "base-300": "oklch(0.269 0 0)",
          "base-content": "oklch(0.985 0 0)",
          "info": "hsl(217 91% 65%)",
          "info-content": "#0a0a0c",
          "success": "hsl(142 69% 58%)",
          "success-content": "#0a0a0c",
          "warning": "hsl(25 95% 63%)",
          "warning-content": "#0a0a0c",
          "error": "oklch(0.704 0.191 22.216)",
          "error-content": "#ffffff",
        },
        /* Analyzer/paper-trading theme - matches Kotak's Analyzer mode (a
           real per-account state, see project_acc3_iqbal_kotak_setup.md),
           not just decorative parity. */
        analyzer: {
          "primary": "oklch(0.7 0.2 280)",
          "primary-content": "oklch(0.98 0 0)",
          "secondary": "oklch(0.28 0.03 280)",
          "secondary-content": "oklch(0.95 0.02 280)",
          "accent": "oklch(0.28 0.03 280)",
          "accent-content": "oklch(0.95 0.02 280)",
          "neutral": "oklch(0.7 0.03 280)",
          "neutral-content": "oklch(0.16 0.02 280)",
          "base-100": "oklch(0.16 0.02 280)",
          "base-200": "oklch(0.2 0.025 280)",
          "base-300": "oklch(0.28 0.03 280)",
          "base-content": "oklch(0.95 0.02 280)",
          "info": "hsl(217 91% 65%)",
          "info-content": "#0a0a0c",
          "success": "hsl(142 69% 58%)",
          "success-content": "#0a0a0c",
          "warning": "hsl(25 95% 63%)",
          "warning-content": "#0a0a0c",
          "error": "oklch(0.65 0.2 25)",
          "error-content": "#ffffff",
        },
      },
    ],
  },
}