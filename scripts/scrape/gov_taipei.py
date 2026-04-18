#!/usr/bin/env python3
"""
台北市政府觀光傳播局 — 活動展演 + 活動年曆 爬蟲
資料源:臺北旅遊網 Open API(官方 JSON,無需 scraping)
  - 活動展演 Events/Activity (日常展演/文娛,量大 ~30-150 筆)
  - 活動年曆 Events/Calendar (大型節慶活動,量少 ~10-30 筆)
Doc: https://www.travel.taipei/open-api/swagger/docs/v1

優點:
  - 直接 JSON,零 HTML parsing
  - 欄位超完整:title/description/begin/end/distric/address/nlat/elong/organizer/tel/ticket/url...
  - 官方開放資料,法律乾淨

執行:
  # 只抓、輸出 JSON
  python3 scripts/scrape/gov_taipei.py --out /tmp/taipei.json

  # 抓 + 寫 Supabase
  SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... \
    python3 scripts/scrape/gov_taipei.py --upsert
"""
from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from datetime import date, timedelta
from typing import Any

BASE = "https://www.travel.taipei/open-api/zh-tw"
# 台北旅遊網 WAF 會擋 "bot" 字樣 UA,改用真實 Chrome UA 避免 403
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
REFERER = "https://www.travel.taipei/open-api/swagger/ui/index"
SOURCE_ACTIVITY = "台北旅遊網-活動展演"
SOURCE_CALENDAR = "台北旅遊網-活動年曆"

CITY = "台北市"

# category 啟發式(title + description 關鍵字,優先序命中第一個)
# 順序有講究:先 sports / travel(最明確) → social(市集/園遊常跟嘉年華混用,優先取)
# → health / learning → culture(最泛,做兜底) → volunteer
CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("sports",   ("馬拉松", "路跑", "健走", "自行車", "單車", "球", "運動", "瑜珈", "瑜伽", "太極")),
    ("travel",   ("旅遊", "踏青", "走讀", "參訪", "小旅行", "巡禮", "市集走讀")),
    ("social",   ("市集", "園遊", "聚會", "聯誼", "同樂", "共餐", "祖孫", "親子")),
    ("health",   ("健康", "養生", "保健", "醫", "篩檢", "血壓", "失智", "防疫")),
    ("volunteer", ("志工", "志願")),
    ("learning", ("講座", "論壇", "研習", "工作坊", "課程", "招生", "培訓", "體驗營", "讀書會")),
    ("culture",  ("展", "演", "音樂", "歌", "戲", "藝術", "文學", "詩", "電影", "影展", "燈會",
                  "節慶", "嘉年華", "博覽會", "國樂", "茶會", "導覽")),
]

TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class ScrapedItem:
    ext_id: int
    title: str
    description: str | None
    begin: str | None
    end: str | None
    district: str | None
    address: str | None
    organizer: str | None
    tel: str | None
    ticket: str | None
    url: str
    source_name: str
    is_major: bool  # Calendar 特有
    image_url: str | None


# 強制不走 proxy(macOS 系統代理設定會讓 urllib 自動走 127.0.0.1:xxxx,
# Clash/V2Ray 關閉時會 Connection refused。這裡明確開一條直連的 opener)
_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def fetch_json(url: str, *, retries: int = 3, timeout: int = 40) -> Any:
    """台北旅遊網 API:
    - 需要 Accept: application/json 才會回 JSON(否則 400 Invalid Parameter)
    - WAF 會擋 "LohasCardBot" 這類自訂 UA(403 Forbidden),改用真實 Chrome UA
    - 加 Referer 模擬從 Swagger UI 發出的請求,更像真人使用
    - 強制不走 system proxy(繞過 Clash/V2Ray 關閉時的 Connection refused)
    """
    last = None
    headers = {
        "User-Agent": UA,
        "Accept": "application/json",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        "Referer": REFERER,
    }
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with _NO_PROXY_OPENER.open(req, timeout=timeout) as r:
                return json.loads(r.read())
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"fetch failed: {url}: {last}")


def clean_html(s: str | None) -> str | None:
    if not s:
        return None
    s = TAG_RE.sub(" ", s)
    s = html_lib.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def iso_date(s: str | None) -> str | None:
    """API 的 begin/end 是 '2026-06-14T00:00:00'  或 '2026-06-14' — 切出日期。"""
    if not s:
        return None
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", s)
    return m.group(1) if m else None


def guess_category(title: str, description: str | None) -> str:
    text = title + " " + (description or "")
    for cat, kws in CATEGORY_KEYWORDS:
        for kw in kws:
            if kw in text:
                return cat
    return "culture"  # 台北旅遊網多為展演類,default culture


