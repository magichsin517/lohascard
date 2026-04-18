import Link from 'next/link';
import { Activity, CATEGORIES, PRICING_STYLE, PRICING_TIERS, formatEventTime, formatCost, pricingTierOf } from '@/lib/supabase';
import BookmarkButton from './BookmarkButton';
import ActivityImage from './ActivityImage';

export default function ActivityCard({
  activity,
  sessionCount = 1,
}: {
  activity: Activity;
  sessionCount?: number;
}) {
  const category = activity.category ? CATEGORIES[activity.category] : null;
  const pricingTier = pricingTierOf(activity);
  const pricingStyle = PRICING_STYLE[pricingTier];
  // 定價 tag 已用獨立 badge 呈現,從 tags 中過濾掉避免重複
  const otherTags = (activity.tags || []).filter((t) => !(PRICING_TIERS as readonly string[]).includes(t));
  const detailHref = `/activities/${activity.id}`;
  const hasMultipleSessions = sessionCount > 1;

  return (
    <article className="group relative bg-paper-raised rounded-2xl border border-black/5 hover:border-black/15 hover:shadow-[0_4px_20px_-8px_rgba(0,0,0,0.12)] transition-all duration-300 flex flex-col">
      {/* 收藏按鈕:絕對定位在右上角,overlay 在 Link 之上,防止點擊冒泡到卡片 */}
      <BookmarkButton activityId={activity.id} variant="overlay" />

      {/* 圖片 + 主內容都導到詳細頁 */}
      <Link href={detailHref} className="block">
        <div className="relative aspect-[5/3] bg-paper-sunken overflow-hidden rounded-t-2xl">
          <ActivityImage
            imageUrl={activity.image_url}
            category={activity.category}
            title={activity.title}
          />
        </div>

        <div className="p-5 pb-4">
          <div className="flex gap-1.5 mb-3 flex-wrap">
            {category && (
              <span className={`text-[12.5px] px-2.5 py-0.5 rounded-full ${category.bg} ${category.text} font-medium`}>
                {category.label}
              </span>
            )}
            <span className={`text-[12.5px] px-2.5 py-0.5 rounded-full ${pricingStyle.bg} ${pricingStyle.text} font-medium`}>
              {pricingTier}
            </span>
            {otherTags.slice(0, 2).map((tag) => (
              <span
                key={tag}
                className="text-[12.5px] px-2.5 py-0.5 rounded-full bg-paper-sunken text-ink-muted"
              >
                {tag}
              </span>
            ))}
          </div>

          <h3 className="font-medium text-[17.5px] leading-snug mb-2 text-ink group-hover:text-ink-soft transition-colors">
            {activity.title}
          </h3>

          {activity.summary && (
            <p className="text-[15px] text-ink-muted leading-relaxed mb-4 line-clamp-2">
              {activity.summary}
            </p>
          )}

          <div className="text-[14px] text-ink-muted space-y-1.5 font-normal">
            <div className="flex items-start gap-2">
              <span className="text-ink-faded w-3.5 shrink-0 mt-px">◷</span>
              <span>
                {formatEventTime(activity)}
                {hasMultipleSessions && (
                  <span className="ml-2 inline-block text-[12.5px] px-1.5 py-0.5 rounded-md bg-sky-50 text-sky-700 font-medium align-middle">
                    共 {sessionCount} 場次
                  </span>
                )}
              </span>
            </div>
            <div className="flex items-start gap-2">
              <span className="text-ink-faded w-3.5 shrink-0 mt-px">◉</span>
              <span className="truncate">{activity.location_name}</span>
            </div>
            <div className="flex items-start gap-2">
              <span className="text-ink-faded w-3.5 shrink-0 mt-px">¥</span>
              <span>{formatCost(activity)}</span>
            </div>
          </div>
        </div>
      </Link>
    </article>
  );
}
