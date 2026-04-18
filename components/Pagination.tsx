'use client';

import Link from 'next/link';
import { useSearchParams, usePathname } from 'next/navigation';

interface Props {
  currentPage: number;
  totalPages: number;
}

/**
 * 簡單分頁器:前 / 1 2 3 … N / 後
 * 保留目前的 category/city/district/pricing 查詢參數。
 */
export default function Pagination({ currentPage, totalPages }: Props) {
  const pathname = usePathname();
  const params = useSearchParams();

  if (totalPages <= 1) return null;

  const makeHref = (p: number) => {
    const q = new URLSearchParams(params.toString());
    if (p === 1) q.delete('page');
    else q.set('page', String(p));
    const qs = q.toString();
    return qs ? `${pathname}?${qs}` : pathname;
  };

  // 決定要顯示哪些頁碼(最多顯示 7 個:當前頁兩側 + 第一頁 + 最後一頁)
  const pages: (number | 'ellipsis')[] = [];
  const push = (v: number | 'ellipsis') => {
    if (pages[pages.length - 1] !== v) pages.push(v);
  };
  push(1);
  const left = Math.max(2, currentPage - 1);
  const right = Math.min(totalPages - 1, currentPage + 1);
  if (left > 2) push('ellipsis');
  for (let i = left; i <= right; i++) push(i);
  if (right < totalPages - 1) push('ellipsis');
  if (totalPages > 1) push(totalPages);

  return (
    <nav className="flex items-center justify-center gap-1 mt-10 mb-4 flex-wrap">
      <Link
        href={makeHref(Math.max(1, currentPage - 1))}
        aria-disabled={currentPage === 1}
        className={`text-[14.5px] px-3 py-1.5 rounded-full border transition-colors ${
          currentPage === 1
            ? 'border-black/5 text-ink-faded pointer-events-none'
            : 'border-black/10 text-ink-muted hover:bg-paper-sunken'
        }`}
      >
        ← 上一頁
      </Link>

      {pages.map((p, i) =>
        p === 'ellipsis' ? (
          <span key={`e-${i}`} className="text-[14.5px] text-ink-faded px-1.5">
            …
          </span>
        ) : (
          <Link
            key={p}
            href={makeHref(p)}
            className={`text-[14.5px] min-w-9 text-center px-3 py-1.5 rounded-full border transition-colors ${
              p === currentPage
                ? 'bg-ink text-paper border-ink'
                : 'border-black/5 text-ink-muted hover:bg-paper-sunken'
            }`}
          >
            {p}
          </Link>
        )
      )}

      <Link
        href={makeHref(Math.min(totalPages, currentPage + 1))}
        aria-disabled={currentPage === totalPages}
        className={`text-[14.5px] px-3 py-1.5 rounded-full border transition-colors ${
          currentPage === totalPages
            ? 'border-black/5 text-ink-faded pointer-events-none'
            : 'border-black/10 text-ink-muted hover:bg-paper-sunken'
        }`}
      >
        下一頁 →
      </Link>
    </nav>
  );
}
