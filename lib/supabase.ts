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
  if (activity.event_type === 'recurring') {
    return `${activity.recurring_rule || ''} ${activity.start_time?.substring(0, 5) || ''}-${activity.end_time?.substring(0, 5) || ''}`;
  }
  if (activity.start_date) {
    const date = new Date(activity.start_date);
    const month = date.getMonth() + 1;
    const day = date.getDate();
    const weekdays = ['日', '一', '二', '三', '四', '五', '六'];
    const weekday = weekdays[date.getDay()];
    return `${month}/${day} (${weekday}) ${activity.start_time?.substring(0, 5) || ''}-${activity.end_time?.substring(0, 5) || ''}`;
  }
  return '';
}

export function formatCost(activity: Activity): string {
  if (activity.cost === 0) return '免費';
  return `NT$ ${activity.cost.toLocaleString()}`;
}
