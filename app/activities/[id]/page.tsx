import { supabase, Activity, CATEGORIES, formatEventTime, formatCost, groupKey } from '@/lib/supabase';
import Header from '@/components/Header';
import Image from 'next/image';
import Link from 'next/link';
import { notFound } from 'next/navigation';

export const revalidate = 60;

async function getActivity(id: string): Promise<Activity | null> {
  const { data, error } = await supabase
    .from('activities')
    .select('*')
    .eq('id', id)
    .single();

  if (error || !data) return null;
  return data as Activity;
}

async function getSessionsInGroup(activity: Activity): Promise<Activity[]> {
  // 用 title + location_name + organizer_name 精確比對同一活動的其他場次
  // (不過濾 event_type,因為 PDF 解析時有時會誤標)
  let q = supabase
    .from('activities')
    .select('*')
    .eq('status', 'active')
    .eq('title', activity.title);
  q = activity.location_name
    ? q.eq('location_name', activity.location_name)
    : q.is('location_name', null);
  q = activity.organizer_name
    ? q.eq('organizer_name', activity.organizer_name)
    : q.is('organizer_name', null);

  const { data, error } = await q;
  if (error || !data) return [activity];
  const rows = data as Activity[];
  // 再以 normalize 過的 groupKey 做二次確認,避免空白差異漏網
  const myKey = groupKey(activity);
  return rows.filter((r) => groupKey(r) === myKey);
}

export default async function ActivityDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const activity = await getActivity(id);

  if (!activity) notFound();

  const allSessions = await getSessionsInGroup(activity);
  // 排序:有日期優先,然後按 start_date + start_time 升冪。
  // 兩邊都沒日期時仍要比 start_time。
  allSessions.sort((a, b) => {
    if (!a.start_date && b.start_date) return 1;
    if (a.start_date && !b.start_date) return -1;
    if (a.start_date && b.start_date && a.start_date !== b.start_date) {
      return a.start_date < b.start_date ? -1 : 1;
    }
    const at = a.start_time || '';
    const bt = b.start_time || '';
    if (at === bt) return 0;
    return at < bt ? -1 : 1;
  });
  const hasMultipleSessions = allSessions.length > 1;

  const category = activity.category ? CATEGORIES[activity.category] : null;
  const imageUrl = activity.image_url || (activity.category ? `/images/categories/${activity.category}.svg` : '/images/categories/social.svg');

  return (
    <>
      <Header />

      <main className="max-w-3xl mx-auto px-5 md:px-8 py-8 md:py-12">
        <Link
          href="/"
          className="text-[13px] text-ink-muted hover:text-ink mb-8 inline-flex items-center gap-1.5"
        >
          <span>←</span> 回到活動列表
        </Link>

        <article>
          {/* 封面圖 */}
          <div className="relative aspect-[16/9] mb-8 rounded-2xl overflow-hidden bg-paper-sunken border border-black/5">
            <Image
              src={imageUrl}
              alt={activity.title}
              fill
              className="object-cover"
              priority
              sizes="(max-width: 768px) 100vw, 768px"
            />
          </div>

          {/* 標籤 */}
          <div className="flex gap-2 mb-4 flex-wrap">
            {category && (
              <span className={`text-[12px] px-3 py-1 rounded-full ${category.bg} ${category.text} font-medium`}>
                {category.label}
              </span>
            )}
            {activity.tags?.map((tag) => (
              <span
                key={tag}
                className="text-[12px] px-3 py-1 rounded-full bg-paper-sunken text-ink-muted"
              >
                {tag}
              </span>
            ))}
          </div>

          <h1 className="font-display text-[30px] md:text-[38px] leading-tight text-ink mb-6">
            {activity.title}
          </h1>

          {activity.summary && (
            <p className="text-[17px] text-ink-soft leading-relaxed mb-8 font-[400]">
              {activity.summary}
            </p>
          )}

          {/* 關鍵資訊 block */}
          <div className="bg-paper-sunken rounded-2xl p-6 md:p-7 mb-10 space-y-4">
            {hasMultipleSessions ? (
              <SessionsRow sessions={allSessions} />
            ) : (
              <InfoRow label="時間" value={formatEventTime(activity)} />
            )}
            <InfoRow label="地點" value={activity.location_name || ''} secondary={activity.address} />
            <InfoRow
              label="區域"
              value={`${activity.city || ''} ${activity.district || ''}`.trim()}
            />
            <InfoRow label="主辦" value={activity.organizer_name || ''} />
            <InfoRow label="對象" value={activity.target_audience || '不限'} />
            <InfoRow label="費用" value={formatCost(activity)} secondary={activity.cost_note} />
          </div>

          {/* 詳細介紹 */}
          {activity.description && (
            <section className="mb-10">
              <h2 className="font-display text-xl text-ink mb-4">活動介紹</h2>
              <p className="text-[15.5px] text-ink-soft leading-[1.9] whitespace-pre-line">
                {activity.description}
              </p>
            </section>
          )}

          {/* 報名方式 */}
          <section className="border-t border-black/5 pt-8">
            <h2 className="font-display text-xl text-ink mb-4">如何參加</h2>
            <SignupCard activity={activity} />
          </section>

          {/* 原始公告連結:想知道消息來源或看完整內容時用 */}
          {activity.source_url && (
            <section className="border-t border-black/5 mt-10 pt-6">
              <p className="text-[12px] tracking-[0.15em] text-ink-faded uppercase mb-2">消息來源</p>
              <a
                href={activity.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-[14px] text-sky-700 hover:text-sky-500 hover:underline underline-offset-2 break-all"
              >
                閱讀原文公告
                <span aria-hidden className="text-[11px]">↗</span>
              </a>
            </section>
          )}
        </article>

        <footer className="border-t border-black/5 mt-16 pt-8 pb-10 text-center">
          <Link href="/" className="text-[13px] text-ink-muted hover:text-ink">
            ← 看更多活動
          </Link>
        </footer>
      </main>
    </>
  );
}

