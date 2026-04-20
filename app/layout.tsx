import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: '樂活卡卡 Lohas Card',
  description: '才剛 55,生活才真的要開始 — 每週替你從雙北挑幾個值得走一趟的活動、走讀、課程。',
  openGraph: {
    title: '樂活卡卡 Lohas Card',
    description: '才剛 55,生活才真的要開始。',
    type: 'website',
    locale: 'zh_TW',
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-Hant">
      <body>{children}</body>
    </html>
  );
}
