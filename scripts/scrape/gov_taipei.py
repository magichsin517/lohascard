#!/usr/bin/env python3
"""
台北市政府觀光傳播局 — 活動 RSS 爬蟲
資料源:臺北旅遊網 Activity RSS feed
  https://www.travel.taipei/zh-tw/activity/rss

為什麼用 RSS 而不用 Open API?
  travel.taipei 的 Open API(/open-api/.../Events/Activity)被 Cloudflare JS
  challenge 擋,Python urllib / curl 的 TLS 指紋過不了(回 403)。
  RSS endpoint 給聚合器用,CF 通常不擋 — 實測 HTTP 200 回 XML。

資料量:RSS 一次只給 10 筆最新活動。單次量少,但配合每日 cron 長期累積:
  10 筆/天 × 30 天 = 300 筆/月。去重用 GUID(詳情頁 URL,永久固定)。

RSS 欄位對應:
  <title>     → activity.title
  <link>      → activity.source_url / signup_url
  <description> → activity.description(含日期/地點/報名方式等,會含 HTML entities)
  <author>    → activity.organizer_name
  <pubDate>   → 發佈時間(不等於活動日期,只記錄)

執行:
  python3 scripts/scrape/gov_taipei.py --out /tmp/taipei.json
  SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... \\
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
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from email.utils import parsedate_to_datetime
from typing import Any

RSS_URL = "https://www.travel.taipei/zh-tw/activity/rss"
# 真 Chrome UA;RSS feed 其實不挑,但保留以防萬一
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
SOURCE_NAME = "台北旅遊網"
CITY = "台北市"

# 強制不走 system proxy(macOS Clash 關閉時會 Connection refused)
_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# category 啟發式(title + description 關鍵字,優先序命中第一個)
CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("sports",   ("馬拉松", "路跑", "健走", "自行車", "單車", "球賽", "運動", "瑜珈", "瑜伽", "太極")),
    ("travel",   ("旅遊", "踏青", "走讀", "小旅行", "巡禮")),
    ("social",   ("市集", "園遊", "同樂", "共餐", "祖孫", "親子")),
    ("health",   ("健康", "養生", "保健", "醫療", "篩檢", "失智", "防疫")),
    ("volunteer", ("志工", "志願")),
    ("learning", ("講座", "論壇", "研習", "工作坊", "體驗營", "讀書會", "培訓")),
    ("culture",  ("展", "演", "音樂", "歌", "戲", "藝術", "文學", "電影", "影展", "燈會",
                  "節慶", "嘉年華", "博覽會", "導覽", "特展", "個展")),
]

TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class ScrapedItem:
    guid: str           # 唯一識別(= 詳情頁 URL)
    title: str
    description: str | None
    link: str
    author: str | None
    pubdate: str | None  # ISO 格式
    image_url: str | None


def fetch_rss(url: str, *, retries: int = 3, timeout: int = 30) -> str:
    """下載 RSS XML。強制不走 system proxy。"""
    last = None
    headers = {
        "User-Agent": UA,
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "zh-TW,zh;q=0.9",
    }
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with _NO_PROXY_OPENER.open(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"fetch RSS failed: {url}: {last}")


def clean_html(s: str | None) -> str | None:
    if not s:
        return None
    # 先處理 &mdash; &nbsp; 這類 entity
    s = html_lib.unescape(s)
    s = TAG_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def parse_pubdate(s: str | None) -> str | None:
    """RSS pubDate 格式:Wed, 15 Apr 2026 09:45:00 GMT → 2026-04-15"""
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s)
        return dt.date().isoformat()
    except Exception:
        return None


def extract_image_from_desc(description: str | None) -> str | None:
    """RSS 的 description 內嵌 HTML,可能含 <img src=...>。"""
    if not description:
        return None
    # description 裡的 HTML 已經被 entity-encoded,先解一次
    unescaped = html_lib.unescape(description)
    m = re.search(r'<img[^>]+src="([^"]+)"', unescaped)
    if m:
        src = m.group(1)
        # travel.taipei RSS 的圖片可能是相對路徑
        if src.startswith("//"):
            src = "https:" + src
        elif src.startswith("/"):
            src = "https://www.travel.taipei" + src
        return src
    return None


def parse_rss(xml_text: str) -> list[ScrapedItem]:
    """解析 RSS XML → list[ScrapedItem]。"""
    items: list[ScrapedItem] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"[error] RSS XML parse failed: {e}", file=sys.stderr)
        return items

    channel = root.find("channel")
    if channel is None:
        return items

    for it in channel.findall("item"):
        def _text(tag: str) -> str | None:
            el = it.find(tag)
            return el.text if el is not None else None

        title = _text("title") or ""
        link = _text("link") or ""
        guid = _text("guid") or link
        description_raw = _text("description")
        author = _text("author")
        pubdate_raw = _text("pubDate")

        if not title or not link:
            continue

        items.append(ScrapedItem(
            guid=guid.strip(),
            title=title.strip(),
            description=description_raw,  # 保留原始 HTML,後面 clean_html 時處理
            link=link.strip(),
            author=author.strip() if author else None,
            pubdate=parse_pubdate(pubdate_raw),
            image_url=extract_image_from_desc(description_raw),
        ))
    return items


def scrape_all() -> list[ScrapedItem]:
    print(f"=== 抓 {RSS_URL} ===", flush=True)
    xml = fetch_rss(RSS_URL)
    items = parse_rss(xml)
    print(f"[rss] → {len(items)} 筆", flush=True)
    return items


def guess_category(title: str, description: str | None) -> str:
    text = title + " " + (description or "")
    for cat, kws in CATEGORY_KEYWORDS:
        for kw in kws:
            if kw in text:
                return cat
    return "culture"  # 台北旅遊網幾乎全是展演類,default culture


def parse_ticket_hints(description_clean: str | None) -> tuple[int, str, str | None]:
    """從 clean description 裡找費用線索。回傳 (cost_int, pricing_tag, cost_note)。"""
    if not description_clean:
        return 0, "免費", None
    t = description_clean
    # 找票價 pattern
    amts = [int(m.group(1)) for m in re.finditer(r"(\d{2,4})\s*元", t)]
    amts = [a for a in amts if a >= 1]
    if amts:
        amt = amts[0]
        # 取第一段含數字的片段當 note(限 50 字內)
        m = re.search(r"([^。\n]{0,50}\d{2,4}\s*元[^。\n]{0,20})", t)
        note = m.group(1).strip() if m else f"約 {amt} 元起"
        if amt <= 300:
            return amt, "小額收費", note
        return amt, "收費", note
    if re.search(r"免費|免報名|免票|自由入場|無售票|自由參觀", t):
        return 0, "免費", "免費入場"
    if re.search(r"售票|票價|門票", t):
        return 0, "收費", None  # 沒抓到數字
    return 0, "免費", None  # default 免費(台北展演多數免費)


def extract_date_range(description_clean: str | None) -> tuple[str | None, str | None]:
    """從 description 找「2026/5/1-5/3」「5月1日到5月3日」類的日期範圍。MVP 簡略版。"""
    if not description_clean:
        return None, None
    t = description_clean

    # pattern A:2026/5/1-5/3 or 2026/5/1～5/3
    m = re.search(r"(20\d{2})[/\-\.](\d{1,2})[/\-\.](\d{1,2})\s*[-~～至到]\s*(\d{1,2})[/\-\.](\d{1,2})", t)
    if m:
        y, m1, d1, m2, d2 = m.groups()
        try:
            return f"{y}-{int(m1):02d}-{int(d1):02d}", f"{y}-{int(m2):02d}-{int(d2):02d}"
        except Exception:
            pass
    # pattern B:2026/5/1 單日
    m = re.search(r"(20\d{2})[/\-\.](\d{1,2})[/\-\.](\d{1,2})", t)
    if m:
        y, mn, d = m.groups()
        try:
            date = f"{y}-{int(mn):02d}-{int(d):02d}"
            return date, date
        except Exception:
            pass
    return None, None


def to_activity_row(item: ScrapedItem) -> dict[str, Any]:
    desc_clean = clean_html(item.description)
    category = guess_category(item.title, desc_clean)
    cost, pricing_tag, cost_note = parse_ticket_hints(desc_clean)
    start_date, end_date = extract_date_range(desc_clean)

    tags = ["活動", "台北旅遊網", pricing_tag]

    # summary 保留前 200 字
    summary = (desc_clean[:200] + ("..." if desc_clean and len(desc_clean) > 200 else "")) if desc_clean else None

    event_type = "single" if start_date and end_date else "recurring"  # 無日期 → recurring 避免被過期濾掉

    return {
        "title": item.title[:140],
        "summary": summary,
        "description": desc_clean[:800] if desc_clean else None,  # 裁到 800 防止爆欄位
        "organizer_name": item.author or "台北市政府觀光傳播局",
        "event_type": event_type,
        "start_date": start_date,
        "end_date": end_date,
        "recurring_rule": None,
        "location_name": None,
        "city": CITY,
        "district": None,
        "category": category,
        "tags": tags,
        "target_audience": "不限",  # 台北旅遊網多為公開活動,不限年齡
        "cost": cost,
        "cost_note": cost_note,
        "signup_method": "online",
        "signup_url": item.link,
        "source_url": item.link,  # 去重鍵
        "source_name": SOURCE_NAME,
        "status": "active",
        "image_url": item.image_url,
    }


def upsert_to_supabase(rows: list[dict], supa_url: str, supa_key: str) -> int:
    if not rows:
        return 0
    # 去重:先撈已存在的 source_url(限制在此 source_name)
    q = (
        f"{supa_url}/rest/v1/activities?select=source_url"
        f"&source_name=eq.{urllib.parse.quote(SOURCE_NAME)}"
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
    data = json.dumps(new_rows).encode()
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
    return len(out)


def main() -> int:
    import os
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=str)
    ap.add_argument("--upsert", action="store_true")
    args = ap.parse_args()

    items = scrape_all()
    print(f"\n=== 共 {len(items)} 筆 ===")
    from collections import Counter
    cat_c = Counter(guess_category(x.title, x.description) for x in items)
    print(f"  category: {dict(cat_c)}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump([asdict(x) for x in items], f, ensure_ascii=False, indent=2)
        print(f"JSON → {args.out}")

    if args.upsert:
        supa_url = os.environ.get("SUPABASE_URL")
        supa_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not supa_url or not supa_key:
            print("[error] 缺 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY", file=sys.stderr)
            return 2
        rows = [to_activity_row(x) for x in items]
        inserted = upsert_to_supabase(rows, supa_url, supa_key)
        print(f"Supabase 新插入 {inserted} 筆(每日 cron 累積)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
