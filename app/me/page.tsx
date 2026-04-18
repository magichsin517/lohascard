'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import Header from '@/components/Header';
import ActivityCard from '@/components/ActivityCard';
import {
  Bookmark,
  BOOKMARK_LABEL,
  BOOKMARK_ORDER,
  BookmarkStatus,
  getBookmarksByStatus,
  hasAnonId,
} from '@/lib/bookmarks';
import { Activity, supabase } from '@/lib/supabase';

type GroupedActivities = Record<BookmarkStatus, Activity[]>;

export default function MePage() {
  const [loading, setLoading] = useState(true);
  const [hasStarted, setHasStarted] = useState(false);
  const [grouped, setGrouped] = useState<GroupedActivities>({
    want: [],
    registered: [],
    done: [],
  });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        setLoading(true);
        const started = hasAnonId();
        setHasStarted(started);

        const byStatus = await getBookmarksByStatus();
        const allIds = Array.from(
          new Set<number>([
            ...byStatus.want.map((b: Bookmark) => b.activity_id),
            ...byStatus.registered.map((b: Bookmark) => b.activity_id),
            ...byStatus.done.map((b: Bookmark) => b.activity_id),
          ])
        );

        if (allIds.length === 0) {
          if (!cancelled) {
            setGrouped({ want: [], registered: [], done: [] });
            setLoading(false);
          }
          return;
        }

        const { data, error: fetchErr } = await supabase
          .from('activities')
          .select('*')
          .in('id', allIds);

        if (fetchErr) {
          throw fetchErr;
        }

        const actById = new Map<number, Activity>();
        for (const a of (data ?? []) as Activity[]) {
          actById.set(a.id, a);
        }

        const next: GroupedActivities = {
          want: byStatus.want
            .map((b: Bookmark) => actById.get(b.activity_id))
            .filter((x): x is Activity => Boolean(x)),
          registered: byStatus.registered
            .map((b: Bookmark) => actById.get(b.activity_id))
            .filter((x): x is Activity => Boolean(x)),
          done: byStatus.done
            .map((b: Bookmark) => actById.get(b.activity_id))
            .filter((x): x is Activity => Boolean(x)),
        };

        if (!cancelled) {
          setGrouped(next);
          setLoading(false);
        }
      } catch (e) {
        console.error('[MePage] load error:', e);
        if (!cancelled) {
          setError('載入收藏時出了點問題,稍後再試試看 🌿');
          setLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const totalCount =
    grouped.want.length + grouped.registered.length + grouped.done.length;

  return (
    <>
      <Header />
      <main className="max-w-6xl mx-auto px-5 md:px-8 py-8 md:py-12">
        <div className="mb-8 md:mb-10">
          <h1 className="font-display text-2xl md:text-3xl font-medium text-ink mb-2">
            我的樂活人生
          </h1>
          <p className="text-[14px] md:text-[15px] text-ink-muted leading-relaxed">
            收藏你想去、已報名、去過的活動。慢慢累積,這就是你生活的樣子。
          </p>
        </div>

        {loading && (
          <div className="py-16 text-center text-ink-muted text-[14px]">
            載入中...
          </div>
        )}

        {!loading && error && (
          <div className="py-12 text-center">
            <p className="text-ink-muted text-[14px]">{error}</p>
          </div>
        )}

        {!loading && !error && totalCount === 0 && (
          <EmptyState hasStarted={hasStarted} />
        )}

        {!loading && !error && totalCount > 0 && (
          <div className="space-y-10 md:space-y-12">
            {BOOKMARK_ORDER.map((status) => {
              const items = grouped[status];
              if (items.length === 0) return null;
              return (
                <section key={status}>
                  <div className="flex items-baseline gap-3 mb-4 md:mb-5">
                    <h2 className="font-display text-xl md:text-[22px] font-medium text-ink">
                      {BOOKMARK_LABEL[status]}
                    </h2>
                    <span className="text-[13px] text-ink-faded">
                      {items.length} 場
                    </span>
                  </div>
                  <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
                    {items.map((a) => (
                      <ActivityCard key={a.id} activity={a} />
                    ))}
                  </div>
                </section>
              );
            })}
          </div>
        )}
      </main>
    </>
  );
}

function EmptyState({ hasStarted }: { hasStarted: boolean }) {
  return (
    <div className="rounded-2xl border border-black/5 bg-paper-raised p-8 md:p-12 text-center">
      <div className="max-w-md mx-auto">
        <div className="w-14 h-14 rounded-full bg-moss-50 text-moss-700 flex items-center justify-center mx-auto mb-4">
          <svg
            viewBox="0 0 24 24"
            className="w-6 h-6"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden
          >
            <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" />
          </svg>
        </div>
        <h2 className="font-display text-lg md:text-xl font-medium text-ink mb-2">
          {hasStarted ? '還沒收藏任何活動' : '這裡會變成你的樂活人生'}
        </h2>
        <p className="text-[14px] text-ink-muted leading-relaxed mb-6">
          在活動卡片上點愛心,就能標記「想去」、「已報名」或「去過了」。
          一年後你再打開這裡,會看到自己走過幾場、試過幾種新體驗。
        </p>
        <Link
          href="/"
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-full bg-moss-700 text-[#faf4e6] text-[14px] font-medium hover:bg-moss-500 transition-colors"
        >
          去逛逛活動
          <span aria-hidden>→</span>
        </Link>
      </div>
    </div>
  );
}
