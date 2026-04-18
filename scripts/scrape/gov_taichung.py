#!/usr/bin/env python3
"""
台中市政府文化局 — 藝文活動查詢 JSON 爬蟲
資料源: https://activity.culture.taichung.gov.tw/_dataaction/index.asp

涵蓋:台中市 29 個區的藝文類活動(展覽/表演/影片/閱讀/講座/研習/社區/文資)
資料量:單次 N 百筆(依當時在展活動數動態變化)

JSON schema(台中文化局給的格式有 trailing commas,不是標準 JSON):
{
  "GenericData": {
    "Dataset": {
      "ROW": [
        {
          "活動名稱": "...",
          "活動展演(起訖)": "2026-07-18 ~ 2026-07-18 14:00-16:00",  # 也可能只有日期沒時間
          "活動售票與否": "否" or "是",
          "活動網址": "...",            # 有時沒有
          "地點": "葫蘆墩文化中心",
          "相關圖片": "https://...",     # 有時沒有
        },
        ...
      ]
    }
  }
}

去重鍵:source_url(活動網址),沒有的話 fallback 用 title+start_date 生 hash。

執行:
  python3 scripts/scrape/gov_taichung.py --out /tmp/taichung.json
  SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... \\
    python3 scripts/scrape/gov_taichung.py --upsert
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from typing import Any

API_URL = "https://activity.culture.taichung.gov.tw/_dataaction/index.asp"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
SOURCE_NAME = "台中市政府文化局"
CITY = "台中市"

# 強制不走 system proxy(Clash 關閉時會 Connection refused)
_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# 台中 29 區(官方順序)
TAICHUNG_DISTRICTS = [
    "中區", "東區", "西區", "南區", "北區",
    "西屯區", "南屯區", "北屯區",
    "豐原區", "大里區", "太平區", "東勢區",
    "大甲區", "清水區", "沙鹿區", "梧棲區",
    "后里區", "神岡區", "潭子區", "大雅區",
    "新社區", "石岡區", "外埔區", "大安區",
    "烏日區", "大肚區", "龍井區", "霧峰區", "和平區",
]

# 場地 → 區 對照表(從官網資料歸納,主要館別先列)
VENUE_TO_DISTRICT: dict[str, str] = {
    "葫蘆墩文化中心": "豐原區",
    "葫蘆墩漆藝館": "豐原區",
    "豐原漆藝館": "豐原區",
    "港區藝術中心": "清水區",
    "大墩文化中心": "西區",
    "屯區藝文中心": "大里區",
    "纖維工藝博物館": "大里區",
    "臺中市纖維工藝博物館": "大里區",
    "臺中國家歌劇院": "西屯區",
    "臺中文學館": "西區",
    "臺灣民俗文物館": "北屯區",
    "牛罵頭遺址文化園區": "清水區",
    "臺中州廳": "西區",
    "摘星山莊": "潭子區",
    "社口林宅": "神岡區",
    "社口萬興宮": "神岡區",
    "林懋陽故居": "北屯區",
    "一德洋樓": "北屯區",
    "臺中刑務所演武場": "西區",
    "臺中市役所": "西區",
    "中興堂": "北區",
    "臺灣體育運動大學中興堂": "北區",
    "清水眷村文化園區": "清水區",
    "臺中市眷村文物館": "北屯區",
    "臺中公園湖心亭": "北區",
    "臺中市長公館": "北區",
    "臺中放送局": "北區",
    "臺中國際會展中心": "烏日區",
    "霧峰林家宮保第園區": "霧峰區",
    "林家花園": "霧峰區",
    "光復新村": "霧峰區",
    "省諮議會": "霧峰區",
    "神岡方舟莊園": "神岡區",
    "神岡區公所": "神岡區",
    "月眉糖廠": "后里區",
    "后里張天機宅": "后里區",
    "東勢客家文化園區": "東勢區",
    "裕珍馨三寶文化館": "大甲區",
    "孫立人將軍故居": "北區",
    "梧棲浩天宮": "梧棲區",
    "梧棲朝元宮": "梧棲區",
    "梧棲真武宮": "梧棲區",
    "梧棲老街": "梧棲區",
    "大甲鎮瀾宮": "大甲區",
    "大肚萬興宮": "大肚區",
    "大肚磺溪書院": "大肚區",
    "南屯萬和宮": "南屯區",
    "大里杙福興宮": "大里區",
    "北屯南興宮": "北屯區",
    "北屯文昌廟": "北屯區",
    "豐原慈濟宮": "豐原區",
    "中區台中萬春宮": "中區",
    "旱溪樂成宮": "東區",
    "張連昌薩克斯風博物館": "后里區",
    "臺中太陽餅博物館": "中區",
    "林之助紀念館": "西區",
    "美術綠園道": "西區",
    "美術園道": "西區",
    "草悟道": "西區",
    "草悟廣場": "西區",
    "經國園道": "西區",
    "審計新村": "西區",
    "范特喜": "西區",
    "市民廣場": "西區",
    "文化部文化資產園區": "南區",
    "台中文化創意產業園區": "南區",
    "文創園區": "南區",
    "繼光商圈": "中區",
    "舊火車站": "中區",
    "洲際棒球場": "北屯區",
    "後壁湖": "和平區",
    "梨山": "和平區",
}

# 圖書館分館對照(命名很多有「XX 分館」)
LIBRARY_BRANCH_DISTRICT: dict[str, str] = {
    "中區分館": "中區", "東區分館": "東區", "西區分館": "西區", "南區分館": "南區", "北區分館": "北區",
    "西屯分館": "西屯區", "南屯分館": "南屯區", "北屯分館": "北屯區",
    "大里分館": "大里區", "大里大新分館": "大里區", "大里德芳分館": "大里區", "大墩分館": "西區",
    "大甲分館": "大甲區", "大肚分館": "大肚區", "大肚瑞井分館": "大肚區",
    "大雅分館": "大雅區", "大安分館": "大安區",
    "葫蘆墩分館": "豐原區", "豐原分館": "豐原區", "豐原南嵩分館": "豐原區",
    "太平分館": "太平區", "太平坪林分館": "太平區",
    "清水分館": "清水區", "沙鹿文昌分館": "沙鹿區", "沙鹿深波分館": "沙鹿區",
    "東勢分館": "東勢區", "東勢許良宇": "東勢區",
    "梧棲分館": "梧棲區", "梧棲親子館": "梧棲區",
    "烏日分館": "烏日區", "神岡分館": "神岡區",
    "后里分館": "后里區", "和平區圖書館": "和平區",
    "霧峰以文分館": "霧峰區", "潭子分館": "潭子區",
    "龍井分館": "龍井區", "龍井山頂分館": "龍井區", "龍井龍津分館": "龍井區",
    "外埔分館": "外埔區", "石岡分館": "石岡區", "新社分館": "新社區",
    "上楓分館": "大雅區",
    "興安分館": "北屯區",
    "溪東分館": "大里區", "溪西分館": "大肚區",
    "精武圖書館": "東區",
    "四張犁分館": "北屯區",
    "李科永紀念圖書分館": "沙鹿區",
    "國立公共資訊圖書館": "南區",
}

CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("sports",    ("馬拉松", "路跑", "健走", "自行車", "單車", "球賽", "運動", "瑜珈", "瑜伽", "太極")),
    ("travel",    ("旅遊", "踏青", "走讀", "小旅行", "巡禮", "環島")),
    ("social",    ("市集", "園遊", "同樂", "共餐", "祖孫", "親子")),
    ("health",    ("健康", "養生", "保健", "醫療", "篩檢", "失智", "防疫")),
    ("volunteer", ("志工", "志願")),
    ("learning",  ("講座", "論壇", "研習", "工作坊", "體驗營", "讀書會", "培訓", "課程", "研討")),
    ("culture",   ("展", "演", "音樂", "歌", "戲", "藝術", "文學", "電影", "影展", "燈會",
                   "節慶", "嘉年華", "博覽會", "導覽", "特展", "個展", "閱讀", "文資", "古蹟")),
]


@dataclass
class ScrapedItem:
    title: str
    date_raw: str
    ticketed: bool
    location_name: str | None
    url: str | None
    image_url: str | None


def fetch_json(url: str, *, retries: int = 3, timeout: int = 60) -> str:
    last = None
    headers = {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
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
    raise RuntimeError(f"fetch failed: {url}: {last}")


def parse_json_loose(raw: str) -> dict[str, Any]:
    """台中文化局的 JSON 有 trailing commas + 夾控制字元,先清掉再寬鬆 parse。"""
    # 1. 移除 trailing commas 在 } 或 ] 之前
    cleaned = re.sub(r",(\s*[}\]])", r"\1", raw)
    # 2. 移除 JSON 絕對不允許的控制字元(U+0000–U+001F, 除 \t \n \r)
    #    對方 payload 有時夾垂直 tab / form feed / 裸 0x1F 之類
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", cleaned)
    # 3. strict=False 讓 json.loads 接受字串裡 raw 的 \t \n \r
    #    (台中文化局某些欄位裡有直接塞 tab,strict 模式會炸
    #     "Invalid control character at: line N column M")
    return json.loads(cleaned, strict=False)


def parse_date_range(s: str) -> tuple[str | None, str | None, str | None, str | None]:
    """解析 "2026-07-18 ~ 2026-07-18 14:00-16:00" 或 "2026-07-01 ~ 2026-07-31 9:00-17:30" 或 "2026-07-18 ~ 2026-07-18 "
    回傳 (start_date, end_date, start_time, end_time)。"""
    if not s:
        return None, None, None, None
    t = s.strip()

    # 日期部分
    date_pat = r"(\d{4}-\d{2}-\d{2})"
    dm = re.search(rf"{date_pat}\s*~\s*{date_pat}", t)
    if dm:
        start_date, end_date = dm.group(1), dm.group(2)
    else:
        dm1 = re.search(date_pat, t)
        if dm1:
            start_date = end_date = dm1.group(1)
        else:
            start_date = end_date = None

    # 時間部分(可能缺)。規格用 H:MM 或 HH:MM
    tm = re.search(r"(\d{1,2}:\d{2})\s*[-~]\s*(\d{1,2}:\d{2})", t)
    if tm:
        start_time = _pad_time(tm.group(1))
        end_time = _pad_time(tm.group(2))
    else:
        start_time = end_time = None

    return start_date, end_date, start_time, end_time


def _pad_time(t: str) -> str:
    """把 9:00 補成 09:00"""
    h, m = t.split(":")
    return f"{int(h):02d}:{m}"


def guess_district(location_name: str | None) -> str | None:
    if not location_name:
        return None
    loc = location_name.strip()

    # 第一優先:精確場地對照
    for venue, district in VENUE_TO_DISTRICT.items():
        if venue in loc:
            return district
    # 第二優先:圖書館分館對照
    for branch, district in LIBRARY_BRANCH_DISTRICT.items():
        if branch in loc:
            return district
    # 第三優先:字面有區名
    for d in TAICHUNG_DISTRICTS:
        if d in loc:
            return d
    return None


def guess_category(title: str, location_name: str | None) -> str:
    text = title + " " + (location_name or "")
    for cat, kws in CATEGORY_KEYWORDS:
        for kw in kws:
            if kw in text:
                return cat
    return "culture"  # 文化局資料 default culture


def synthetic_source_url(item: ScrapedItem, start_date: str | None) -> str:
    """沒有 url 時,用 title + date + location 雜湊出一個穩定的 id。"""
    h = hashlib.sha1(
        f"{item.title}|{start_date}|{item.location_name or ''}".encode("utf-8")
    ).hexdigest()[:12]
    return f"taichung-culture://{h}"


def scrape_all() -> list[ScrapedItem]:
    print(f"=== 抓 {API_URL} ===", flush=True)
    raw = fetch_json(API_URL)
    data = parse_json_loose(raw)
    rows = data.get("GenericData", {}).get("Dataset", {}).get("ROW", [])
    items: list[ScrapedItem] = []
    for r in rows:
        title = (r.get("活動名稱") or "").strip()
        date_raw = (r.get("活動展演(起訖)") or "").strip()
        ticket = (r.get("活動售票與否") or "").strip()
        url = (r.get("活動網址") or "").strip() or None
        # 修掉偶爾看到的 "http://h..." 或 "http://hhttps://" 類的錯誤
        if url and url.startswith("http://h") and "https://" in url:
            url = url[url.index("https://"):]
        loc = (r.get("地點") or "").strip() or None
        img = (r.get("相關圖片") or "").strip() or None

        if not title:
            continue
        items.append(ScrapedItem(
            title=title,
            date_raw=date_raw,
            ticketed=(ticket == "是"),
            location_name=loc,
            url=url,
            image_url=img,
        ))
    print(f"[json] → {len(items)} 筆", flush=True)
    return items


def to_activity_row(item: ScrapedItem) -> dict[str, Any]:
    start_date, end_date, start_time, end_time = parse_date_range(item.date_raw)
    district = guess_district(item.location_name)
    category = guess_category(item.title, item.location_name)

    cost = 0
    pricing_tag = "免費"
    cost_note = None
    if item.ticketed:
        # JSON 沒有票價數字,只有「是/否」— 標「收費」,詳情請看連結
        cost = 0  # 無確切票價
        pricing_tag = "小額收費"
        cost_note = "詳情請見活動連結"

    # event_type: 有完整日期 → single;無日期 → recurring(避免被過期過濾掉)
    event_type = "single" if start_date else "recurring"

    tags = ["藝文", "台中文化局", pricing_tag]

    source_url = item.url or synthetic_source_url(item, start_date)

    return {
        "title": item.title[:140],
        "summary": None,   # JSON 沒摘要,維持空
        "description": None,
        "organizer_name": SOURCE_NAME,
        "event_type": event_type,
        "start_date": start_date,
        "end_date": end_date,
        "start_time": start_time,
        "end_time": end_time,
        "recurring_rule": None,
        "location_name": item.location_name,
        "city": CITY,
        "district": district,
        "category": category,
        "tags": tags,
        "target_audience": "不限",
        "cost": cost,
        "cost_note": cost_note,
        "signup_method": "online" if item.url else "none",
        "signup_url": item.url,
        "source_url": source_url,
        "source_name": SOURCE_NAME,
        "status": "active",
        "image_url": item.image_url,
    }


# ---- 圖片 URL 驗證 ----
# 台中文化局 JSON 常給出檔名對不上實際檔案的 image_url(e.g. title 和 filename
# 不一致),對方 server 找不到檔案時會 302 redirect 到 html error page,
# 不是真的 200 image。前端直接顯示破圖。解法:HEAD 驗證,壞的存 null。

def _is_image_url_ok(url: str | None, *, timeout: int = 8) -> bool:
    """HEAD 驗證 image URL。200 + image/* content-type 才算 OK。
    302 / 404 / 例外 / 非 image content-type 都算壞。
    不 follow redirect(對方壞路徑會 302 到 html error 頁)。"""
    if not url:
        return False
    try:
        # 用 no-redirect handler(urllib 預設 follow redirect,這裡強制關掉)
        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
        with opener.open(req, timeout=timeout) as r:
            code = r.status
            ct = (r.headers.get("Content-Type") or "").lower()
            return code == 200 and ct.startswith("image/")
    except Exception:
        return False


def validate_image_urls(items: list[ScrapedItem], *, workers: int = 10) -> int:
    """並行 HEAD 驗證 items 裡的 image_url,壞的 set None。回傳清掉幾張。"""
    from concurrent.futures import ThreadPoolExecutor

    targets = [(i, it.image_url) for i, it in enumerate(items) if it.image_url]
    if not targets:
        return 0
    print(f"[image-check] 驗證 {len(targets)} 張 image_url...", flush=True)

    def _check(idx_url: tuple[int, str]) -> tuple[int, bool]:
        idx, url = idx_url
        return idx, _is_image_url_ok(url)

    cleaned = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for idx, ok in ex.map(_check, targets):
            if not ok:
                items[idx].image_url = None
                cleaned += 1
    print(f"[image-check] → {cleaned} 張壞圖設 null(保留 {len(targets) - cleaned} 張)", flush=True)
    return cleaned


def sweep_bad_image_urls_in_db(supa_url: str, supa_key: str, *, workers: int = 10) -> int:
    """掃 Supabase 裡 source_name=台中文化局 且 image_url 非 null 的 rows,
    HEAD 驗證,壞的 UPDATE 成 null。一次性清理既有髒資料。回傳清了幾筆。"""
    from concurrent.futures import ThreadPoolExecutor

    # 1. 撈目標 rows(要分頁,PostgREST 預設 max 1000)
    all_rows: list[dict] = []
    offset = 0
    PAGE = 1000
    while True:
        q = (
            f"{supa_url}/rest/v1/activities?"
            f"source_name=eq.{urllib.parse.quote(SOURCE_NAME)}"
            f"&image_url=not.is.null&select=id,image_url"
            f"&limit={PAGE}&offset={offset}"
        )
        req = urllib.request.Request(q, headers={
            "apikey": supa_key,
            "Authorization": f"Bearer {supa_key}",
        })
        with _NO_PROXY_OPENER.open(req, timeout=60) as r:
            chunk = json.loads(r.read())
        if not chunk:
            break
        all_rows.extend(chunk)
        if len(chunk) < PAGE:
            break
        offset += PAGE

    print(f"[sweep] 台中文化局有 image_url 的 rows:{len(all_rows)} 筆", flush=True)
    if not all_rows:
        return 0

    # 2. 並行 HEAD
    def _check(row: dict) -> int | None:
        return None if _is_image_url_ok(row["image_url"]) else row["id"]

    bad_ids: list[int] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        done = 0
        for result in ex.map(_check, all_rows):
            done += 1
            if result is not None:
                bad_ids.append(result)
            if done % 100 == 0:
                print(f"[sweep] 已驗證 {done}/{len(all_rows)},目前找到 {len(bad_ids)} 筆壞圖", flush=True)

    print(f"[sweep] 驗證完畢:{len(bad_ids)} 筆壞圖,{len(all_rows) - len(bad_ids)} 筆 OK", flush=True)
    if not bad_ids:
        return 0

    # 3. 分批 PATCH image_url=null
    BATCH = 100
    total = 0
    for i in range(0, len(bad_ids), BATCH):
        chunk = bad_ids[i:i + BATCH]
        ids_param = ",".join(str(x) for x in chunk)
        upd_url = f"{supa_url}/rest/v1/activities?id=in.({ids_param})"
        data = json.dumps({"image_url": None}).encode()
        req = urllib.request.Request(
            upd_url, data=data, method="PATCH",
            headers={
                "apikey": supa_key,
                "Authorization": f"Bearer {supa_key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
        )
        with _NO_PROXY_OPENER.open(req, timeout=60) as r:
            r.read()
        total += len(chunk)
        print(f"[sweep] 已清 {total}/{len(bad_ids)}", flush=True)
    return total


def upsert_to_supabase(rows: list[dict], supa_url: str, supa_key: str) -> int:
    if not rows:
        return 0
    # 去重:先撈這個 source_name 下已存在的 source_url
    q = (
        f"{supa_url}/rest/v1/activities?select=source_url"
        f"&source_name=eq.{urllib.parse.quote(SOURCE_NAME)}"
        # Supabase 預設 max 1000 rows,如果未來超過要分批,但目前單次幾百筆沒問題
    )
    req = urllib.request.Request(q, headers={
        "apikey": supa_key,
        "Authorization": f"Bearer {supa_key}",
    })
    with _NO_PROXY_OPENER.open(req, timeout=30) as r:
        existing = {x["source_url"] for x in json.loads(r.read()) if x.get("source_url")}

    new_rows = [r for r in rows if r.get("source_url") and r["source_url"] not in existing]
    if not new_rows:
        return 0

    # 台中一次可能幾百筆,分批 insert 每次 500 筆避免 request 太大
    BATCH = 500
    total_inserted = 0
    for i in range(0, len(new_rows), BATCH):
        chunk = new_rows[i:i + BATCH]
        insert_url = f"{supa_url}/rest/v1/activities"
        data = json.dumps(chunk).encode()
        req = urllib.request.Request(
            insert_url, data=data, method="POST",
            headers={
                "apikey": supa_key,
                "Authorization": f"Bearer {supa_key}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
        )
        with _NO_PROXY_OPENER.open(req, timeout=120) as r:
            out = json.loads(r.read())
        total_inserted += len(out)
    return total_inserted


def main() -> int:
    import os
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=str)
    ap.add_argument("--upsert", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.0)  # 為了跟其他 scraper 維持 arg 介面一致
    ap.add_argument("--skip-image-check", action="store_true",
                    help="跳過 image_url HEAD 驗證(預設會驗證,壞的設 null)")
    ap.add_argument("--sweep-images", action="store_true",
                    help="不抓新資料,單純掃 DB 既有 image_url,壞的 UPDATE 成 null")
    args = ap.parse_args()

    # Sweep-only 模式:不抓新資料,只清既有髒 image_url
    if args.sweep_images:
        supa_url = os.environ.get("SUPABASE_URL")
        supa_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not supa_url or not supa_key:
            print("[error] 缺 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY", file=sys.stderr)
            return 2
        n = sweep_bad_image_urls_in_db(supa_url, supa_key)
        print(f"\n=== Sweep 完成:{n} 筆壞圖 image_url 清為 null ===")
        return 0

    items = scrape_all()
    print(f"\n=== 共 {len(items)} 筆 ===")

    # 統計資訊
    from collections import Counter
    cat_c: Counter[str] = Counter()
    dist_c: Counter[str] = Counter()
    no_date = 0
    for x in items:
        cat_c[guess_category(x.title, x.location_name)] += 1
        d = guess_district(x.location_name) or "(未知區)"
        dist_c[d] += 1
        sd, _, _, _ = parse_date_range(x.date_raw)
        if not sd:
            no_date += 1

    print(f"  category: {dict(cat_c)}")
    print(f"  districts: {dict(dist_c.most_common())}")
    print(f"  無日期: {no_date} 筆(會標 recurring,避免被過期濾掉)")

    # 驗 image_url 是否可達,壞的 set None(預設開;--skip-image-check 可關)
    if not args.skip_image_check:
        validate_image_urls(items)

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
        print(f"Supabase 新插入 {inserted} 筆")

    return 0


if __name__ == "__main__":
    sys.exit(main())
