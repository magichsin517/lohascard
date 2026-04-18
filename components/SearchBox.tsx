'use client';

import { useRouter, useSearchParams, usePathname } from 'next/navigation';
import { useState, useEffect, FormEvent } from 'react';

/**
 * 首頁的搜尋框。輸入關鍵字(例如「太極」「卡拉 OK」)後按 Enter / 放大鏡,
 * 把 `?q=XXX` 寫入 URL,頁面會用 PostgREST ilike 做模糊比對。
 */
export default function SearchBox() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const initial = searchParams.get('q') || '';
  const [value, setValue] = useState(initial);

  // URL 的 q 改變時(例如按分頁保留參數)同步到輸入框
  useEffect(() => {
    setValue(searchParams.get('q') || '');
  }, [searchParams]);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const params = new URLSearchParams(searchParams.toString());
    const q = value.trim();
    if (q) params.set('q', q);
    else params.delete('q');
    params.delete('page'); // 搜尋時回到第 1 頁
    router.push(`${pathname}?${params.toString()}`);
  };

  const clear = () => {
    setValue('');
    const params = new URLSearchParams(searchParams.toString());
    params.delete('q');
    params.delete('page');
    router.push(`${pathname}?${params.toString()}`);
  };

  return (
    <form onSubmit={submit} className="relative max-w-xl">
      <div className="flex items-center gap-2 bg-paper-raised border border-black/10 rounded-full pl-5 pr-1.5 py-1.5 focus-within:border-ink/30 transition-colors">
        <span className="text-ink-faded text-[17px]" aria-hidden>
          ⌕
        </span>
        <input
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="搜尋活動、課程、中心(例:太極、卡拉 OK、書法)"
          className="flex-1 bg-transparent outline-none text-[16px] text-ink placeholder:text-ink-faded py-2"
        />
        {value && (
          <button
            type="button"
            onClick={clear}
            className="text-[14px] text-ink-faded hover:text-ink px-2"
            aria-label="清除"
          >
            ✕
          </button>
        )}
        <button
          type="submit"
          className="bg-ink text-paper text-[14.5px] px-5 py-2 rounded-full hover:bg-ink-soft transition-colors"
        >
          搜尋
        </button>
      </div>
    </form>
  );
}
