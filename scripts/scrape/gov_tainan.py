#!/usr/bin/env python3
"""
台南市政府文化局 — 藝文活動爬蟲
資料源: https://culture.tainan.gov.tw/active/index?Parser=99,3,31,,,,,,,,{page}

頁面結構 (2026-05-20 實測):
  - 列表頁: <li class="list_date"> 塊，每頁 10 筆，共 4 頁 (page 0-3)
  - 標題: <a href="Details?Parser=99,3,31,,,,{ID}" title="...">
  - 日期: <span class="w30" data-th="活動日期：">YYYY/MM/DD~YYYY/MM/DD</span>
  - 詳細頁: <div class="content_title">...</div>
            <li><div class="tabulation_tt w20">活動日期</div><div class="tabulation_word w80">...</div></li>
            <li><div class="tabulation_tt w20">公布單位</div><div class="tabulation_word w80">...</div></li>

去重鍵: source_url

執行:
  python3 scripts/scrape/gov_tainan.py --out /tmp/tainan.json
  SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... \\
    python3 scripts/scrape/gov_tainan.py --upsert
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

BASE_URL = "https://culture.tainan.gov.tw"
LIST_URL = BASE_URL + "/active/index?Parser=99,3,31,,,,,,,,{page}"
TOTAL_PAGES = 4  # pages 0-3 (confirmed 2026-05-20)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
SOURCE_NAME = "台南市政府文化局"
CITY = "台南市"

_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

TAG_RE = re.compile(r"<[^>]+>")

CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("sports",    ("馬拉松", "路跑", "健走", "自行車", "運動", "瑜珈", "太極", "球賽")),
    ("travel",    ("旅遊", "踏青", "走讀", "小旅行", "安平", "赤崁", "鹿耳門", "巡禮")),
    ("social",    ("市集", "園遊", "同樂", "共餐", "燈會", "節慶", "嘉年華", "祭")),
    ("health",    ("健康", "養生", "保健", "醫療", "篩檢", "失智")),
    ("volunteer", ("志工", "志願")),
    ("learning",  ("講座", "論壇", "研習", "工作坊", "培訓", "讀書會", "課程")),
    ("culture",   ("展", "演", "音樂", "歌", "戲", "藝術", "文學", "電影",
                   "影展", "博覽會", "導覽", "特展", "競賽", "創作")),
]

TAINAN_DISTRICTS = [
    "中西區", "東區", "南區", "北區", "安平區", "安南區", "永康區",
    "歸仁區", "新化區", "左鎮區", "玉井區", "楠西區", "南化區", "仁德區",
    "關廟區", "龍崎區", "官田區", "麻豆區", "佳里區", "西港區", "七股區",
    "將軍區", "學甲區", "北門區", "新營區", "後壁區", "白河區", "東山區",
    "六甲區", "下營區", "柳營區", "鹽水區", "善化區", "大內區", "山上區",
    "新市區", "安定區",
]


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
    for d in sorted(TAINAN_DISTRICTS, key=len, reverse=True):
        if d in title:
            return d
    return None


def parse_date_range(text: str) -> tuple[str | None, str | None]:
    """YYYY/MM/DD~YYYY/MM/DD 或 YYYY/MM/DD"""
    matches = re.findall(r"(\d{4})/(\d{1,2})/(\d{1,2})", text)
    if not matches:
        # 民國年: 113/05/20
        roc = re.findall(r"(\d{2,3})/(\d{1,2})/(\d{1,2})", text)
        if roc:
            matches = [(str(int(y) + 1911), m, d) for y, m, d in roc]
    if not matches:
        return None, None
    dates = [f"{y}-{int(m):02d}-{int(d):02d}" for y, m, d in matches]
    return dates[0], dates[-1] if len(dates) > 1 else None


def parse_list_page(html: str) -> list[dict]:
    """從列表頁抽取活動基本資料"""
    items = []
    # Each activity is in <li class="list_date"> block
    blocks = re.findall(
        r'<li class="list_date">(.*?)</li>',
        html,
        re.DOTALL,
    )
    for block in blocks:
        # Title and link
        # Primary: <a href="Details?..." title="...">
        link_m = re.search(
            r'href="(Details\?Parser=99,3,31,,,,\d+)"[^>]*title="([^"]+)"',
            block,
        )
        # Some items use external URL with hiturl pointing to Details
        if not link_m:
            link_m = re.search(
                r'hiturl="(Details\?Parser=99,3,31,,,,\d+)"',
                block,
            )
            title_m = re.search(r'title="([^"]+)"', block)
            if link_m and title_m:
                href = link_m.group(1)
                title = html_lib.unescape(title_m.group(1))
            else:
                continue
        else:
            href = link_m.group(1)
            title = html_lib.unescape(link_m.group(2))

        source_url = f"{BASE_URL}/active/{href}"

        # Date: <span class="w30" data-th="活動日期：">YYYY/MM/DD~YYYY/MM/DD</span>
        date_m = re.search(
            r'data-th="活動日期：">([^<]+)<',
            block,
        )
        date_text = date_m.group(1).strip() if date_m else ""
        start_date, end_date = parse_date_range(date_text)

        items.append({
            "title": title,
            "source_url": source_url,
            "start_date": start_date,
            "end_date": end_date,
            "date_text": date_text,
        })
    return items


TITLE_CLEANUP_RE = re.compile(
    r"^(?:連結至\s*)|(?:\s*\(另開視窗\))\s*$"
)

SENIOR_RE = re.compile(r"55歲|60歲|65歲|樂齡|銀髮|長者|老人|高齡|退休")


def clean_title(raw: str) -> str:
    t = TITLE_CLEANUP_RE.sub("", raw).strip()
    # Remove trailing (另開視窗) anywhere
    t = re.sub(r"\s*\(另開視窗\)\s*$", "", t).strip()
    return t


def item_to_row(item: dict) -> dict[str, Any]:
    title = clean_title(item["title"])
    is_free = re.search(r"免費|free", title, re.I) is not None
    is_senior = bool(SENIOR_RE.search(title))
    pricing_tags = ["免費"] if is_free else ["小額收費"]

    return {
        "source_url": item["source_url"],
        "title": title,
        "summary": item["date_text"] or None,
        "description": None,
        "organizer_name": SOURCE_NAME,
        "source_name": SOURCE_NAME,
        "event_type": "single" if item["start_date"] else "recurring",
        "start_date": item["start_date"],
        "end_date": item["end_date"],
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
    ap.add_argument("--sleep", type=float, default=0.8, help="頁面間 sleep 秒數")
    ap.add_argument("--pages", type=int, default=TOTAL_PAGES, help="爬幾頁 (預設 4)")
    args = ap.parse_args()

    import os
    supabase_url = os.environ.get("SUPABASE_URL", "")
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

    all_items: list[dict] = []
    for page in range(args.pages):
        url = LIST_URL.format(page=page)
        print(f"[gov_tainan] Fetching page {page}: {url}")
        try:
            html = fetch_url(url)
            items = parse_list_page(html)
            print(f"  → {len(items)} activities")
            all_items.extend(items)
        except Exception as e:
            print(f"[WARN] Page {page} failed: {e}", file=sys.stderr)
        if page < args.pages - 1:
            time.sleep(args.sleep)

    if not all_items:
        print("[ERROR] 沒有抓到任何活動", file=sys.stderr)
        sys.exit(1)

    rows = [item_to_row(i) for i in all_items]
    with_date = sum(1 for r in rows if r["start_date"])
    print(f"[gov_tainan] Total: {len(rows)} rows ({with_date} with start_date)")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        print(f"[gov_tainan] Written to {args.out}")

    if args.upsert:
        if not supabase_url or not service_key:
            print("[ERROR] 需要 SUPABASE_URL 和 SUPABASE_SERVICE_ROLE_KEY", file=sys.stderr)
            sys.exit(1)
        n = upsert_to_supabase(rows, supabase_url, service_key)
        print(f"[gov_tainan] Upserted {n} rows")

    print("[gov_tainan] Done")


if __name__ == "__main__":
    main()
