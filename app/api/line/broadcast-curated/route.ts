// 樂活卡卡 — 本週精選 LINE 推播 endpoint
//
// 用法(在 Vercel Function 上):
//   POST /api/line/broadcast-curated?mode=self       → push 給 LINE_TEST_USER_ID(自己測試用)
//   POST /api/line/broadcast-curated?mode=broadcast  → 廣播給全體 OA 好友
//
// 驗證:必須帶 header `x-broadcast-secret: <LINE_BROADCAST_SECRET>`
//
// 訊息格式:Flex Carousel
//   - top 5 筆 curated 活動(按 start_date 升冪)每筆一張 bubble
//   - 最後一張「看完整本週精選」bubble 連到首頁
//
// 額度:每月 200 則推播(免費版),每次 broadcast 算 1 則,每次 push 算 1 則
//
// 環境變數:
//   LINE_CHANNEL_ACCESS_TOKEN  — 和 webhook 共用
//   LINE_BROADCAST_SECRET      — 自訂隨機字串,避免 endpoint 被亂打
//   LINE_TEST_USER_ID          — mode=self 的目標(從 webhook 的 "myid" 指令取得)

import { NextRequest, NextResponse } from 'next/server';
import { supabase, Activity, CATEGORIES } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const LINE_PUSH_ENDPOINT = 'https://api.line.me/v2/bot/message/push';
const LINE_BROADCAST_ENDPOINT = 'https://api.line.me/v2/bot/message/broadcast';
const SITE_URL = 'https://lohascard.vercel.app';

const WEEKDAY_ZH = ['日', '一', '二', '三', '四', '五', '六'];

function formatDate(s: string | null): string {
  if (!s) return '';
  const d = new Date(s + 'T00:00:00+08:00');
  const mo = d.getMonth() + 1;
  const day = d.getDate();
  const w = WEEKDAY_ZH[d.getDay()];
  return `${mo}/${day}(${w})`;
}

function utmSuffix(): string {
  const campaign = new Date().toISOString().slice(0, 10);
  return `?utm_source=line&utm_medium=weekly_pick&utm_campaign=${campaign}`;
}

// LINE Flex Message JSON 型別複雜,就用 any 跳過(reference: https://developers.line.biz/flex-simulator/)
function buildActivityBubble(a: Activity): Record<string, unknown> {
  const dateStr = formatDate(a.start_date);
  const location = [a.district, a.location_name].filter(Boolean).join(' · ');
  const subtitle = [dateStr, location].filter(Boolean).join(' · ');
  const category = a.category ? CATEGORIES[a.category] : null;
  const catLabel = category?.label || '活動';
  const detailUrl = `${SITE_URL}/activities/${a.id}${utmSuffix()}`;

  const bubble: Record<string, unknown> = {
    type: 'bubble',
    size: 'kilo',
    body: {
      type: 'box',
      layout: 'vertical',
      spacing: 'sm',
      contents: [
        { type: 'text', text: catLabel, size: 'xs', color: '#9E7A5A', weight: 'bold' },
        { type: 'text', text: a.title, weight: 'bold', size: 'md', wrap: true, maxLines: 3 },
        {
          type: 'text',
          text: subtitle || '請查看詳情',
          size: 'xs',
          color: '#5a5a5a',
          wrap: true,
          margin: 'sm',
        },
      ],
    },
    footer: {
      type: 'box',
      layout: 'vertical',
      contents: [
        {
          type: 'button',
          action: { type: 'uri', label: '看詳情', uri: detailUrl },
          style: 'primary',
          color: '#5a7a3e',
          height: 'sm',
        },
      ],
    },
  };

  // LINE Flex image 只接受 PNG/JPEG(SVG 不行)。跳過 .svg 和 null。
  // 我們站內 /images/categories/*.svg fallback 是前端用的,推播用不了;沒圖就 body-only 版型
  if (
    a.image_url &&
    /^https?:\/\//.test(a.image_url) &&
    !a.image_url.toLowerCase().endsWith('.svg')
  ) {
    bubble.hero = {
      type: 'image',
      url: a.image_url,
      size: 'full',
      aspectRatio: '5:3',
      aspectMode: 'cover',
    };
  }

  return bubble;
}

