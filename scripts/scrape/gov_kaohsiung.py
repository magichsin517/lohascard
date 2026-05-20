#!/usr/bin/env python3
"""
高雄市立圖書館 — 最新消息/活動爬蟲
資料源: https://www.ksml.edu.tw/lib/Latestevent/index.aspx?Parser=9,83,918

頁面結構 (2026-05-20 實測):
  - 列表頁: <li> 塊，每頁 10 筆，共 2 頁 (page 0-1)
  - 標題: <a href="Details.aspx?Parser=9,83,918,,,,{ID}" title="...">
  - 公布日期: <span class="w15 hidden-xs">YYYY-MM-DD</span>

補充說明:
  - iCulture 已涵蓋高雄市 2000+ 筆藝文活動
  - 此爬蟲補充高雄市立圖書館辦理之講座/展覽/閱讀活動，
    這類活動 iCulture 通常不收錄

去重鍵: source_url

執行:
  python3 scripts/scrape/gov_kaohsiung.py --out /tmp/kaohsiung.json
  SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... \\
    python3 scripts/scrape/gov_kaohsiung.py --upsert
"""
from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import sys
import time
import urllib.request
from typing import Any

BASE_URL = "https://www.ksml.edu.tw"
LIST_URL = BASE_URL + "/lib/Latestevent/index.aspx?Parser=9,83,918,,,,,,,,{page}"
DETAIL_BASE = BASE_URL + "/lib/Latestevent/"
TOTAL_PAGES = 2  # pages 0-1 (confirmed 2026-05-20)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
SOURCE_NAME = "高雄市立圖書館"
CITY = "高雄市"

_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

TAG_RE = re.compile(r"<[^>]+>")

CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("sports",    ("馬拉松", "路跑", "健走", "自行車", "運動", "瑜珈", "太極")),
    ("travel",    ("旅遊", "踏青", "走讀", "小旅行", "旗津", "美濃")),
    ("social",    ("市集", "園遊", "同樂", "共餐", "親子", "祖孫")),
    ("health",    ("健康", "養生", "保健", "醫療", "篩檢", "失智")),
    ("volunteer", ("志工", "志願")),
    ("learning",  ("講座", "論壇", "研習", "工作坊", "培訓", "讀書會",
                   "說書", "文學", "獎", "徵文", "徵獎")),
    ("culture",   ("展", "演", "音樂", "歌", "戲", "藝術", "電影",
                   "影展", "博覽會", "導覽", "特展", "閱讀", "書")),
]

KAOHSIUNG_DISTRICTS = [
    "鹽埕區", "鼓山區", "左營區", "楠梓區", "三民區", "新興區", "前金區",
    "苓雅區", "前鎮區", "旗津區", "小港區", "鳳山區", "林園區", "大寮區",
    "大樹區", "大社區", "仁武區", "鳥松區", "岡山區", "橋頭區", "燕巢區",
    "田寮區", "阿蓮區", "路竹區", "湖內區", "茄萣區", "永安區", "彌陀區",
    "梓官區", "旗山區", "美濃區", "六龜區", "甲仙區", "杉林區", "內門區",
    "茂林區", "桃源區", "那瑪夏區",
]

SENIOR_RE = re.compile(r"55歲|60歲|65歲|樂齡|銀髮|長者|老人|高齡|退休")


