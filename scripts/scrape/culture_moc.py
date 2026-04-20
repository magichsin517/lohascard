#!/usr/bin/env python3
"""
文化部 iCulture — 全台藝文活動 Open API 爬蟲
資料源:文化部 iCulture 雲端平臺
  https://cloud.culture.tw/frontsite/trans/SearchShowAction.do?method=doFindTypeJ&category={N}

為什麼選這個 source:
  iCulture 已整合 100+ 公民營網站(兩廳院、各縣市文化局、故宮/北美館/科博館/
  高美館、劇院演藝廳等),每日更新。用一支 scraper 就能把雙北未來 45 天內
  有 start_date 的活動從 2 筆拉到 150+ 筆,同時覆蓋桃竹中南高的六都資料。

  授權:政府 Open Data, CC-BY,商業利用 OK,需註明來源「文化部 iCulture」。

Category 對應(2026-04 實測筆數):
  1  音樂      688
  2  戲劇      334
  3  舞蹈       88
  5  親子        6  ← 跳過,不收
  6  展覽      834
  7  講座      534
  8  電影      298
  11 兒童       32  ← 跳過,不收
  15 研習課程   49
  16 藝文       45
  17 未命名      9
  19 綜合       50

多場次處理:
  一筆 iCulture event 的 showInfo[] 可能有多場次。每場展開為一筆 activity row
  (event_type=single),source_url=iculture://{UID}/s{idx}。

執行:
  # 沙盒/本機 dry-run(只 fetch,不寫 DB)
  python3 scripts/scrape/culture_moc.py --out /tmp/iculture.json

  # 實際寫 Supabase
  SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... \\
    python3 scripts/scrape/culture_moc.py --upsert

  # 只抓特定 category
  python3 scripts/scrape/culture_moc.py --categories 1,2,7 --out /tmp/t.json
"""
from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict, field
from typing import Any

API_BASE = "https://cloud.culture.tw/frontsite/trans/SearchShowAction.do?method=doFindTypeJ&category={}"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
SOURCE_NAME = "文化部iCulture"

# 單一 event 最多收幾個 session。iCulture 的 VR 體感劇院類會有 346 個場次,
# 全寫入會把 DB 灌爆且使用者體驗差(列表看到 346 個一樣的標題)。
# 策略:優先收未來場次,按日期排序,取前 N 個。
MAX_SESSIONS_PER_EVENT = 8

# 強制不走 system proxy(macOS Clash 關閉時會 Connection refused)
_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# iCulture category → lohascard category + 中文名(for tags)
ICULTURE_CATEGORIES: dict[int, tuple[str, str]] = {
    # id: (lohascard_category, 中文名)
    1:  ("culture",  "音樂"),
    2:  ("culture",  "戲劇"),
    3:  ("culture",  "舞蹈"),
    6:  ("culture",  "展覽"),
    7:  ("learning", "講座"),
    8:  ("culture",  "電影"),
    15: ("learning", "研習課程"),
    16: ("culture",  "藝文"),
    17: ("culture",  "其他"),
    19: ("culture",  "綜合"),
}

# 跳過:親子(5)、兒童(11)太低齡,不適合 55+
SKIP_CATEGORIES = {5, 11}

# 台灣縣市清單(按優先序,前面先匹配)
CITIES = [
    "台北市", "新北市", "桃園市", "台中市", "台南市", "高雄市",
    "新竹市", "新竹縣", "基隆市", "宜蘭縣", "嘉義市", "嘉義縣",
    "雲林縣", "彰化縣", "南投縣", "苗栗縣", "屏東縣",
    "花蓮縣", "台東縣", "澎湖縣", "金門縣", "連江縣",
]
# iCulture 裡可能用 臺 字,兩版都比對
_CITY_VARIANTS = [(c, c.replace("台", "臺")) for c in CITIES]

