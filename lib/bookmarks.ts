// 樂活卡卡 — 豆瓣式個人收藏功能 (client-only)
//
// 識別方式:anon_id(client 產生的 UUID,存 localStorage)
// 未來可接 LIFF 登入,把 anon_id 換成 LINE userId。
//
// 三種狀態:want / registered / done
// 對應:想去 / 已報名 / 去過了
//
// ⚠️ 這個檔案只能在 Client Component 使用(用到 localStorage)

import { supabase } from './supabase';

const ANON_ID_KEY = 'lohascard_anon_id';

export type BookmarkStatus = 'want' | 'registered' | 'done';

export const BOOKMARK_LABEL: Record<BookmarkStatus, string> = {
  want: '想去',
  registered: '已報名',
  done: '去過了',
};

export const BOOKMARK_ORDER: BookmarkStatus[] = ['want', 'registered', 'done'];

export interface Bookmark {
  id: number;
  anon_id: string;
  activity_id: number;
  status: BookmarkStatus;
  note: string | null;
  rating: number | null;
  created_at: string;
  updated_at: string;
}

// ─── anon_id 管理 ────────────────────────────────────────

/** 取得當下 user 的 anon_id,沒有就產生一個並存到 localStorage */
export function getAnonId(): string {
  if (typeof window === 'undefined') return '';
  let id = window.localStorage.getItem(ANON_ID_KEY);
  if (!id) {
    id = crypto.randomUUID();
    window.localStorage.setItem(ANON_ID_KEY, id);
  }
  return id;
}

/** 檢查是否已有 anon_id(不會自動產生) */
export function hasAnonId(): boolean {
  if (typeof window === 'undefined') return false;
  return !!window.localStorage.getItem(ANON_ID_KEY);
}

/** 清除 anon_id(debug 用,使用者「忘記我」也可呼叫) */
export function clearAnonId(): void {
  if (typeof window === 'undefined') return;
  window.localStorage.removeItem(ANON_ID_KEY);
}

// ─── 收藏操作 ────────────────────────────────────────────

/** 取得單一活動的收藏狀態(沒收藏回 null) */
export async function getBookmark(activityId: number): Promise<Bookmark | null> {
  const anonId = getAnonId();
  if (!anonId) return null;
  const { data, error } = await supabase
    .from('user_bookmarks')
    .select('*')
    .eq('anon_id', anonId)
    .eq('activity_id', activityId)
    .maybeSingle();
  if (error) {
    console.error('[bookmarks] getBookmark error:', error);
    return null;
  }
  return data as Bookmark | null;
}

/** 設定/更新一筆收藏(upsert) */
export async function setBookmark(
  activityId: number,
  status: BookmarkStatus
): Promise<Bookmark | null> {
  const anonId = getAnonId();
  if (!anonId) return null;
  const { data, error } = await supabase
    .from('user_bookmarks')
    .upsert(
      {
        anon_id: anonId,
        activity_id: activityId,
        status,
        updated_at: new Date().toISOString(),
      },
      { onConflict: 'anon_id,activity_id' }
    )
    .select()
    .single();
  if (error) {
    console.error('[bookmarks] setBookmark error:', error);
    return null;
  }
  return data as Bookmark;
}

/** 移除收藏 */
export async function deleteBookmark(activityId: number): Promise<boolean> {
  const anonId = getAnonId();
  if (!anonId) return false;
  const { error } = await supabase
    .from('user_bookmarks')
    .delete()
    .eq('anon_id', anonId)
    .eq('activity_id', activityId);
  if (error) {
    console.error('[bookmarks] deleteBookmark error:', error);
    return false;
  }
  return true;
}

/** 取得當下 user 所有收藏 */
export async function getAllBookmarks(): Promise<Bookmark[]> {
  const anonId = getAnonId();
  if (!anonId) return [];
  const { data, error } = await supabase
    .from('user_bookmarks')
    .select('*')
    .eq('anon_id', anonId)
    .order('updated_at', { ascending: false });
  if (error) {
    console.error('[bookmarks] getAllBookmarks error:', error);
    return [];
  }
  return (data as Bookmark[]) ?? [];
}

/** 依狀態分組取得收藏 */
export async function getBookmarksByStatus(): Promise<Record<BookmarkStatus, Bookmark[]>> {
  const all = await getAllBookmarks();
  const grouped: Record<BookmarkStatus, Bookmark[]> = {
    want: [],
    registered: [],
    done: [],
  };
  for (const b of all) {
    grouped[b.status].push(b);
  }
  return grouped;
}

// ─── 打星 + 寫心得(Phase 2)────────────────────────────

/** 設定評分(1-5)。傳 null 清空 */
export async function setRating(
  activityId: number,
  rating: number | null
): Promise<Bookmark | null> {
  const anonId = getAnonId();
  if (!anonId) return null;
  if (rating !== null && (rating < 1 || rating > 5)) {
    console.error('[bookmarks] rating must be 1-5, got:', rating);
    return null;
  }
  const { data, error } = await supabase
    .from('user_bookmarks')
    .update({
      rating,
      updated_at: new Date().toISOString(),
    })
    .eq('anon_id', anonId)
    .eq('activity_id', activityId)
    .select()
    .single();
  if (error) {
    console.error('[bookmarks] setRating error:', error);
    return null;
  }
  return data as Bookmark;
}

/** 設定心得文字。傳 null 或空字串清空 */
export async function setNote(
  activityId: number,
  note: string | null
): Promise<Bookmark | null> {
  const anonId = getAnonId();
  if (!anonId) return null;
  const cleaned = note && note.trim() ? note.trim() : null;
  const { data, error } = await supabase
    .from('user_bookmarks')
    .update({
      note: cleaned,
      updated_at: new Date().toISOString(),
    })
    .eq('anon_id', anonId)
    .eq('activity_id', activityId)
    .select()
    .single();
  if (error) {
    console.error('[bookmarks] setNote error:', error);
    return null;
  }
  return data as Bookmark;
}
