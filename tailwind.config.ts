import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['var(--font-sans)', 'system-ui', 'sans-serif'],
        display: ['var(--font-display)', 'system-ui', 'sans-serif'],
      },
      colors: {
        ink: {
          DEFAULT: '#1a1a1a',
          soft: '#3a3a3a',
          muted: '#5a5a5a',   // 從 #6b6b6b 加深,55+ 可讀性
          faded: '#7a7a7a',   // 從 #9a9a9a 加深,老花眼友善
        },
        paper: {
          DEFAULT: '#fdfcf8',
          raised: '#ffffff',
          sunken: '#f5f3ec',
        },
        moss: { 50: '#f2f6ef', 500: '#5a7a3e', 700: '#3a5226' },
        clay: { 50: '#f9f1ea', 500: '#b8714a', 700: '#7d4a2e' },
        sky:  { 50: '#eef4f8', 500: '#4a7a9a', 700: '#2f5775' },
        plum: { 50: '#f4eef2', 500: '#8a5a7a', 700: '#5c3a52' },
        sun:  { 50: '#faf4e6', 500: '#c89447', 700: '#8a6528' },
      },
    },
  },
  plugins: [],
};

export default config;
