import { createClient } from '@supabase/supabase-js';

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!;

export const supabase = createClient(supabaseUrl, supabaseKey);

// 活動的 TypeScript 型別定義 (跟 DB 的 schema 對應)
export type Category = 'sports' | 'learning' | 'health' | 'culture' | 'travel' | 'social' | 'volunteer';
export type EventType = 'single' | 'recurring';
export type SignupMethod = 'phone' | 'online' | 'walk_in' | 'email' | 'none';

export interface Activity {
  id: number;
  title: string;
  description: string | null;
  summary: string | null;
  organizer_name: string | null;
  event_type: EventType;
  start_date: string | null;
  end_date: string | null;
  start_time: string | null;
  end_time: string | null;
  recurring_rule: string | null;
  location_name: string | null;
  address: string | null;
  city: string | null;
  district: string | null;
  category: Category | null;
  tags: string[];
  target_audience: string | null;
  cost: number;
  cost_note: string | null;
  signup_method: SignupMethod | null;
  signup_url: string | null;
  signup_phone: string | null;
  signup_deadline: string | null;
  capacity: number | null;
  image_url: string | null;
  source_url: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

// 分類的中文名稱和顏色
export const CATEGORIES: Record<Category, { label: string; color: string; bg: string; text: string }> = {
  sports:    { label: '運動',     color: 'moss', bg: 'bg-moss-50',  text: 'text-moss-700' },
  learning:  { label: '學習',     color: 'plum', bg: 'bg-plum-50',  text: 'text-plum-700' },
  health:    { label: '健康',     color: 'clay', bg: 'bg-clay-50',  text: 'text-clay-700' },
  culture:   { label: '文娛',     color: 'sun',  bg: 'bg-sun-50',   text: 'text-sun-700' },
  travel:    { label: '旅遊',     color: 'sky',  bg: 'bg-sky-50',   text: 'text-sky-700' },
  social:    { label: '社交',     color: 'plum', bg: 'bg-plum-50',  text: 'text-plum-700' },
  volunteer: { label: '志願服務', color: 'moss', bg: 'bg-moss-50',  text: 'text-moss-700' },
};

// 費用標籤(與 activities.tags 陣列中的字串對應)
// 規則:cost=0 → 免費, 1~300 → 小額收費, >300 → 收費
export type PricingTier = '免費' | '小額收費' | '收費';
export const PRICING_TIERS: PricingTier[] = ['免費', '小額收費', '收費'];
export const PRICING_STYLE: Record<PricingTier, { bg: string; text: string }> = {
  '免費':     { bg: 'bg-moss-50', text: 'text-moss-700' },
  '小額收費': { bg: 'bg-sun-50',  text: 'text-sun-700' },
  '收費':     { bg: 'bg-clay-50', text: 'text-clay-700' },
};

export function pricingTierFromCost(cost: number): PricingTier {
  if (cost <= 0) return '免費';
  if (cost <= 300) return '小額收費';
  return '收費';
}

export function pricingTierOf(activity: Pick<Activity, 'tags' | 'cost'>): PricingTier {
  const fromTag = activity.tags?.find((t) => (PRICING_TIERS as string[]).includes(t)) as PricingTier | undefined;
  return fromTag ?? pricingTierFromCost(activity.cost);
}

// 格式化日期/時間的小工具
export function formatEventTime(activity: Activity): string {
  const startT = activity.start_time?.substring(0, 5) || '';
  const endT = activity.end_time?.substring(0, 5) || '';
  const timeRange = startT && endT ? `${startT}-${endT}` : startT || endT || '';

  if (activity.event_type === 'recurring') {
    const rule = activity.recurring_rule || '';
    return [rule, timeRange].filter(Boolean).join(' ').trim();
  }
  if (activity.start_date) {
    const date = new Date(activity.start_date);
    const month = date.getMonth() + 1;
    const day = date.getDate();
    const weekdays = ['日', '一', '二', '三', '四', '五', '六'];
    const weekday = weekdays[date.getDay()];
    const datePart = `${month}/${day} (${weekday})`;
    return [datePart, timeRange].filter(Boolean).join(' ').trim();
  }
  return '';
}

export function formatCost(activity: Activity): string {
  if (activity.cost === 0) return '免費';
  return `NT$ ${activity.cost.toLocaleString()}`;
}

// ─── 多場次合併 ──────────────────────────────────────────────
// 同一活動(title + location_name + organizer_name 完全相同)
// 可能因為 PDF 解析被拆成多筆 row。前端把他們合併成一組顯示。

export type ActivityGroup = {
  primary: Activity;       // 代表場次 (最近即將到來的那一場;沒有就用第一筆)
  sessions: Activity[];    // 所有場次 (含 primary),依時間 ASC 排序
};

function normalizeKeyPart(s: string | null | undefined): string {
  return (s || '')
    .trim()
    .replace(/\s+/g, '')
    // 把各種 dash 變體統一成 ASCII hyphen-minus,避免同一活動因為 dash 不同被分成兩組
    // –(en dash U+2013)、—(em dash U+2014)、−(minus U+2212)、‒‑‐ 各種 unicode hyphen
    .replace(/[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]/g, '-')
    // 統一台/臺(scraper 已處理縣市,但標題/中心名可能混用)
    .replace(/臺/g, '台');
}

export function groupKey(a: Pick<Activity, 'title' | 'location_name' | 'organizer_name'>): string {
  return [
    normalizeKeyPart(a.title),
    normalizeKeyPart(a.location_name),
    normalizeKeyPart(a.organizer_name),
  ].join('|');
}

// 排序比較:沒日期的排最後;有日期的按 start_date → start_time 升冪。
// 兩邊都沒日期時仍要比 start_time(PDF 解析來的 recurring 多屬此類)。
function compareByStart(a: Activity, b: Activity): number {
  if (!a.start_date && b.start_date) return 1;
  if (a.start_date && !b.start_date) return -1;
  if (a.start_date && b.start_date && a.start_date !== b.start_date) {
    return a.start_date < b.start_date ? -1 : 1;
  }
  const at = a.start_time || '';
  const bt = b.start_time || '';
  if (at === bt) return 0;
  return at < bt ? -1 : 1;
}

export function groupActivities(activities: Activity[]): ActivityGroup[] {
  const today = new Date().toISOString().slice(0, 10);
  const buckets = new Map<string, Activity[]>();

  for (const a of activities) {
    // 不管 event_type,同標題+地點+主辦就是同一活動
    // (PDF 解析時 event_type 有時會誤標成 recurring,所以不以此判斷)
    const key = groupKey(a);
    const arr = buckets.get(key) || [];
    arr.push(a);
    buckets.set(key, arr);
  }

  const groups: ActivityGroup[] = [];
  for (const sessions of buckets.values()) {
    const sorted = [...sessions].sort(compareByStart);
    // primary = 最近即將到來 (start_date >= today);都過期就用第一個
    const upcoming = sorted.find((s) => !s.start_date || s.start_date >= today);
    const primary = upcoming || sorted[0];
    groups.push({ primary, sessions: sorted });
  }

  // 群組之間再按 primary 的開始時間排序,維持原本 UI 的「最近的在前」
  groups.sort((g1, g2) => compareByStart(g1.primary, g2.primary));
  return groups;
}
