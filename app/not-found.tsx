import Link from 'next/link';
import Header from '@/components/Header';

export default function NotFound() {
  return (
    <>
      <Header />
      <main className="max-w-3xl mx-auto px-5 md:px-8 py-24 text-center">
        <p className="text-[11px] tracking-[0.25em] text-ink-faded uppercase mb-4">404</p>
        <h1 className="font-display text-3xl text-ink mb-3">找不到這個活動</h1>
        <p className="text-ink-muted mb-8">可能已經結束、被移除,或是網址輸入錯誤。</p>
        <Link
          href="/"
          className="inline-block text-[14px] px-6 py-2.5 rounded-full bg-ink text-paper hover:bg-ink-soft transition-colors"
        >
          回到活動列表
        </Link>
      </main>
    </>
  );
}