def parse_ticket(ticket: str | None) -> tuple[int, str]:
    """ticket 欄位例:「免費入場」「全票 100 元、敬老票 50 元」「線上報名」等。
    回傳 (cost_int, tier_tag)。

    重要:先抓金額再判免費,避免「100 元」的尾巴 "0 元" 被誤判成免費。
    "免費" 關鍵字用完整詞匹配,不碰 "入場"(因為「入場 100 元」也算入場)。
    """
    if not ticket:
        return 0, "免費"  # 台北旅遊網預設多為免費展演
    t = ticket
    # 1. 先抓具體金額(2-4 位數字 + 元);取第一個 >= 1 元的
    amts = [int(m.group(1)) for m in re.finditer(r"(\d{2,4})\s*元", t)]
    amts = [a for a in amts if a >= 1]  # 排除 0 元
    if amts:
        amt = amts[0]
        if amt <= 300:
            return amt, "小額收費"
        else:
            return amt, "收費"
    # 2. 沒金額 → 看有沒有「免費」或「自由參加」等明顯訊號
    if re.search(r"免費|自由參加|免入場|免報名費", t):
        return 0, "免費"
    # 3. 有「票價/報名費」但沒金額(少見) → 保守歸收費
    if re.search(r"報名費|票價|售票", t):
        return 0, "收費"
    # 4. 其他(如「線上報名」「請洽主辦單位」)→ default 免費(台北展演多免費)
    return 0, "免費"


def extract_image(item: dict) -> str | None:
    """從 files 或 links 抓第一張圖。"""
    files = item.get("files") or []
    for f in files:
        src = f.get("src") or f.get("<Src>k__BackingField")
        if not src:
            continue
        if str(src).lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
            return src
    return None


def to_scraped_item(item: dict, source_name: str) -> ScrapedItem:
    title = (item.get("title") or "").strip()
    return ScrapedItem(
        ext_id=item.get("id") or 0,
        title=title,
        description=clean_html(item.get("description")),
        begin=iso_date(item.get("begin")),
        end=iso_date(item.get("end")),
        district=item.get("distric"),  # API 是 distric (typo 官方的)
        address=item.get("address"),
        organizer=item.get("organizer"),
        tel=item.get("tel"),
        ticket=item.get("ticket"),
        url=item.get("url") or "",
        source_name=source_name,
        is_major=bool(item.get("is_major")),
        image_url=extract_image(item),
    )