function buildSeeAllBubble(remaining: number): Record<string, unknown> {
  return {
    type: 'bubble',
    size: 'kilo',
    body: {
      type: 'box',
      layout: 'vertical',
      spacing: 'md',
      contents: [
        { type: 'text', text: 'MORE PICKS', size: 'xs', color: '#9E7A5A', weight: 'bold' },
        {
          type: 'text',
          text: `還有 ${remaining} 個好活動`,
          weight: 'bold',
          size: 'xl',
          wrap: true,
        },
        {
          type: 'text',
          text: '去首頁看完整本週精選',
          size: 'sm',
          color: '#5a5a5a',
          margin: 'md',
          wrap: true,
        },
      ],
    },
    footer: {
      type: 'box',
      layout: 'vertical',
      contents: [
        {
          type: 'button',
          action: { type: 'uri', label: '看完整精選 →', uri: `${SITE_URL}/${utmSuffix()}` },
          style: 'primary',
          color: '#5a7a3e',
          height: 'sm',
        },
      ],
    },
  };
}

export async function POST(req: NextRequest) {
  // 1. 檢查必要環境變數 + 驗證 secret
  const BROADCAST_SECRET = process.env.LINE_BROADCAST_SECRET;
  const ACCESS_TOKEN = process.env.LINE_CHANNEL_ACCESS_TOKEN;
  if (!BROADCAST_SECRET || !ACCESS_TOKEN) {
    return NextResponse.json({ ok: false, error: 'missing_env' }, { status: 500 });
  }
  const givenSecret = req.headers.get('x-broadcast-secret');
  if (givenSecret !== BROADCAST_SECRET) {
    return NextResponse.json({ ok: false, error: 'unauthorized' }, { status: 401 });
  }

  // 2. mode 參數
  const mode = req.nextUrl.searchParams.get('mode') || 'self';
  if (mode !== 'self' && mode !== 'broadcast') {
    return NextResponse.json({ ok: false, error: 'invalid_mode' }, { status: 400 });
  }

  // 3. 撈 curated(跟首頁 getCuratedActivities 同邏輯,未過期 + limit 12)
  const today = new Date().toISOString().slice(0, 10);
  const { data, error } = await supabase
    .from('activities')
    .select('*')
    .eq('status', 'active')
    .eq('is_curated', true)
    .or(
      `event_type.eq.recurring,` +
        `end_date.gte.${today},` +
        `and(end_date.is.null,start_date.gte.${today}),` +
        `and(end_date.is.null,start_date.is.null)`
    )
    .order('start_date', { ascending: true, nullsFirst: false })
    .order('id', { ascending: true })
    .limit(12);
  if (error) {
    return NextResponse.json(
      { ok: false, error: 'db_error', detail: error.message },
      { status: 500 }
    );
  }
  const curated = (data as Activity[]) || [];
  if (curated.length === 0) {
    return NextResponse.json({ ok: false, error: 'no_curated' }, { status: 404 });
  }

  // 4. 組 Flex Carousel(top 5 + see-all)
  const top5 = curated.slice(0, 5);
  const remaining = Math.max(0, curated.length - 5);
  const bubbles: Record<string, unknown>[] = top5.map(buildActivityBubble);
  if (remaining > 0) {
    bubbles.push(buildSeeAllBubble(remaining));
  }
  // altText 是推播通知裡看到的預覽文字,上限 400 字
  const altText = `本週精選:${top5.map((a) => a.title).join(' / ')}`.slice(0, 395);

  const flexMessage = {
    type: 'flex',
    altText,
    contents: {
      type: 'carousel',
      contents: bubbles,
    },
  };

  // 5. 呼叫 LINE API
  const payload: Record<string, unknown> = { messages: [flexMessage] };
  let endpoint = LINE_BROADCAST_ENDPOINT;
  if (mode === 'self') {
    const userId = process.env.LINE_TEST_USER_ID;
    if (!userId) {
      return NextResponse.json(
        { ok: false, error: 'missing_test_user_id' },
        { status: 500 }
      );
    }
    endpoint = LINE_PUSH_ENDPOINT;
    payload.to = userId;
  }

  const res = await fetch(endpoint, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${ACCESS_TOKEN}`,
    },
    body: JSON.stringify(payload),
  });
  const lineBody = await res.text().catch(() => '');
  if (!res.ok) {
    return NextResponse.json(
      { ok: false, error: 'line_api', status: res.status, detail: lineBody },
      { status: 500 }
    );
  }

  return NextResponse.json({
    ok: true,
    mode,
    bubblesSent: bubbles.length,
    curatedIds: top5.map((a) => a.id),
    altText,
  });
}
