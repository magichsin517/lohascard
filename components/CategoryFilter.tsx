'use client';

import { useRouter, useSearchParams, usePathname } from 'next/navigation';
import { CATEGORIES, Category } from '@/lib/supabase';

const ALL_CATEGORIES: (Category | 'all')[] = ['all', 'sports', 'learning', 'health', 'culture', 'travel', 'social', 'volunteer'];

export default function CategoryFilter() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const currentCategory = searchParams.get('category') || 'all';

  const handleClick = (cat: string) => {
    const params = new URLSearchParams(searchParams.toString());
    params.delete('page');
    if (cat === 'all') {
      params.delete('category');
    } else {
      params.set('category', cat);
    }
    router.push(`${pathname}?${params.toString()}`);
  };

  return (
    <div className="flex gap-2 gap-y-1.5 flex-wrap items-center">
      <span className="text-[14px] text-ink-muted font-medium shrink-0 mr-1">分類</span>
      {ALL_CATEGORIES.map((cat) => {
        const isActive = currentCategory === cat;
        const label = cat === 'all' ? '全部' : CATEGORIES[cat as Category].label;
        return (
          <button
            key={cat}
            onClick={() => handleClick(cat)}
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