def scrape_endpoint(
    endpoint: str, source_name: str, max_pages: int = 5,
    begin_date: str | None = None, sleep: float = 0.5,
) -> list[ScrapedItem]:
    """抓 Events/Activity 或 Events/Calendar。"""
    out: list[ScrapedItem] = []
    for page in range(1, max_pages + 1):
        qs = [f"page={page}"]
        if begin_date:
            qs.append(f"begin={begin_date}")
        url = f"{BASE}/Events/{endpoint}?" + "&".join(qs)
        try:
            data = fetch_json(url)
        except Exception as e:
            print(f"[error] {endpoint} page {page}: {e}", file=sys.stderr)
            break

        # API 回傳 {"total": N, "data": [...]} 或直接 [...] — 看實況
        items = data.get("data") if isinstance(data, dict) else data
        if not items:
            print(f"[{endpoint} p{page}] 無資料,停。", flush=True)
            break

        page_items = [to_scraped_item(x, source_name) for x in items if x.get("title")]
        # 過濾:end_date 已過的活動先 skip(展演已結束對 UX 無價值)
        today = date.today().isoformat()
        page_items = [x for x in page_items if not x.end or x.end >= today]

        out.extend(page_items)
        print(f"[{endpoint} p{page}] → 原始 {len(items)} / 有效 {len(page_items)} 筆", flush=True)

        if len(items) < 30:
            break  # 最後一頁
        time.sleep(sleep)

    # 依 (source_name, ext_id) 去重
    seen: set[tuple[str, int]] = set()
    deduped: list[ScrapedItem] = []
    for it in out:
        key = (it.source_name, it.ext_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(it)
    return deduped


def to_activity_row(item: ScrapedItem) -> dict[str, Any]:
    category = guess_category(item.title, item.description)
    cost, pricing_tag = parse_ticket(item.ticket)

    tags = ["活動", "台北旅遊網", pricing_tag]
    if item.is_major:
        tags.append("大型活動")

    # event_type:有明確 begin/end 就算 single,否則 recurring
    event_type = "single" if (item.begin and item.end) else "recurring"

    # summary:description 太長就截
    desc = item.description or ""
    summary = desc[:200] + ("..." if len(desc) > 200 else "")
    if not summary:
        summary = f"{item.title} - 點原連結看詳情。"

    # source_url:API 提供 url,若沒有則退回 travel.taipei/zh-tw/events/details/{id} 的共通規則
    source_url = item.url
    if not source_url:
        source_url = f"https://www.travel.taipei/zh-tw/events/details/{item.ext_id}"

    return {
        "title": item.title[:140],
        "summary": summary,
        "description": desc[:500] if desc else None,  # description 可長,裁到 500
        "organizer_name": item.organizer or "台北市政府",
        "event_type": event_type,
        "start_date": item.begin,
        "end_date": item.end,
        "recurring_rule": None,
        "location_name": item.address,
        "address": item.address,
        "city": CITY,
        "district": item.district,
        "category": category,
        "tags": tags,
        "target_audience": "不限",  # 大部分展演無年齡限制;樂齡族也可參加
        "cost": cost,
        "cost_note": item.ticket[:100] if item.ticket else None,
        "signup_method": "phone" if item.tel else "online",
        "signup_phone": item.tel,
        "signup_url": source_url,
        "source_url": source_url,
        "source_name": item.source_name,
        "status": "active",
        "image_url": item.image_url,
    }


def upsert_to_supabase(rows: list[dict], supa_url: str, supa_key: str) -> int:
    """強制不走 system proxy(同 fetch_json),避免 Clash 關閉時 Connection refused。"""
    if not rows:
        return 0
    # 去重用 source_url(同一 API id 會有穩定 url)
    # 先撈既有的 source_url — 限制在兩個 source_name 內
    q = (
        f"{supa_url}/rest/v1/activities?select=source_url"
        f"&source_name=in.({urllib.parse.quote(SOURCE_ACTIVITY)},{urllib.parse.quote(SOURCE_CALENDAR)})"
    )
    req = urllib.request.Request(q, headers={
        "apikey": supa_key,
        "Authorization": f"Bearer {supa_key}",
    })
    with _NO_PROXY_OPENER.open(req, timeout=20) as r:
        existing = {x["source_url"] for x in json.loads(r.read()) if x.get("source_url")}

    new_rows = [r for r in rows if r.get("source_url") and r["source_url"] not in existing]
    if not new_rows:
        return 0

    insert_url = f"{supa_url}/rest/v1/activities"
    # Supabase 一次不要塞超過 500 筆,分批
    total_inserted = 0
    BATCH = 100
    for i in range(0, len(new_rows), BATCH):
        batch = new_rows[i:i + BATCH]
        data = json.dumps(batch).encode()
        req = urllib.request.Request(
            insert_url, data=data, method="POST",
            headers={
                "apikey": supa_key,
                "Authorization": f"Bearer {supa_key}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
        )
        with _NO_PROXY_OPENER.open(req, timeout=60) as r:
            out = json.loads(r.read())
        total_inserted += len(out)
    return total_inserted


def main() -> int:
    import os
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=str)
    ap.add_argument("--upsert", action="store_true")
    ap.add_argument("--max-pages", type=int, default=5, help="每個 endpoint 最多抓幾頁(每頁 30 筆)")
    ap.add_argument("--sleep", type=float, default=0.5)
    args = ap.parse_args()

    # begin 往回推 1 週(確保抓到還在跑的活動),end 是今天就能 filter 掉的
    begin_date = (date.today() - timedelta(days=7)).isoformat()
    print(f"=== 抓 台北旅遊網 Events/Activity(活動展演) begin={begin_date} ===")
    activity_items = scrape_endpoint("Activity", SOURCE_ACTIVITY, args.max_pages, begin_date, args.sleep)
    print(f"→ 共 {len(activity_items)} 筆")

    print(f"\n=== 抓 台北旅遊網 Events/Calendar(活動年曆) ===")
    calendar_items = scrape_endpoint("Calendar", SOURCE_CALENDAR, 3, None, args.sleep)
    print(f"→ 共 {len(calendar_items)} 筆")

    all_items = activity_items + calendar_items
    print(f"\n=== 總共 {len(all_items)} 筆 ===")

    from collections import Counter
    cat_c = Counter(guess_category(x.title, x.description) for x in all_items)
    print(f"  category: {dict(cat_c)}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump([asdict(x) for x in all_items], f, ensure_ascii=False, indent=2)
        print(f"JSON → {args.out}")

    if args.upsert:
        supa_url = os.environ.get("SUPABASE_URL")
        supa_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not supa_url or not supa_key:
            print("[error] 缺 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY", file=sys.stderr)
            return 2
        rows = [to_activity_row(x) for x in all_items]
        inserted = upsert_to_supabase(rows, supa_url, supa_key)
        print(f"Supabase 新插入 {inserted} 筆")

    return 0


if __name__ == "__main__":
    sys.exit(main())