# District regex — 從 location 字串抓行政區(雙北、六都常見)
DISTRICT_RE = re.compile(
    r"(中正區|大同區|中山區|松山區|大安區|萬華區|信義區|士林區|北投區|內湖區|南港區|文山區|"
    r"板橋區|三重區|中和區|永和區|新莊區|新店區|樹林區|鶯歌區|三峽區|淡水區|汐止區|瑞芳區|"
    r"土城區|蘆洲區|五股區|泰山區|林口區|深坑區|石碇區|坪林區|三芝區|石門區|八里區|平溪區|"
    r"雙溪區|貢寮區|金山區|萬里區|烏來區|"
    r"桃園區|中壢區|大溪區|楊梅區|蘆竹區|大園區|龜山區|八德區|龍潭區|平鎮區|新屋區|觀音區|復興區|"
    r"中區|東區|南區|西區|北區|北屯區|西屯區|南屯區|太平區|大里區|霧峰區|烏日區|豐原區|后里區|"
    r"東勢區|石岡區|新社區|潭子區|大雅區|神岡區|大肚區|沙鹿區|龍井區|梧棲區|清水區|大甲區|外埔區|大安區|和平區|"
    r"東區|南區|北區|安南區|安平區|中西區|新營區|鹽水區|白河區|柳營區|後壁區|東山區|麻豆區|下營區|六甲區|"
    r"官田區|大內區|佳里區|學甲區|西港區|七股區|將軍區|北門區|新化區|善化區|新市區|安定區|山上區|玉井區|"
    r"楠西區|南化區|左鎮區|仁德區|歸仁區|關廟區|龍崎區|永康區|"
    r"鹽埕區|鼓山區|左營區|楠梓區|三民區|新興區|前金區|苓雅區|前鎮區|旗津區|小港區|鳳山區|大寮區|鳥松區|"
    r"林園區|仁武區|大樹區|岡山區|路竹區|橋頭區|梓官區|彌陀區|永安區|燕巢區|田寮區|阿蓮區|茄萣區|湖內區|"
    r"旗山區|美濃區|內門區|杉林區|甲仙區|六龜區|茂林區|桃源區|那瑪夏區)"
)

# 超簡單 keyword → category 覆寫(當 iCulture 的 category 不夠精準時)
REFINE_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("sports",    ("馬拉松", "路跑", "健走", "瑜珈", "瑜伽", "太極", "舞動", "氣功")),
    ("health",    ("健康", "養生", "失智", "長者", "長青", "長壽", "銀髮")),
    ("travel",    ("走讀", "小旅行", "巡禮", "踏青")),
]

TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class ScrapedSession:
    """一筆 iCulture event 的一個場次(多場次展開後的最小粒度)"""
    uid: str              # iCulture event UID
    session_idx: int      # showInfo[] 的 index,從 0 起
    category_id: int      # iCulture category
    category_label: str   # 中文名(音樂/展覽/...)
    title: str
    summary: str | None
    start_date: str | None   # YYYY-MM-DD
    end_date: str | None
    start_time: str | None   # HH:MM
    end_time: str | None
    location: str | None     # 地址
    location_name: str | None  # 場地名
    city: str | None
    district: str | None
    on_sales: str | None     # 'Y' / 'N'
    price: str | None
    image_url: str | None
    master_unit: str | None
    source_web: str | None   # 原始主辦網站(sourceWebPromote)
    source_web_name: str | None

    @property
    def synthetic_source_url(self) -> str:
        # 用 date+time 編 key 而非 array idx。這樣當上游 showInfo 變動(例如過去場次
        # 被清掉、新場次加入),同一個真實的場次還是能對應到同一個 key,
        # 不會因為 cap MAX_SESSIONS_PER_EVENT 後 idx 漂移而重複插入。
        t = self.start_time or "00:00"
        d = self.start_date or "nodate"
        return f"iculture://{self.uid}/{d}T{t}"


def fetch_category(cat_id: int, *, retries: int = 3, timeout: int = 40) -> list[dict]:
    url = API_BASE.format(cat_id)
    headers = {
        "User-Agent": UA,
        "Accept": "application/json",
        "Accept-Language": "zh-TW,zh;q=0.9",
    }
    last: Exception | None = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with _NO_PROXY_OPENER.open(req, timeout=timeout) as r:
                body = r.read().decode("utf-8", errors="replace")
            if not body.strip():
                return []
            return json.loads(body)
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    print(f"[warn] category={cat_id} fetch failed: {last}", file=sys.stderr)
    return []


def clean_html(s: str | None) -> str | None:
    if not s:
        return None
    s = html_lib.unescape(s)
    s = TAG_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def parse_iculture_datetime(s: str | None) -> tuple[str | None, str | None]:
    """「2026/06/15 19:30:00」→ (2026-06-15, 19:30)"""
    if not s:
        return None, None
    m = re.match(r"(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})(?:\s+(\d{1,2}):(\d{2})(?::\d{2})?)?", s.strip())
    if not m:
        return None, None
    y, mo, d, hh, mm = m.groups()
    date = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    t_str = f"{int(hh):02d}:{mm}" if hh is not None else None
    return date, t_str


