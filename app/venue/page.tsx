import Link from 'next/link';
import { createClient } from '@supabase/supabase-js';
import type { Activity } from '@/lib/supabase';
import Header from '@/components/Header';

const VENUE_SOURCE = '衛福部社區照顧關懷據點';

// 這頁用 server component 直接讀 DB。用 publishable key 即可(讀取無密碼)
const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!,
);

export const metadata = {
  title: '附近據點 | 樂活卡卡',
  description: '全台社區關懷據點,找離你最近的聚會地點。',
};

// 開放給 Next.js 做 ISR(12 小時重新產生一次,據點資料更新不急)
export const revalidate = 43200;

export default async function VenuesPage({
  searchParams,
}: {
  searchParams: { city?: string };
}) {
  let q = supabase
    .from('activities')
    .select('id, title, city, district, location_name')
    .eq('source_name', VENUE_SOURCE);

  if (searchParams?.city) {
    q = q.eq('city', searchParams.city);
  }

  const { data: venues } = await q
    .order('city')
    .order('district')
    .order('title')
    .limit(1000);

  // 城市清單(給 filter 用)
  const cityCounts = new Map<string, number>();
  (venues ?? []).forEach((v) => {
    if (v.city) cityCounts.set(v.city, (cityCounts.get(v.city) ?? 0) + 1);
  });

  return (
    <>
      <Header />

      <main className="max-w-6xl mx-auto px-5 md:px-8 py-8 md:py-12">
      <header className="mb-8">
        <h1 className="font-display text-[32px] md:text-[42px] leading-tight text-ink mb-3">附近據點</h1>
        <p className="text-ink-muted max-w-2xl leading-relaxed">
          社區關懷據點是地方上的長輩聚會點,有固定時段的共餐、活動、健康促進。
          資料來自衛福部。想找單次可報名的活動,請回到
          <Link href="/" className="underline ml-1">首頁</Link>。
        </p>
      </header>

      {/* 城市 filter — 陽春版 */}
      {cityCounts.size > 0 && (
        <nav className="mb-6 flex flex-wrap gap-2">
          <Link
            href="/venue"
            className={`text-sm px-3 py-1.5 rounded-full border ${
              !searchParams?.city
                ? 'bg-ink text-paper-raised border-ink'
                : 'border-black/10 hover:border-black/30'
            }`}
          >
            全部
          </Link>
          {Array.from(cityCounts.entries())
            .sort((a, b) => b[1] - a[1])
            .map(([city, count]) => (
              <Link
                key={city}
                href={`/venue?city=${encodeURIComponent(city)}`}
                className={`text-sm px-3 py-1.5 rounded-full border ${
                  searchParams?.city === city
                    ? 'bg-ink text-paper-raised border-ink'
                    : 'border-black/10 hover:border-black/30'
                }`}
              >
                {city} <span className="text-ink-muted">({count})</span>
              </Link>
            ))}
        </nav>
      )}

      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
        {(venues ?? []).map((v) => (
          <article
            key={v.id}
            className="border border-black/5 bg-paper-raised rounded-xl p-4 hover:border-black/15 transition-colors"
          >
            <h3 className="font-medium text-ink leading-snug mb-1.5">{v.title}</h3>
            <div className="text-[13px] text-ink-muted">
              {v.city} {v.district ?? ''}
            </div>
            {v.location_name && (
              <div className="text-[13px] text-ink-muted mt-1">
                {v.location_name}
              </div>
            )}
          </article>
        ))}
      </div>

      {(!venues || venues.length === 0) && (
        <div className="text-center py-12 text-ink-muted">
          找不到據點。
          <Link href="/venue" className="underline ml-1">回全部</Link>
        </div>
      )}
      </main>
    </>
  );
}
