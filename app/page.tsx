import { supabase, Activity } from '@/lib/supabase';
import Header from '@/components/Header';
import ActivityCard from '@/components/ActivityCard';
import CategoryFilter from '@/components/CategoryFilter';
import DistrictFilter from '@/components/DistrictFilter';
import PricingFilter from '@/components/PricingFilter';
import LineCallout from '@/components/LineCallout';

export const revalidate = 60; // 每分鐘重新驗證一次

async function getActivities(category?: string, district?: string, city?: string, pricing?: string): Promise<Activity[]> {
  let query = supabase
    .from('activities')
    .select('*')
    .eq('status', 'active')
    .order('start_date', { ascending: true, nullsFirst: false });

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

  const { data, error } = await query;
  if (error) {
    console.error('[getActivities]', error);
    return [];
  }
  return (data as Activity[]) || [];
}

export default async function HomePage({
  searchParams,
}: {
  searchParams: Promise<{ category?: string; district?: string; city?: string; pricing?: string }>;
}) {
  const params = await searchParams;
  const activities = await getActivities(params.category, params.district, params.city, params.pricing);

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
              {activities.length} 個活動
            </p>
          </div>

          {activities.length === 0 ? (
            <EmptyState />
          ) : (
            <div className="grid gap-5 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
              {activities.map((a) => (
                <ActivityCard key={a.id} activity={a} />
              ))}
            </div>
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