def extract_city(location: str | None, location_name: str | None) -> str | None:
    text = f"{location or ''} {location_name or ''}"
    for canonical, alt in _CITY_VARIANTS:
        if canonical in text or alt in text:
            return canonical  # 一律用「台」版
    return None


def extract_district(location: str | None) -> str | None:
    if not location:
        return None
    m = DISTRICT_RE.search(location)
    if m:
        return m.group(1)
    return None


def refine_category(base_cat: str, title: str, summary: str | None) -> str:
    text = f"{title} {summary or ''}"
    for cat, kws in REFINE_KEYWORDS:
        if any(kw in text for kw in kws):
            return cat
    return base_cat


def expand_sessions(event: dict, cat_id: int) -> list[ScrapedSession]:
    """一筆 iCulture event → 多筆 ScrapedSession(每個 showInfo 一筆)"""
    uid = event.get("UID") or ""
    if not uid:
        return []

    cat_base, cat_label = ICULTURE_CATEGORIES.get(cat_id, ("culture", "其他"))
    title = (event.get("title") or "").strip()
    if not title:
        return []

    summary_raw = event.get("descriptionFilterHtml")
    summary = clean_html(summary_raw)
    image_url = (event.get("imageUrl") or "").strip() or None
    source_web = (event.get("sourceWebPromote") or "").strip() or None
    source_web_name = (event.get("sourceWebName") or "").strip() or None

    master_units = event.get("masterUnit") or []
    master_unit = master_units[0] if master_units else None
    if isinstance(master_unit, dict):
        master_unit = master_unit.get("unitName") or master_unit.get("name")

    sessions: list[ScrapedSession] = []
    show_info = event.get("showInfo") or []

    # 場次上限:優先收未來的,依日期升序
    from datetime import date
    today = date.today().isoformat()
    def _date_key(si):
        d, _ = parse_iculture_datetime(si.get("time") or "")
        return d or "9999-12-31"

    if len(show_info) > MAX_SESSIONS_PER_EVENT:
        # 先把未來場次和過去場次分開,優先未來
        future = [si for si in show_info if _date_key(si) >= today]
        past = [si for si in show_info if _date_key(si) < today]
        future.sort(key=_date_key)
        past.sort(key=_date_key, reverse=True)
        # 取未來前 N 個;不夠 N 個才用過去補(多半 N=8 時都是未來的)
        picked = future[:MAX_SESSIONS_PER_EVENT]
        if len(picked) < MAX_SESSIONS_PER_EVENT:
            picked = picked + past[:(MAX_SESSIONS_PER_EVENT - len(picked))]
        show_info = picked

    if not show_info:
        # fallback:用 startDate / endDate
        sd = event.get("startDate")
        ed = event.get("endDate")
        if sd:
            start_date, _ = parse_iculture_datetime(sd + " 00:00:00")
            end_date, _ = parse_iculture_datetime(ed + " 00:00:00") if ed else (None, None)
            sessions.append(ScrapedSession(
                uid=uid,
                session_idx=0,
                category_id=cat_id,
                category_label=cat_label,
                title=title,
                summary=summary,
                start_date=start_date,
                end_date=end_date,
                start_time=None,
                end_time=None,
                location=None,
                location_name=None,
                city=None,
                district=None,
                on_sales=None,
                price=None,
                image_url=image_url,
                master_unit=master_unit,
                source_web=source_web,
                source_web_name=source_web_name,
            ))
        return sessions

    for idx, s in enumerate(show_info):
        start_date, start_time = parse_iculture_datetime(s.get("time"))
        end_date, end_time = parse_iculture_datetime(s.get("endTime"))
        loc = (s.get("location") or "").strip() or None
        loc_name = (s.get("locationName") or "").strip() or None
        city = extract_city(loc, loc_name)
        district = extract_district(loc)
        sessions.append(ScrapedSession(
            uid=uid,
            session_idx=idx,
            category_id=cat_id,
            category_label=cat_label,
            title=title,
            summary=summary,
            start_date=start_date,
            end_date=end_date,
            start_time=start_time,
            end_time=end_time,
            location=loc,
            location_name=loc_name,
            city=city,
            district=district,
            on_sales=s.get("onSales"),
            price=(s.get("price") or "").strip() or None,
            image_url=image_url,
            master_unit=master_unit,
            source_web=source_web,
            source_web_name=source_web_name,
        ))
    return sessions