def fetch_url(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with _NO_PROXY_OPENER.open(req, timeout=timeout) as resp:
        raw = resp.read()
        for enc in ("utf-8", "big5", "utf-8-sig"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")


def strip_tags(html_str: str) -> str:
    return TAG_RE.sub(" ", html_lib.unescape(html_str)).strip()


def guess_category(title: str) -> str:
    for cat, kws in CATEGORY_KEYWORDS:
        if any(k in title for k in kws):
            return cat
    return "culture"


def guess_district(title: str) -> str | None:
    for d in sorted(KAOHSIUNG_DISTRICTS, key=len, reverse=True):
        if d in title:
            return d
    return None


def parse_date(text: str) -> str | None:
    """YYYY-MM-DD or YYYY/MM/DD"""
    m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


def parse_list_page(html: str) -> list[dict]:
    """從列表頁抽取活動基本資料"""
    items = []
    # Each item: <li > ... Details.aspx?Parser=9,83,918,,,,{ID},,,,{page}  title="..." ... <span>2026-05-17</span>
    blocks = re.findall(r'<li >(.*?)</li>', html, re.DOTALL)
    for block in blocks:
        # URL: Details.aspx?Parser=9,83,918,,,,15793,,,,0  (extra commas at end)
        link_m = re.search(
            r'href="(Details\.aspx\?Parser=9,83,918,,,,\d+[^"]*)"[^>]*title="([^"]+)"',
            block,
        )
        if not link_m:
            continue
        href = link_m.group(1)
        title = html_lib.unescape(link_m.group(2))
        source_url = DETAIL_BASE + href

        # Publication date from <span class="w15 hidden-xs">
        date_m = re.search(r'class="w15 hidden-xs">(\d{4}-\d{2}-\d{2})<', block)
        pub_date = date_m.group(1) if date_m else None

        items.append({
            "title": title,
            "source_url": source_url,
            "pub_date": pub_date,
        })
    return items


def fetch_detail_dates(source_url: str, sleep: float = 0.5) -> tuple[str | None, str | None]:
    """
    從詳細頁抽取活動日期範圍。
    搜尋 YYYY-MM-DD 或 M/D(週) 等格式。
    回傳 (start_date, end_date)。
    """
    time.sleep(sleep)
    try:
        html = fetch_url(source_url)
    except Exception:
        return None, None

    # Extract body text from content_txt div
    idx = html.find("content_txt")
    body_html = html[idx:idx + 4000] if idx > 0 else html[3000:7000]
    body = TAG_RE.sub(" ", html_lib.unescape(body_html))

    # Full YYYY-MM-DD or YYYY/MM/DD dates
    full_dates = re.findall(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", body)
    # Filter out today/metadata dates (first two spans are site meta)
    event_dates = []
    for d in full_dates:
        parsed = parse_date(d)
        if parsed and parsed not in event_dates:
            event_dates.append(parsed)

    # If only one date and it looks like the pub date (exact match), ignore
    if len(event_dates) == 1:
        return event_dates[0], None
    if len(event_dates) >= 2:
        return event_dates[0], event_dates[-1]
    return None, None


def item_to_row(item: dict, fetch_detail: bool = True, sleep: float = 0.5) -> dict[str, Any]:
    title = item["title"]
    is_free = re.search(r"免費|free", title, re.I) is not None
    is_senior = bool(SENIOR_RE.search(title))
    pricing_tags = ["免費"] if is_free else ["小額收費"]

    # Try to get actual event dates from detail page
    start_date, end_date = None, None
    if fetch_detail:
        start_date, end_date = fetch_detail_dates(item["source_url"], sleep=sleep)
    # Fallback to publication date
    if not start_date:
        start_date = item.get("pub_date")

    return {
        "source_url": item["source_url"],
        "title": title,
        "summary": None,
        "description": None,
        "organizer_name": SOURCE_NAME,
        "source_name": SOURCE_NAME,
        "event_type": "single" if start_date else "recurring",
        "start_date": start_date,
        "end_date": end_date,
        "city": CITY,
        "district": guess_district(title),
        "category": guess_category(title),
        "tags": pricing_tags,
        "target_audience": "55+" if is_senior else "不限",
        "cost": 0 if is_free else 1,
        "signup_method": "online",
        "signup_url": item["source_url"],
        "image_url": None,
        "status": "active",
        "is_curated": False,
    }


def upsert_to_supabase(rows: list[dict], supabase_url: str, service_key: str) -> int:
    endpoint = f"{supabase_url}/rest/v1/activities"
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    seen: set[str] = set()
    deduped = []
    for r in rows:
        key = r.get("source_url") or ""
        if key and key not in seen:
            seen.add(key)
            deduped.append(r)
    body = json.dumps(deduped).encode()
    req = urllib.request.Request(
        f"{endpoint}?on_conflict=source_url",
        data=body,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        status = resp.status
    print(f"[upsert] HTTP {status}, {len(deduped)} rows")
    return len(deduped)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="輸出 JSON 路徑")
    ap.add_argument("--upsert", action="store_true", help="寫入 Supabase")
    ap.add_argument("--sleep", type=float, default=0.8, help="請求間 sleep 秒數")
    ap.add_argument("--pages", type=int, default=TOTAL_PAGES, help="爬幾頁 (預設 2)")
    ap.add_argument("--no-detail", action="store_true", help="跳過詳細頁抓日期")
    args = ap.parse_args()

    import os
    supabase_url = os.environ.get("SUPABASE_URL", "")
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

    all_items: list[dict] = []
    for page in range(args.pages):
        url = LIST_URL.format(page=page)
        print(f"[gov_kaohsiung] Fetching page {page}: {url}")
        try:
            html = fetch_url(url)
            items = parse_list_page(html)
            print(f"  → {len(items)} items")
            all_items.extend(items)
        except Exception as e:
            print(f"[WARN] Page {page} failed: {e}", file=sys.stderr)
        if page < args.pages - 1:
            time.sleep(args.sleep)

    if not all_items:
        print("[ERROR] 沒有抓到任何活動", file=sys.stderr)
        sys.exit(1)

    fetch_detail = not args.no_detail
    print(f"[gov_kaohsiung] Building rows (fetch_detail={fetch_detail})...")
    rows = [item_to_row(i, fetch_detail=fetch_detail, sleep=args.sleep) for i in all_items]

    with_date = sum(1 for r in rows if r["start_date"])
    print(f"[gov_kaohsiung] Total: {len(rows)} rows ({with_date} with start_date)")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        print(f"[gov_kaohsiung] Written to {args.out}")

    if args.upsert:
        if not supabase_url or not service_key:
            print("[ERROR] 需要 SUPABASE_URL 和 SUPABASE_SERVICE_ROLE_KEY", file=sys.stderr)
            sys.exit(1)
        n = upsert_to_supabase(rows, supabase_url, service_key)
        print(f"[gov_kaohsiung] Upserted {n} rows")

    print("[gov_kaohsiung] Done")


if __name__ == "__main__":
    main()
