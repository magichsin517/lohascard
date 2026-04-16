import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: '樂活卡卡 Lohas Card',
  description: '台灣 60+ 活力銀髮族的活動聚合平台 — 每週發現身邊的好活動',
  openGraph: {
    title: '樂活卡卡 Lohas Card',
    description: '退休生活,從今天開始',
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