def pricing_tag(on_sales: str | None, price: str | None) -> tuple[str, str | None]:
    """從 onSales/price 推測 pricing_tag 和 cost_note"""
    if on_sales == "N":
        return "免費", None
    if price:
        # price 可能是「200 / 300」這種,抓第一個數字
        m = re.search(r"(\d{2,5})", price)
        if m:
            amt = int(m.group(1))
            note = price[:60]
            if amt <= 300:
                return "小額收費", note
            return "收費", note
    # onSales=Y 但沒 price 數字
    if on_sales == "Y":
        return "小額收費", "詳情見連結"
    return "免費", None


def to_activity_row(sess: ScrapedSession) -> dict[str, Any]:
    category = refine_category(ICULTURE_CATEGORIES.get(sess.category_id, ("culture", ""))[0],
                                sess.title, sess.summary)
    tag_price, cost_note = pricing_tag(sess.on_sales, sess.price)

    tags = [tag_price, "文化部iCulture", sess.category_label]

    # 時間範圍併入 summary 開頭方便顯示
    time_prefix = ""
    if sess.start_time:
        time_prefix = f"{sess.start_time}"
        if sess.end_time and sess.end_time != sess.start_time:
            time_prefix += f"-{sess.end_time}"
        time_prefix += " · "

    summary_out = None
    if sess.summary:
        summary_out = (time_prefix + sess.summary)[:300]
    elif time_prefix:
        summary_out = time_prefix.rstrip(" ·")

    event_type = "single" if sess.start_date else "recurring"

    signup_url = sess.source_web or f"https://cloud.culture.tw/frontsite/activeInfoAction.do?method=doFindShowById&showId={sess.uid}"

    return {
        "title": sess.title[:140],
        "summary": summary_out,
        "description": sess.summary[:800] if sess.summary else None,
        "organizer_name": sess.master_unit or sess.source_web_name or "文化部iCulture",
        "event_type": event_type,
        "start_date": sess.start_date,
        "end_date": sess.end_date,
        "recurring_rule": None,
        "location_name": sess.location_name,
        "city": sess.city,
        "district": sess.district,
        "category": category,
        "tags": tags,
        "target_audience": "不限",
        "cost": 0,  # iCulture price 欄位不標準,保守填 0;實際金額放 cost_note
        "cost_note": cost_note,
        "signup_method": "online",
        "signup_url": signup_url,
        "source_url": sess.synthetic_source_url,
        "source_name": SOURCE_NAME,
        "status": "active",
        "image_url": sess.image_url,
    }


def scrape_all(categories: list[int], *, parallel: int = 4) -> list[ScrapedSession]:
    all_sessions: list[ScrapedSession] = []
    print(f"=== 抓 iCulture 共 {len(categories)} 個 category: {categories} ===", flush=True)

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        fut_to_cat = {pool.submit(fetch_category, c): c for c in categories}
        for fut in as_completed(fut_to_cat):
            cat_id = fut_to_cat[fut]
            try:
                events = fut.result() or []
            except Exception as e:
                print(f"[error] cat={cat_id}: {e}", file=sys.stderr)
                continue
            cat_sessions: list[ScrapedSession] = []
            for ev in events:
                cat_sessions.extend(expand_sessions(ev, cat_id))
            label = ICULTURE_CATEGORIES.get(cat_id, ("?", "?"))[1]
            print(f"  cat={cat_id:>2} {label:<5} → {len(events)} events, {len(cat_sessions)} sessions",
                  flush=True)
            all_sessions.extend(cat_sessions)
    return all_sessions


