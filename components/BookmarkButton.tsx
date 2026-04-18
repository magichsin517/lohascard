'use client';

import { useState, useEffect, useRef } from 'react';
import {
  BOOKMARK_LABEL,
  BOOKMARK_ORDER,
  BookmarkStatus,
  deleteBookmark,
  getBookmark,
  setBookmark,
} from '@/lib/bookmarks';

interface Props {
  activityId: number;
  /** 尺寸,預設 md */
  size?: 'sm' | 'md';
  /** 在 card 上會用 absolute 浮在右上;在詳細頁用 inline */
  variant?: 'overlay' | 'inline';
}

export default function BookmarkButton({
  activityId,
  size = 'md',
  variant = 'overlay',
}: Props) {
  const [status, setStatus] = useState<BookmarkStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // 初始載入
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const bm = await getBookmark(activityId);
      if (!cancelled) {
        setStatus(bm?.status ?? null);
        setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activityId]);

  // 點外面關 menu
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const handleToggle = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setOpen((v) => !v);
  };

  const handleSelect = async (e: React.MouseEvent, newStatus: BookmarkStatus) => {
    e.preventDefault();
    e.stopPropagation();
    setOpen(false);
    // 如果點同一個狀態 = 取消
    if (newStatus === status) {
      setStatus(null);
      await deleteBookmark(activityId);
      return;
    }
    // optimistic
    setStatus(newStatus);
    const result = await setBookmark(activityId, newStatus);
    if (!result) {
      // 失敗回復(非致命)
      console.warn('[BookmarkButton] set failed, reverting');
    }
  };

  const handleRemove = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setOpen(false);
    setStatus(null);
    await deleteBookmark(activityId);
  };

  const isBookmarked = status !== null;
  const iconSize = size === 'sm' ? 'w-7 h-7' : 'w-9 h-9';
  const iconInner = size === 'sm' ? 'w-3.5 h-3.5' : 'w-4 h-4';

  // 浮在卡片右上角
  const posClass =
    variant === 'overlay'
      ? 'absolute top-3 right-3 z-10'
      : 'inline-block';

  return (
    <div className={posClass} ref={menuRef}>
      <button
        type="button"
        onClick={handleToggle}
        aria-label={
          isBookmarked ? `已收藏(${BOOKMARK_LABEL[status!]})` : '收藏這個活動'
        }
        className={[
          iconSize,
          'flex items-center justify-center rounded-full transition-all',
          'backdrop-blur-sm shadow-sm',
          isBookmarked
            ? 'bg-moss-500 text-white hover:bg-moss-700'
            : 'bg-white/90 text-ink-muted hover:text-moss-700 hover:bg-white',
          loading ? 'opacity-60 cursor-wait' : 'cursor-pointer',
        ].join(' ')}
        disabled={loading}
      >
        {/* 愛心 icon (填滿 / 描邊) */}
        <svg
          viewBox="0 0 24 24"
          className={iconInner}
          fill={isBookmarked ? 'currentColor' : 'none'}
          stroke="currentColor"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" />
        </svg>
      </button>

      {/* 下拉選單 */}
      {open && (
        <div
          className={[
            'absolute z-20 mt-2 w-36 rounded-xl bg-white shadow-lg border border-black/5 py-1.5 overflow-hidden',
            variant === 'overlay' ? 'right-0' : 'left-0',
          ].join(' ')}
          onClick={(e) => e.stopPropagation()}
        >
          {BOOKMARK_ORDER.map((s) => {
            const active = status === s;
            return (
              <button
                key={s}
                type="button"
                onClick={(e) => handleSelect(e, s)}
                className={[
                  'w-full text-left px-3.5 py-2 text-[13.5px] flex items-center gap-2 transition-colors',
                  active
                    ? 'bg-moss-50 text-moss-700 font-medium'
                    : 'text-ink-soft hover:bg-paper-sunken',
                ].join(' ')}
              >
                <span className={`w-1.5 h-1.5 rounded-full ${active ? 'bg-moss-500' : 'bg-ink-faded'}`} />
                {BOOKMARK_LABEL[s]}
              </button>
            );
          })}
          {isBookmarked && (
            <>
              <div className="my-1 border-t border-black/5" />
              <button
                type="button"
                onClick={handleRemove}
                className="w-full text-left px-3.5 py-2 text-[13px] text-ink-muted hover:bg-paper-sunken flex items-center gap-2"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-transparent" />
                取消收藏
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
