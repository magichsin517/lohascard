'use client';

import { useRouter, useSearchParams, usePathname } from 'next/navigation';

// 資料類型:
//   - 預設(無參數):排除「鄰近社區」,只看課程活動 — 對使用者最有用的清單
//   - ?source=point:只看鄰近社區(衛福部 5,800+ 關懷據點)
//   - ?source=all:含社區,全部
//
// UI 顯示映射(「全部」靠左,跟其他篩選器一致):
const OPTIONS: Array<{ key: '' | 'point' | 'all'; label: string }> = [
  { key: '', label: '全部' },
  { key: 'point', label: '鄰近社區' },
  { key: 'all', label: '全部(含社區)' },
];

export default function SourceFilter() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const raw = searchParams.get('source') || '';
  const current: '' | 'point' | 'all' =
    raw === 'point' ? 'point' : raw === 'all' ? 'all' : '';

  const handleClick = (key: '' | 'point' | 'all') => {
    const params = new URLSearchParams(searchParams.toString());
    params.delete('page');
    if (!key) {
      params.delete('source');
    } else {
      params.set('source', key);
    }
    router.push(`${pathname}?${params.toString()}`);
  };

  return (
    <div className="flex gap-2 gap-y-1.5 flex-wrap items-center">
      <span className="text-[14px] text-ink-muted font-medium shrink-0 mr-1">類型</span>
      {OPTIONS.map(({ key, label }) => {
        const isActive = current === key;
        return (
          <button
            key={key || 'default'}
            onClick={() => handleClick(key)}
            className={`text-[14.5px] px-4 py-1.5 rounded-full transition-all ${
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
