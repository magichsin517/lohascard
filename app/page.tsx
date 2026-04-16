import { supabase, Activity } from '@/lib/supabase';
import Header from '@/components/Header';
import ActivityCard from '@/components/ActivityCard';
import CategoryFilter from '@/components/CategoryFilter';
import DistrictFilter from '@/components/DistrictFilter';
import PricingFilter from '@/components/PricingFilter';
import Pagination from '@/components/Pagination';
import LineCallout from '@/components/LineCallout';

export const revalidate = 60; // 每分鐘重新驗證一次

const PAGE_SIZE = 30;

async function getActivities(
  category: string | undefined,
  district: string | undefined,
  city: string | undefined,
  pricing: string | undefined,
  page: number
): Promise<{ rows: Activity[]; total: number }> {
  // 過濾過期:
  //   - recurring 活動永遠顯示(沒有終止日)
  //   - single 活動若有 end_date,必須 end_date >= 今天
  //   - single 活動若只有 start_date,必須 start_date >= 今天
  //   - 完全沒日期的活動(爬來的月度課表)暫時保留顯示 — 等 PDF 解析後補日期再加嚴
  const today = new Date().toISOString().slice(0, 10); // YYYY-MM-DD (UTC)

  const from = (page - 1) * PAGE_SIZE;
  const to = from + PAGE_SIZE - 1;

  let query = supabase
    .from('activities')
    .select('*', { count: 'exact' })
    .eq('status', 'active')
    // 不顯示這些雜訊 tag 的 parent 活動
    .not('tags', 'cs', '{"無課表附件"}')
    .not('tags', 'cs', '{"解析失敗"}')
    .not('tags', 'cs', '{"解析0堂"}')
    // recurring 一律保留,single 活動則看日期
    .or(
      `event_type.eq.recurring,` +
      `end_date.gte.${today},` +
      `and(end_date.is.null,start_date.gte.${today}),` +
      `and(end_date.is.null,start_date.is.null)`
    )
    .order('start_date', { ascending: true, nullsFirst: false })
    .order('id', { ascending: true })
    .range(from, to);

  if (category && category !== 'all') {
    query = query.eq('category', category);
  }
  if (district) {
    query = query.eq('district', district);
  }
  if (city) {
    query = query.eq('city', city);
  }
  if (pricing && pricing !== 'all') {
    // tags 為 text[],用 contains 找包含該價格 tag 的活動
    query = query.contains('tags', [pricing]);
  }

  const { data, error, count } = await query;
  if (error) {
    console.error('[getActivities]', error);
    return { rows: [], total: 0 };
  }
  return { rows: (data as Activity[]) || [], total: count ?? 0 };
}

export default async function HomePage({
  searchParams,
}: {
  searchParams: Promise<{ category?: string; district?: string; city?: string; pricing?: string; page?: string }>;
}) {
  const params = await searchParams;
  const page = Math.max(1, parseInt(params.page || '1', 10) || 1);
  const { rows: activities, total } = await getActivities(
    params.category,
    params.district,
    params.city,
    params.pricing,
    page
  );
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <>
      <Header />

      <main className="max-w-6xl mx-auto px-5 md:px-8">
        {/* Hero 區塊 */}
        <section className="py-14 md:py-20 border-b border-black/5">
          <p className="text-[11px] tracking-[0.25em] text-ink-faded uppercase mb-5">
            For 60+ · Taiwan
          </p>
          <h1 className="font-display text-[36px] md:text-[52px] leading-[1.2] text-ink max-w-3xl mb-5">
            退休後的每一天,<br />
            都值得好好過。
          </h1>
          <p className="text-ink-muted text-[16px] md:text-[17px] max-w-xl leading-relaxed">
            我們幫你從全台里長、樂齡中心、社區關懷據點、老人服務中心的活動裡,挑出最值得參加的那些。
            免費或小額,在你家附近,說走就走。
          </p>
        </section>

        {/* 篩選區 */}
        <section className="py-8 md:py-10 space-y-5">
          <CategoryFilter />
          <PricingFilter />
          <DistrictFilter />
        </section>

        {/* 活動列表 */}
        <section className="pb-8">
          <div className="flex items-baseline justify-between mb-6">
            <p className="text-[13px] text-ink-faded">
              {params.city ? `${params.city} · ` : ''}
              {params.district ? `${params.district} · ` : ''}
              共 {total} 個活動{totalPages > 1 ? `(第 ${page}/${totalPages} 頁)` : ''}
            </p>
          </div>

          {activities.length === 0 ? (
            <EmptyState />
          ) : (
            <>
              <div className="grid gap-5 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
                {activities.map((a) => (
                  <ActivityCard key={a.id} activity={a} />
                ))}
              </div>
              <Pagination currentPage={page} totalPages={totalPages} />
            </>
          )}
        </section>

        <LineCallout />

        <footer className="border-t border-black/5 py-10 text-center">
          <p className="font-display text-lg text-ink mb-2">樂活卡卡</p>
          <p className="text-[12px] text-ink-faded">
            Lohas Card · 為台灣銀髮族聚合好活動
          </p>
          <p className="text-[11px] text-ink-faded mt-4">
            資料來源:教育部樂齡學習網、衛生福利部社區照顧關懷據點、各縣市政府、各合作單位
          </p>
        </footer>
      </main>
    </>
  );
}

function EmptyState() {
  return (
    <div className="py-24 text-center">
      <p className="font-display text-xl text-ink mb-2">這區暫時還沒有活動</p>
      <p className="text-[13px] text-ink-muted">試試別的區域,或回到全部活動</p>
    </div>
  );
}
