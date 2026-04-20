// 樂活卡卡 — LINE Messaging API Webhook
//
// LINE 平台在使用者傳訊息給 @388pvphx 時會 POST 到這裡。
// 我們驗證簽名 → 解析事件 → 用 Q&A bank 比對 → 呼叫 LINE reply API 回覆。
//
// 環境變數(在 Vercel Project Settings → Environment Variables 加):
//   LINE_CHANNEL_SECRET        — 來自 OA Manager → 設定 → Messaging API
//   LINE_CHANNEL_ACCESS_TOKEN  — 來自 LINE Developers Console → Messaging API 分頁
//
// LINE 平台的 Webhook URL 設定:
//   https://lohascard.vercel.app/api/line/webhook

import { NextRequest, NextResponse } from 'next/server';
import crypto from 'crypto';
import { matchQA, WELCOME_REPLY } from '@/lib/line-qa';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const LINE_REPLY_ENDPOINT = 'https://api.line.me/v2/bot/message/reply';

function verifySignature(body: string, signature: string | null, secret: string): boolean {
  if (!signature) return false;
  const expected = crypto.createHmac('sha256', secret).update(body).digest('base64');
  // 用 timingSafeEqual 避免 timing attack
  const a = Buffer.from(expected);
  const b = Buffer.from(signature);
  if (a.length !== b.length) return false;
  return crypto.timingSafeEqual(a, b);
}

interface LineTextMessage {
  type: 'text';
  id: string;
  text: string;
}

interface LineMessageEvent {
  type: 'message';
  replyToken: string;
  source: { userId?: string; type: string };
  message: LineTextMessage | { type: string };
}

interface LineFollowEvent {
  type: 'follow';
  replyToken: string;
  source: { userId?: string; type: string };
}

type LineEvent = LineMessageEvent | LineFollowEvent | { type: string; replyToken?: string };

async function replyText(replyToken: string, text: string, accessToken: string): Promise<void> {
  const res = await fetch(LINE_REPLY_ENDPOINT, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify({
      replyToken,
      messages: [{ type: 'text', text }],
    }),
  });
  if (!res.ok) {
    // 原本只 console.error 讓錯誤被吞掉 — 2026-04-20 踩到:rotate LINE token 後忘記更新
    // Vercel env,reply API 401,webhook 還是回 200 給 LINE、LINE 標已讀但使用者沒收到
    // 回覆,極難從外部 debug。改 throw 讓 Vercel runtime log 看到 loud error;外層
    // events.map 的 try/catch 仍會攔住,單一 event 失敗不影響 webhook 整體狀態。
    const errBody = await res.text().catch(() => '');
    const msg = `[line-webhook] reply failed: ${res.status} ${errBody}`;
    console.error(msg);
    throw new Error(msg);
  }
}

export async function POST(req: NextRequest) {
  const CHANNEL_SECRET = process.env.LINE_CHANNEL_SECRET;
  const CHANNEL_ACCESS_TOKEN = process.env.LINE_CHANNEL_ACCESS_TOKEN;

  if (!CHANNEL_SECRET || !CHANNEL_ACCESS_TOKEN) {
    console.error('[line-webhook] missing env vars');
    // 仍然回 200,避免 LINE 平台不斷重試;但在 log 留紀錄
    return NextResponse.json({ ok: false, error: 'missing_env' }, { status: 200 });
  }

  const rawBody = await req.text();
  const signature = req.headers.get('x-line-signature');

  if (!verifySignature(rawBody, signature, CHANNEL_SECRET)) {
    console.warn('[line-webhook] invalid signature');
    return NextResponse.json({ ok: false, error: 'invalid_signature' }, { status: 401 });
  }

  let payload: { events?: LineEvent[] };
  try {
    payload = JSON.parse(rawBody);
  } catch {
    return NextResponse.json({ ok: false, error: 'bad_json' }, { status: 400 });
  }

  const events = payload.events ?? [];

  // 並行處理所有事件(LINE 單次可送多個)
  await Promise.all(
    events.map(async (event) => {
      try {
        if (event.type === 'message') {
          const ev = event as LineMessageEvent;
          if (ev.message.type === 'text') {
            const userText = (ev.message as LineTextMessage).text;
            // 暫時性 debug 指令:回傳呼叫者 userId,供推播設定使用。
            // 上線前若擔心被亂用可拿掉,不過 userId 本身不是 secret(只能對特定 channel 用)
            const trimmed = userText.trim().toLowerCase();
            if (trimmed === 'myid' || trimmed === '我的id' || trimmed === 'userid') {
              const uid = ev.source.userId || '(source has no userId, private chat only?)';
              await replyText(ev.replyToken, `你的 LINE userId:\n${uid}`, CHANNEL_ACCESS_TOKEN);
            } else {
              const answer = matchQA(userText);
              await replyText(ev.replyToken, answer, CHANNEL_ACCESS_TOKEN);
            }
          }
          // 其他訊息類型(圖片、貼圖等)暫不處理
        } else if (event.type === 'follow') {
          const ev = event as LineFollowEvent;
          if (ev.replyToken) {
            await replyText(ev.replyToken, WELCOME_REPLY, CHANNEL_ACCESS_TOKEN);
          }
        }
        // 其他事件類型(unfollow、join、leave 等)目前忽略
      } catch (err) {
        console.error('[line-webhook] event handling error:', err);
      }
    })
  );

  return NextResponse.json({ ok: true });
}

// LINE 平台第一次設定 webhook 時會發 GET 來驗證(其實不會,但保留以免未來)
export async function GET() {
  return NextResponse.json({ ok: true, service: 'lohascard-line-webhook' });
}
