import Link from 'next/link';
import { createClient } from '@supabase/supabase-js';
import Header from '@/components/Header';
import Pagination from '@/components/Pagination';
import SearchBox from '@/components/SearchBox';

const VENUE_SOURCE = '衛福部社區照顧關懷據點';
const PAGE_SIZE = 60;

// 這頁用 server component 直接讀 DB。用 publishable key 即可(讀取無密碼)
const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!,
);

export const metadata = {
  title: '附近據點 | 樂活卡卡',
  description: '全台社區關懷據點,找離你最近的聚會地點。',
};

// 12 小時重新產生一次。分頁 + filter 不同會產生不同 cache entry,不用擔心失效
export const revalidate = 43200;

/**
 * 全體 city 統計 — 不受 q / city filter 影響,讓 chips 永遠顯示所有縣市。
 * 用 chunked range 撈(PostgREST 預設 max-rows=1000,不分批只拿得到 1000 筆)。
 */
async function getCityCounts(): Promise<Map<string, number>> {
  const counts = new Map<string, number>();
  const CHUNK = 1000;
  for (let offset = 0; offset < 20000; offset += CHUNK) {
    const end = offset + CHUNK - 1;
    const { data, error } = await supabase
      .from('activities')
      .select('city')
      .eq('source_name', VENUE_SOURCE)
      .range(offset, end);
    if (error) break;
    const rows = (data as { city: string | null }[]) || [];
    rows.forEach((r) => {
      if (r.city) counts.set(r.city, (counts.get(r.city) ?? 0) + 1);
    });
    if (rows.length < CHUNK) break;
  }
  return counts;
}

export default async function VenuesPage({
  searchParams,
}: {
  searchParams: Promise<{ city?: string; q?: string; page?: string }>;
}) {
  const params = await searchParams;
  const page = Math.max(1, parseInt(params.page || '1', 10) || 1);
  const from = (page - 1) * PAGE_SIZE;
  const to = from + PAGE_SIZE - 1;

  // 撈全體 city counts(給 chips)+ 該頁的 venues(給網格)— 並行
  const [cityCounts, venueResult] = await Promise.all([
    getCityCounts(),
    (async () => {
      let q = supabase
        .from('activities')
        .select('id, title, city, district, location_name', { count: 'exact' })
        .eq('source_name', VENUE_SOURCE);

      if (params.city) q = q.eq('city', params.city);
      if (params.q && params.q.trim()) {
        const kw = params.q.trim().replace(/[%,]/g, '');
        const pattern = `*${kw}*`;
        q = q.or(`title.ilike.${pattern},location_name.ilike.${pattern}`);
      }

      return q
        .order('city')
        .order('district')
        .order('title')
        .range(from, to);
    })(),
  ]);

  const venues = venueResult.data ?? [];
  const total = venueResult.count ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const totalVenues = Array.from(cityCounts.values()).reduce((a, b) => a + b, 0);

  // 幫忙保留目前其他 params 的 href builder
  const buildHref = (nextCity?: string) => {
    const p = new URLSearchParams();
    if (nextCity) p.set('city', nextCity);
    if (params.q) p.set('q', params.q);
    // 切 city chip 時回到第 1 頁
    const qs = p.toString();
    return qs ? `/venue?${qs}` : '/venue';
  };

  return (
    <>
      <Header />

      <main className="max-w-6xl mx-auto px-5 md:px-8 py-8 md:py-12">
        <header className="mb-6">
          <h1 className="font-display text-[32px] md:text-[42px] leading-tight text-ink mb-3">
            附近據點
          </h1>
          <p className="text-ink-muted max-w-2xl leading-relaxed">
            社區關懷據點是地方上的長輩聚會點,有固定時段的共餐、活動、健康促進。
            資料來自衛福部。想找單次可報名的活動,請回到
            <Link href="/" className="underline ml-1">
              首頁
            </Link>
            。
          </p>
        </header>

        {/* 搜尋框(寫入 ?q=) */}
        <div className="mb-5">
          <SearchBox />
        </div>

        {/* 城市 filter — chips 以全體 cityCounts 渲染,不受 q 影響 */}
        {cityCounts.size > 0 && (
          <nav className="mb-6 flex flex-wrap gap-2">
            <Link
              href={buildHref()}
              className={`text-sm px-3 py-1.5 rounded-full border ${
                !params.city
                  ? 'bg-ink text-paper-raised border-ink'
                  : 'border-black/10 hover:border-black/30'
              }`}
            >
              全部 <span className="text-ink-faded">({totalVenues})</span>
            </Link>
            {Array.from(cityCounts.entries())
              .sort((a, b) => b[1] - a[1])
              .map(([city, ccount]) => (
                <Link
                  key={city}
                  href={buildHref(city)}
                  className={`text-sm px-3 py-1.5 rounded-full border ${
                    params.city === city
                      ? 'bg-ink text-paper-raised border-ink'
                      : 'border-black/10 hover:border-black/30'
                  }`}
                >
                  {city} <span className="text-ink-muted">({ccount})</span>
                </Link>
              ))}
          </nav>
        )}

        {/* 結果摘要 */}
        <p className="text-[14px] text-ink-muted mb-5">
          {params.q ? `搜尋「${params.q}」· ` : ''}
          {params.city ? `${params.city} · ` : ''}
          共 {total} 個據點
          {totalPages > 1 ? `(第 ${page}/${totalPages} 頁)` : ''}
        </p>

        {venues.length > 0 ? (
          <>
            <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
              {venues.map((v) => (
                <article
                  key={v.id}
                  className="border border-black/5 bg-paper-raised rounded-xl p-4 hover:border-black/15 transition-colors"
                >
                  <h3 className="font-medium text-ink leading-snug mb-1.5">
                    {v.title}
                  </h3>
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
            <Pagination currentPage={page} totalPages={totalPages} />
          </>
        ) : (
          <div className="text-center py-12 text-ink-muted">
            找不到據點。
            <Link href="/venue" className="underline ml-1">
              回全部
            </Link>
          </div>
        )}
      </main>
    </>
  );
}
