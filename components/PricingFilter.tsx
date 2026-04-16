'use client';

import { useRouter, useSearchParams, usePathname } from 'next/navigation';
import { PRICING_TIERS } from '@/lib/supabase';

const ALL = ['all', ...PRICING_TIERS] as const;

export default function PricingFilter() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const current = searchParams.get('pricing') || 'all';

  const handleClick = (key: string) => {
    const params = new URLSearchParams(searchParams.toString());
    if (key === 'all') {
      params.delete('pricing');
    } else {
      params.set('pricing', key);
    }
    router.push(`${pathname}?${params.toString()}`);
  };

  return (
    <div className="flex gap-2 flex-wrap">
      {ALL.map((key) => {
        const isActive = current === key;
        const label = key === 'all' ? '全部費用' : key;
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
