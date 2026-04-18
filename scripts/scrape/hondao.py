#!/usr/bin/env python3
"""
弘道老人福利基金會 — 活動消息爬蟲
https://www.hondao.org.tw/news/3

清單頁(/news)預設就是活動消息分類。每頁 12 筆、總共 ~7 頁。
每筆活動抓:
  - title(【活動報名】/【活動消息】開頭的才算活動)
  - /news/3/{id} 詳情 URL(source_url)
  - 封面圖
  - description(列表上的短文)

欄位推斷(用 title 啟發式):
  - category:從 title 關鍵字猜(social/travel/culture/sports/learning/volunteer)
  - city:若 title 含「台北場/台中場/高雄場...」就抓,否則 null(代表全台或線上)
  - cost_tier:若含「已額滿」標 tag、無費用資訊不填(前端會顯示「請點連結查詳情」)

執行:
  # dry-run(只列出,不寫 DB)
  python3 scripts/scrape/hondao.py --out /tmp/hondao.json

  # 寫入 Supabase
  SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... python3 scripts/scrape/hondao.py --upsert

這個網站 GitHub Actions 連得到(非台灣 gov),可以排進 daily-scrape.yml。
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
from typing import Any

BASE = "https://www.hondao.org.tw"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 LohasCardBot/0.1"
SOURCE_NAME = "弘道老人福利基金會"

# 清單頁裡的卡片 pattern:<a href="/news/3/{id}" class="item"> ... </a>
# title/description/image 分別在內部 <div class="title">、<div class="text">、<img alt="...">
# 用寬鬆 regex 逐個取。注意這個網站排版不完全一致,所以一對一抓每個卡片再 parse 內部欄位。
CARD_RE = re.compile(
    r'<a\s+href="(/news/3/(\d+))"\s+class="item"[^>]*>(.*?)</a>',
    re.DOTALL,
)
IMG_RE = re.compile(r'<img[^>]+src="([^"]+)"[^>]*alt="([^"]*)"', re.DOTALL)
TITLE_RE = re.compile(r'<div class="title">\s*(.*?)\s*</div>', re.DOTALL)
TEXT_RE = re.compile(r'<div class="text">\s*(.*?)\s*</div>', re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")

# 過濾規則
# 活動類 prefix(前綴含任一視為活動)
INCLUDE_PREFIXES = (
    "【活動報名】", "【活動消息】", "【活動推薦】",
    "【已額滿】",  # 已額滿但仍展示(tag 標註)
)
# 非活動類 prefix(店鋪、文件、公告等)
EXCLUDE_PREFIXES = (
    "【重要資訊】", "【重要】", "【公告】",
    "【弘道出品】", "【弘道榮耀】",
    "【弘道好物】", "【全新登場】",  # 商品類,不是可參加的活動
)

# 台灣主要縣市別名(台/臺 都認)
CITY_ALIASES: list[tuple[str, str]] = [
    ("台北", "台北市"), ("臺北", "台北市"),
    ("新北", "新北市"),
    ("桃園", "桃園市"),
    ("台中", "台中市"), ("臺中", "台中市"),
    ("台南", "台南市"), ("臺南", "台南市"),
    ("高雄", "高雄市"),
    ("基隆", "基隆市"),
    ("新竹", "新竹市"),
    ("苗栗", "苗栗縣"),
    ("彰化", "彰化縣"),
    ("南投", "南投縣"),
    ("雲林", "雲林縣"),
    ("嘉義", "嘉義市"),
    ("屏東", "屏東縣"),
    ("宜蘭", "宜蘭縣"),
    ("花蓮", "花蓮縣"),
    ("台東", "台東縣"), ("臺東", "台東縣"),
    ("澎湖", "澎湖縣"),
    ("金門", "金門縣"),
    ("連江", "連江縣"), ("馬祖", "連江縣"),
]

# category 啟發式(按優先序匹配第一個命中)
CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("sports", ("騎士", "健走", "Walk", "走讀", "K-POP", "舞蹈", "舞動", "環島", "登山")),
    ("travel", ("出走", "旅行", "旅遊", "行旅", "踏青", "走訪", "山海")),
    ("culture", ("音樂", "歌唱", "表演", "演出", "爺奶萬萬說", "展覽", "博覽會", "藝術", "劇本殺", "桌遊", "戲劇")),
    ("social", ("市集", "聚會", "聯誼", "同樂", "童樂會", "祖孫", "共餐")),
    ("volunteer", ("志工", "志願", "引導員", "培訓", "陪伴")),
    ("learning", ("課程", "講座", "工作坊", "研習", "說明會", "論壇", "高峰會")),
]


@dataclass
class ScrapedItem:
    source_url: str
    news_id: str
    title: str
    summary: str | None
    image_url: str | None
    category: str
    city: str | None
    tags: list[str]


def fetch(url: str, *, retries: int = 3, backoff: float = 2.0, timeout: int = 40) -> str:
    last_exc = None
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    import gzip
                    raw = gzip.decompress(raw)
                return raw.decode("utf-8", errors="replace")
        except Exception as e:
            last_exc = e
            time.sleep(backoff * (attempt + 1))
    raise RuntimeError(f"fetch failed: {url}: {last_exc}")


def clean_text(s: str) -> str:
    s = TAG_RE.sub(" ", s)
    s = html_lib.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    # 統一 dash 與繁體(保持台灣慣用)
    s = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]", "-", s)
    s = s.replace("臺", "台")
    return s


def should_include(title: str) -> bool:
    """只收活動類貼文。"""
    if any(title.startswith(p) for p in EXCLUDE_PREFIXES):
        return False
    if any(p in title for p in INCLUDE_PREFIXES):
        return True
    # 兜底:含「活動」二字也收
    if "活動" in title[:15]:
        return True
    return False


def guess_category(title: str, summary: str | None) -> str:
    """title + summary 組合關鍵字猜 category。"""
    text = title + " " + (summary or "")
    for cat, kws in CATEGORY_KEYWORDS:
        for kw in kws:
            if kw in text:
                return cat
    return "social"  # 弘道活動多是社群取向,default social 比 learning 合理


def guess_city(title: str, summary: str | None) -> str | None:
    """從 title/summary 找「台北場、高雄場、在台中」等線索。"""
    text = title + " " + (summary or "")
    for alias, canonical in CITY_ALIASES:
        # 常見寫法:「台北場」「在台北」「台北舉辦」
        if re.search(alias + r"(場|市|縣|舉辦|登場|活動)", text):
            return canonical
        if re.search(r"(於|在)" + alias, text):
            return canonical
    return None  # 沒明確地點 → 全台 or 線上 or 多場次


def extract_tags(title: str, summary: str | None) -> list[str]:
    """弘道活動的 tag,包含 pricing tier(免費/小額收費/收費)。

    前端 filter 約定:每筆活動必須剛好有一個 pricing tag。
    弘道多數活動詳情頁才寫費用,MVP 靠 title/summary 線索猜:
      - 含「免費」→ 免費
      - 含「公益市集」、「參觀」等無費用活動 → 免費
      - default → 小額收費 (弘道多數活動在 300-2000 元區間)
    """
    text = title + " " + (summary or "")
    tags: list[str] = ["活動", "弘道"]

    # pricing tier
    if "免費" in text or "免報名費" in text:
        tags.append("免費")
    elif re.search(r"\d{4,}\s*元", text):  # 四位數以上 = 收費活動
        tags.append("收費")
    else:
        tags.append("小額收費")  # 弘道多數在此區間,保守預設

    if "已額滿" in title:
        tags.append("已額滿")
    elif "招募" in title or "報名" in title or "開放報名" in text:
        tags.append("開放報名")
    return tags


def parse_list_page(html: str) -> list[ScrapedItem]:
    """解析單頁 /news?page=N 回傳 item list(已過濾 non-event)。"""
    items: list[ScrapedItem] = []
    seen_ids: set[str] = set()
    for m in CARD_RE.finditer(html):
        href, news_id, inner = m.group(1), m.group(2), m.group(3)
        if news_id in seen_ids:
            continue
        # title
        tm = TITLE_RE.search(inner)
        if not tm:
            continue
        title = clean_text(tm.group(1))
        if not title or not should_include(title):
            continue
        # text / summary
        um = TEXT_RE.search(inner)
        summary = clean_text(um.group(1)) if um else None
        # image
        im = IMG_RE.search(inner)
        image_url = im.group(1) if im else None
        if image_url and image_url.startswith("/"):
            image_url = BASE + image_url

        seen_ids.add(news_id)
        items.append(ScrapedItem(
            source_url=BASE + href,
            news_id=news_id,
            title=title,
            summary=summary,
            image_url=image_url,
            category=guess_category(title, summary),
            city=guess_city(title, summary),
            tags=extract_tags(title, summary),
        ))
    return items


def scrape_all(max_pages: int = 7, sleep: float = 0.5) -> list[ScrapedItem]:
    all_items: list[ScrapedItem] = []
    for page in range(1, max_pages + 1):
        url = f"{BASE}/news" if page == 1 else f"{BASE}/news?page={page}"
        try:
            html = fetch(url)
        except Exception as e:
            print(f"[error] page {page}: {e}", file=sys.stderr)
            continue
        items = parse_list_page(html)
        all_items.extend(items)
        print(f"[page {page}] → {len(items)} 筆活動", flush=True)
        if not items:
            # 沒東西了就停,避免白爬
            break
        time.sleep(sleep)
    # 依 news_id 去重
    seen: set[str] = set()
    deduped: list[ScrapedItem] = []
    for it in all_items:
        if it.news_id in seen:
            continue
        seen.add(it.news_id)
        deduped.append(it)
    return deduped


def to_activity_row(item: ScrapedItem) -> dict[str, Any]:
    """轉成 activities 表 row。弘道活動多為單次活動(single),
    若含多場次(巡迴)資訊,前端點原連結看詳情。"""
    summary = item.summary or f"弘道基金會活動 — 點原連結看詳細日期、地點、報名方式。"
    # cost 欄位:不知具體金額,用 0(schema default),實際定價 tag 走 tags
    return {
        "title": item.title[:140],
        "summary": summary[:280] if summary else None,
        "description": None,  # MVP 不讀 detail page;未來 v2 可加
        "organizer_name": SOURCE_NAME,
        "event_type": "single",
        "recurring_rule": None,
        "location_name": None,
        "city": item.city,
        "district": None,
        "category": item.category,
        "tags": item.tags,
        "target_audience": "55+",
        "cost": 0,  # 用 0 搭 tag『小額收費』— cost 欄位目前前端沒拿來顯示,靠 tag filter
        "signup_method": "online",
        "signup_url": item.source_url,
        "source_url": item.source_url,
        "source_name": SOURCE_NAME,
        "status": "active",
        "image_url": item.image_url,
    }


def upsert_to_supabase(rows: list[dict[str, Any]], supa_url: str, supa_key: str) -> int:
    """以 source_url 為去重鍵。回傳新插入筆數。"""
    if not rows:
        return 0
    # 撈既有 source_url
    check_url = (
        f"{supa_url}/rest/v1/activities?select=source_url"
        f"&source_name=eq.{urllib.parse.quote(SOURCE_NAME)}"
    )
    req = urllib.request.Request(check_url, headers={
        "apikey": supa_key,
        "Authorization": f"Bearer {supa_key}",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        existing = {x["source_url"] for x in json.loads(r.read()) if x.get("source_url")}

    new_rows = [r for r in rows if r.get("source_url") and r["source_url"] not in existing]
    if not new_rows:
        return 0

    insert_url = f"{supa_url}/rest/v1/activities"
    data = json.dumps(new_rows).encode("utf-8")
    req = urllib.request.Request(
        insert_url, data=data, method="POST",
        headers={
            "apikey": supa_key,
            "Authorization": f"Bearer {supa_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        out = json.loads(r.read())
    return len(out)


def main() -> int:
    import os
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=str, help="輸出 JSON 檔(除錯用)")
    ap.add_argument("--upsert", action="store_true", help="寫入 Supabase")
    ap.add_argument("--max-pages", type=int, default=7)
    ap.add_argument("--sleep", type=float, default=0.5)
    args = ap.parse_args()

    items = scrape_all(max_pages=args.max_pages, sleep=args.sleep)
    print(f"\n=== 共爬到 {len(items)} 筆活動 ===")

    # 分佈統計(眼睛看看有沒有抓錯)
    from collections import Counter
    cat_c = Counter(it.category for it in items)
    city_c = Counter(it.city or "(全台/未標)" for it in items)
    print(f"  category: {dict(cat_c)}")
    print(f"  city    : {dict(city_c)}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump([asdict(x) for x in items], f, ensure_ascii=False, indent=2)
        print(f"已輸出 JSON → {args.out}")

    if args.upsert:
        supa_url = os.environ.get("SUPABASE_URL")
        supa_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not supa_url or not supa_key:
            print("[error] 缺 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY", file=sys.stderr)
            return 2
        rows = [to_activity_row(x) for x in items]
        inserted = upsert_to_supabase(rows, supa_url, supa_key)
        print(f"Supabase 新插入 {inserted} 筆(已去重 source_url)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
