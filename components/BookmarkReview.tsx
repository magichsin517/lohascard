'use client';

// 樂活卡卡 — 打星 + 寫心得(Phase 2)
//
// 只對「去過了」(status='done')的 bookmark 顯示。
// - 1-5 顆星,點一下即儲存;再點同一顆 = 清空
// - 心得預設收合;點「寫下心得」展開 textarea + 儲存按鈕
// - 55+ 友善:星星大、字體大、儲存狀態清楚顯示

import { useState } from 'react';
import { setRating, setNote } from '@/lib/bookmarks';

interface Props {
  activityId: number;
  initialRating: number | null;
  initialNote: string | null;
}

export default function BookmarkReview({
  activityId,
  initialRating,
  initialNote,
}: Props) {
  const [rating, setRatingState] = useState<number | null>(initialRating);
  const [hover, setHover] = useState<number>(0);
  const [note, setNoteState] = useState<string>(initialNote ?? '');
  const [editing, setEditing] = useState<boolean>(false);
  const [saving, setSaving] = useState<boolean>(false);
  const [justSaved, setJustSaved] = useState<boolean>(false);

  const handleStarClick = async (n: number) => {
    // 再點同一顆 = 清空
    const newRating = rating === n ? null : n;
    setRatingState(newRating); // optimistic
    setSaving(true);
    const result = await setRating(activityId, newRating);
    setSaving(false);
    if (result) {
      setJustSaved(true);
      setTimeout(() => setJustSaved(false), 1500);
    }
  };

  const handleNoteSave = async () => {
    setSaving(true);
    const cleaned = note.trim() || null;
    const result = await setNote(activityId, cleaned);
    setSaving(false);
    if (result) {
      setNoteState(cleaned ?? '');
      setEditing(false);
      setJustSaved(true);
      setTimeout(() => setJustSaved(false), 1500);
    }
  };

  const handleNoteCancel = () => {
    setNoteState(initialNote ?? '');
    setEditing(false);
  };

  const hasNote = !editing && note.trim().length > 0;

  return (
    <div className="px-4 py-3.5 bg-paper-raised rounded-2xl border border-black/5 space-y-3">
      {/* 星星列 */}
      <div className="flex items-center gap-1.5" onMouseLeave={() => setHover(0)}>
        {[1, 2, 3, 4, 5].map((n) => {
          const filled = (hover || rating || 0) >= n;
          return (
            <button
              key={n}
              type="button"
              onClick={() => handleStarClick(n)}
              onMouseEnter={() => setHover(n)}
              aria-label={`${n} 顆星`}
              className={`p-1 -m-1 transition-colors ${
                filled ? 'text-sun-500' : 'text-ink-faded hover:text-sun-500'
              }`}
            >
              <svg
                viewBox="0 0 24 24"
                className="w-7 h-7"
                fill={filled ? 'currentColor' : 'none'}
                stroke="currentColor"
                strokeWidth={1.8}
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden
              >
                <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
              </svg>
            </button>
          );
        })}
        {rating !== null && (
          <span className="ml-2 text-[13.5px] text-ink-muted">{rating} / 5</span>
        )}
        {justSaved && (
          <span className="ml-auto text-[12.5px] text-moss-700">已儲存 ✓</span>
        )}
      </div>

      {/* 心得 */}
      {!editing && !hasNote && (
        <button
          type="button"
          onClick={() => setEditing(true)}
          className="text-[14px] text-moss-700 hover:text-moss-500 inline-flex items-center gap-1.5"
        >
          <svg viewBox="0 0 24 24" className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M12 20h9" />
            <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
          </svg>
          寫下心得
        </button>
      )}

      {!editing && hasNote && (
        <div className="space-y-2">
          <p className="text-[14.5px] text-ink-soft leading-relaxed whitespace-pre-line">
            {note}
          </p>
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="text-[13.5px] text-ink-muted hover:text-ink inline-flex items-center gap-1"
          >
            編輯心得 →
          </button>
        </div>
      )}

      {editing && (
        <div className="space-y-2">
          <textarea
            value={note}
            onChange={(e) => setNoteState(e.target.value)}
            placeholder="這場活動怎麼樣?寫幾句記一下..."
            className="w-full min-h-[80px] p-3 rounded-lg border border-black/10 focus:border-moss-500 focus:outline-none text-[15px] text-ink placeholder:text-ink-faded bg-paper leading-relaxed resize-y"
            maxLength={1000}
          />
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleNoteSave}
              disabled={saving}
              className="text-[14px] px-4 py-1.5 rounded-full bg-moss-700 text-[#faf4e6] hover:bg-moss-500 disabled:opacity-60 disabled:cursor-wait transition-colors"
            >
              {saving ? '儲存中...' : '儲存'}
            </button>
            <button
              type="button"
              onClick={handleNoteCancel}
              className="text-[14px] px-4 py-1.5 rounded-full text-ink-muted hover:text-ink hover:bg-paper-sunken transition-colors"
            >
              取消
            </button>
            <span className="ml-auto text-[12px] text-ink-faded">
              {note.length} / 1000
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