def upsert_to_supabase(rows: list[dict], supa_url: str, supa_key: str,
                       *, chunk: int = 500) -> tuple[int, int]:
    """回傳 (inserted, skipped_existing)"""
    if not rows:
        return 0, 0

    # 去重:先撈已存在的 source_url(限制在此 source_name)
    q = (
        f"{supa_url}/rest/v1/activities?select=source_url"
        f"&source_name=eq.{urllib.parse.quote(SOURCE_NAME)}"
        f"&source_url=not.is.null"
    )
    existing: set[str] = set()
    offset = 0
    limit = 1000
    while True:
        req = urllib.request.Request(
            f"{q}&limit={limit}&offset={offset}",
            headers={
                "apikey": supa_key,
                "Authorization": f"Bearer {supa_key}",
            },
        )
        with _NO_PROXY_OPENER.open(req, timeout=30) as r:
            batch = json.loads(r.read())
        if not batch:
            break
        for x in batch:
            if x.get("source_url"):
                existing.add(x["source_url"])
        if len(batch) < limit:
            break
        offset += limit

    # 先在 batch 內去重(iCulture 偶爾會返回同 event 兩次)
    seen_in_batch: set[str] = set()
    dedup_rows: list[dict] = []
    for r in rows:
        u = r.get("source_url")
        if not u or u in seen_in_batch:
            continue
        seen_in_batch.add(u)
        dedup_rows.append(r)

    new_rows = [r for r in dedup_rows if r["source_url"] not in existing]
    skipped = len(rows) - len(new_rows)
    if not new_rows:
        return 0, skipped

    inserted = 0
    for i in range(0, len(new_rows), chunk):
        batch = new_rows[i:i + chunk]
        insert_url = f"{supa_url}/rest/v1/activities"
        data = json.dumps(batch).encode()
        req = urllib.request.Request(
            insert_url, data=data, method="POST",
            headers={
                "apikey": supa_key,
                "Authorization": f"Bearer {supa_key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
        )
        try:
            with _NO_PROXY_OPENER.open(req, timeout=90) as r:
                r.read()
        except urllib.error.HTTPError as e:
            # 把 DB 回的錯誤訊息展開,方便未來 debug(否則只會看到 HTTP 400 Bad Request)
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                body = "(無法讀 response body)"
            print(f"\n[error] Supabase 回 HTTP {e.code} — 拒絕這批 {len(batch)} 筆", file=sys.stderr)
            print(f"[error] response body: {body[:600]}", file=sys.stderr)
            print(f"[error] 第一筆 row 樣本:\n{json.dumps(batch[0], ensure_ascii=False, indent=2)[:800]}",
                  file=sys.stderr)
            raise
        inserted += len(batch)
        print(f"  upsert {i + len(batch)}/{len(new_rows)}", flush=True)
    return inserted, skipped


def print_stats(sessions: list[ScrapedSession]) -> None:
    from collections import Counter
    from datetime import date
    today = date.today().isoformat()

    cat_c = Counter(s.category_label for s in sessions)
    city_c = Counter(s.city or "(null)" for s in sessions)
    future_45 = sum(1 for s in sessions if s.start_date and s.start_date >= today
                    and s.start_date <= (date.today().replace(day=1).isoformat()
                                         if False else "2099-12-31")
                    and s.start_date <= _add_days(today, 45))

    print(f"\n=== 統計 (total sessions: {len(sessions)}) ===")
    print(f"category:")
    for k, v in cat_c.most_common():
        print(f"  {v:5d}  {k}")
    print(f"city (top 15):")
    for k, v in city_c.most_common(15):
        print(f"  {v:5d}  {k}")

    # 雙北未來 45 天 single
    双北_45 = [s for s in sessions
              if s.city in ("台北市", "新北市")
              and s.start_date
              and s.start_date >= today
              and s.start_date <= _add_days(today, 45)]
    print(f"\n雙北 + 未來 45 天 + 有 start_date: {len(双北_45)} 筆")
    print(f"(對比目前 DB 此條件僅 2 筆)")


def _add_days(date_str: str, days: int) -> str:
    from datetime import date, timedelta
    y, m, d = date_str.split("-")
    dt = date(int(y), int(m), int(d)) + timedelta(days=days)
    return dt.isoformat()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=str, help="寫出 sessions JSON 路徑(dry-run 用)")
    ap.add_argument("--upsert", action="store_true", help="寫 Supabase")
    ap.add_argument("--categories", type=str,
                    help="只抓特定 category(逗號分隔,例 1,2,7)")
    ap.add_argument("--parallel", type=int, default=4)
    args = ap.parse_args()

    if args.categories:
        cats = [int(x.strip()) for x in args.categories.split(",") if x.strip()]
    else:
        cats = [c for c in ICULTURE_CATEGORIES.keys() if c not in SKIP_CATEGORIES]

    sessions = scrape_all(cats, parallel=args.parallel)
    print_stats(sessions)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump([asdict(s) for s in sessions], f, ensure_ascii=False, indent=2)
        print(f"\nJSON → {args.out}")

    if args.upsert:
        supa_url = os.environ.get("SUPABASE_URL")
        supa_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not supa_url or not supa_key:
            print("[error] 缺 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY", file=sys.stderr)
            return 2
        rows = [to_activity_row(s) for s in sessions]
        # 先 filter 掉沒 start_date 又沒 title 的(防守)
        rows = [r for r in rows if r.get("title")]
        inserted, skipped = upsert_to_supabase(rows, supa_url, supa_key)
        print(f"\nSupabase 新插入 {inserted} 筆(已存在跳過 {skipped} 筆)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
