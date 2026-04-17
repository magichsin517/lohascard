'use client';

import { useRouter, useSearchParams, usePathname } from 'next/navigation';

// 資料類型:課程 / 社區據點 / 全部
// 預設「課程」(排除據點),避免首次進來 5800+ 據點卡片洗版
const OPTIONS: Array<{ key: string; label: string; hint?: string }> = [
  { key: 'course', label: '課程活動' },
  { key: 'point', label: '社區據點' },
  { key: 'all', label: '全部' },
];

export default function SourceFilter() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const current = searchParams.get('source') || 'course';

  const handleClick = (key: string) => {
    const params = new URLSearchParams(searchParams.toString());
    // 回到第一頁
    params.delete('page');
    if (key === 'course') {
      params.delete('source');
    } else {
      params.set('source', key);
    }
    router.push(`${pathname}?${params.toString()}`);
  };

  return (
    <div className="flex gap-2 flex-wrap">
      {OPTIONS.map(({ key, label }) => {
        const isActive = current === key;
        return (
          <button
            key={key}
            onClick={() => handleClick(key)}
            className={`text-[13px] px-4 py-1.5 rounded-full transition-all ${
              isActive
                ? 'bg-ink text-paper'
                : 'bg-paper-raised text-ink-muted hover:bg-paper-sunken border border-black/5'
            }`}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}