function InfoRow({ label, value, secondary }: { label: string; value: string; secondary?: string | null }) {
  if (!value) return null;
  return (
    <div className="flex gap-6 items-baseline">
      <span className="text-[12px] tracking-[0.15em] text-ink-faded uppercase w-14 shrink-0">
        {label}
      </span>
      <div>
        <p className="text-[15px] text-ink">{value}</p>
        {secondary && <p className="text-[13px] text-ink-muted mt-0.5">{secondary}</p>}
      </div>
    </div>
  );
}

function SessionsRow({ sessions }: { sessions: Activity[] }) {
  return (
    <div className="flex gap-6 items-baseline">
      <span className="text-[12px] tracking-[0.15em] text-ink-faded uppercase w-14 shrink-0">
        時間
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-[13px] text-ink-muted mb-2">
          共 <span className="text-ink font-medium">{sessions.length}</span> 場次可選
        </p>
        <ul className="divide-y divide-black/5 border-t border-black/5">
          {sessions.map((s) => (
            <li key={s.id} className="py-2.5 text-[14.5px] text-ink">
              {formatEventTime(s)}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function SignupCard({ activity }: { activity: Activity }) {
  const method = activity.signup_method;
  const linkIsSource = !!activity.signup_url && activity.signup_url === activity.source_url;

  if (method === 'walk_in' || method === 'none') {
    return (
      <div className="bg-moss-50 rounded-2xl p-6 border border-moss-500/20">
        <p className="text-moss-700 font-medium mb-1">不需預先報名</p>
        <p className="text-[14px] text-ink-soft">當天直接前往活動地點即可。</p>
      </div>
    );
  }

  const hasAny = activity.signup_phone || activity.signup_url || activity.source_url;
  if (!hasAny) {
    return (
      <div className="bg-paper-sunken rounded-2xl p-6 border border-black/5">
        <p className="text-[14px] text-ink-muted">
          報名方式請洽主辦單位
          {activity.organizer_name ? `「${activity.organizer_name}」` : ''}。
        </p>
      </div>
    );
  }

  return (
    <div className="bg-paper-raised rounded-2xl p-6 border border-black/10 space-y-4">
      {activity.signup_phone && (
        <div>
          <p className="text-[11px] tracking-[0.15em] text-ink-faded uppercase mb-1.5">電話報名</p>
          <a
            href={`tel:${activity.signup_phone}`}
            className="font-display text-2xl text-ink hover:text-moss-700 transition-colors"
          >
            {activity.signup_phone}
          </a>
        </div>
      )}
      {activity.signup_url && (
        <div>
          <p className="text-[11px] tracking-[0.15em] text-ink-faded uppercase mb-1.5">
            {linkIsSource ? '原始公告(含詳細課表與聯絡方式)' : '線上報名'}
          </p>
          <a
            href={activity.signup_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[14px] text-sky-700 hover:underline break-all"
          >
            {activity.signup_url}
          </a>
        </div>
      )}
      {activity.signup_deadline && (
        <p className="text-[13px] text-clay-700">
          ⚠ 報名截止:{activity.signup_deadline}
        </p>
      )}
      {activity.capacity && (
        <p className="text-[13px] text-ink-muted">
          名額:{activity.capacity} 人
        </p>
      )}
    </div>
  );
}
