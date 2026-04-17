#!/usr/bin/env python3
"""
教育部樂齡學習網爬蟲 — 全台 22 縣市子網站
https://moe.senioredu.moe.gov.tw/

每個縣市子網站 Index 頁面列出三類資訊:
  - ContentEducation  (教育/縣市政府 公告)
  - ContentGoverment  (中央單位 公告)
  - ContentSeniorCenter (樂齡學習中心 課程/活動公告) ← 這才是活動資料

每個「樂齡中心」條目通常是當月課程表彙整(例如「萬華區樂齡學習中心115年4月份課程表」),
本爬蟲以一筆公告 = 一筆 activity,導到原始連結查詳情。
粒度:月。未來如果要做到單堂課,要下載 PDF/圖片另外解析。

執行方式:
  # 僅抓取、不寫 DB,輸出 JSON
  python3 scripts/scrape/senioredu_moe.py --out /tmp/senioredu.json

  # 抓取後直接寫入 Supabase
  SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... python3 scripts/scrape/senioredu_moe.py --upsert
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

BASE = "https://moe.senioredu.moe.gov.tw"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 LohasCardBot/0.1"

# 22 縣市子站代號 → 中文城市名
CITY_MAP: dict[str, str] = {
    "Taipei":         "台北市",
    "Xinbei":         "新北市",
    "Keelung":        "基隆市",
    "Taoyuan":        "桃園市",
    "Hsinchu":        "新竹市",
    "HsinchuCounty":  "新竹縣",
    "Yilan":          "宜蘭縣",
    "Miaoli":         "苗栗縣",
    "Taichung":       "台中市",
    "Changhua":       "彰化縣",
    "Nantou":         "南投縣",
    "Yunlin":         "雲林縣",
    "Chiayi":         "嘉義市",
    "ChiayiCounty":   "嘉義縣",
    "Tainan":         "台南市",
    "Kaohsiung":      "高雄市",
    "Pingtung":       "屏東縣",
    "Hualien":        "花蓮縣",
    "Taitung":        "台東縣",
    "Penghu":         "澎湖縣",
    "Kinmen":         "金門縣",
    "Lianjiang":      "連江縣",
}

# 每個縣市的合法鄉鎮市區清單(簡化版,用於 district 匹配;缺某些偏鄉 OK,regex fallback 會接手)
# 這份列表不追求完整,只要涵蓋樂齡中心所在的地區即可。完整版在 lib/taiwan-regions.ts
CITY_DISTRICTS: dict[str, list[str]] = {
    "台北市": ["松山區","信義區","大安區","中山區","中正區","大同區","萬華區","文山區","南港區","內湖區","士林區","北投區"],
    "新北市": ["板橋區","三重區","中和區","永和區","新莊區","新店區","土城區","蘆洲區","樹林區","汐止區","鶯歌區","三峽區","淡水區","瑞芳區","五股區","泰山區","林口區","深坑區","石碇區","坪林區","三芝區","石門區","八里區","平溪區","雙溪區","貢寮區","金山區","萬里區","烏來區"],
    "基隆市": ["中正區","七堵區","暖暖區","仁愛區","中山區","安樂區","信義區"],
    "桃園市": ["桃園區","中壢區","平鎮區","八德區","楊梅區","蘆竹區","大溪區","龍潭區","龜山區","大園區","觀音區","新屋區","復興區"],
    "新竹市": ["東區","北區","香山區"],
    "新竹縣": ["竹北市","竹東鎮","新埔鎮","關西鎮","湖口鄉","新豐鄉","峨眉鄉","寶山鄉","北埔鄉","芎林鄉","橫山鄉","尖石鄉","五峰鄉"],
    "宜蘭縣": ["宜蘭市","羅東鎮","蘇澳鎮","頭城鎮","礁溪鄉","壯圍鄉","員山鄉","冬山鄉","五結鄉","三星鄉","大同鄉","南澳鄉"],
    "苗栗縣": ["苗栗市","頭份市","竹南鎮","後龍鎮","通霄鎮","苑裡鎮","卓蘭鎮","造橋鄉","頭屋鄉","公館鄉","大湖鄉","泰安鄉","銅鑼鄉","三義鄉","西湖鄉","獅潭鄉","三灣鄉","南庄鄉"],
    "台中市": ["中區","東區","南區","西區","北區","西屯區","南屯區","北屯區","豐原區","東勢區","大甲區","清水區","沙鹿區","梧棲區","后里區","神岡區","潭子區","大雅區","新社區","石岡區","外埔區","大安區","烏日區","大肚區","龍井區","霧峰區","太平區","大里區","和平區"],
    "彰化縣": ["彰化市","員林市","鹿港鎮","和美鎮","北斗鎮","溪湖鎮","田中鎮","二林鎮","線西鄉","伸港鄉","福興鄉","秀水鄉","花壇鄉","芬園鄉","大村鄉","埔鹽鄉","埔心鄉","永靖鄉","社頭鄉","二水鄉","田尾鄉","埤頭鄉","芳苑鄉","大城鄉","竹塘鄉","溪州鄉"],
    "南投縣": ["南投市","埔里鎮","草屯鎮","竹山鎮","集集鎮","名間鄉","鹿谷鄉","中寮鄉","魚池鄉","國姓鄉","水里鄉","信義鄉","仁愛鄉"],
    "雲林縣": ["斗六市","斗南鎮","虎尾鎮","西螺鎮","土庫鎮","北港鎮","古坑鄉","大埤鄉","莿桐鄉","林內鄉","二崙鄉","崙背鄉","麥寮鄉","東勢鄉","褒忠鄉","台西鄉","元長鄉","四湖鄉","口湖鄉","水林鄉"],
    "嘉義市": ["東區","西區"],
    "嘉義縣": ["太保市","朴子市","布袋鎮","大林鎮","民雄鄉","溪口鄉","新港鄉","六腳鄉","東石鄉","義竹鄉","鹿草鄉","水上鄉","中埔鄉","竹崎鄉","梅山鄉","番路鄉","大埔鄉","阿里山鄉"],
    "台南市": ["中西區","東區","南區","北區","安平區","安南區","永康區","歸仁區","新化區","左鎮區","玉井區","楠西區","南化區","仁德區","關廟區","龍崎區","官田區","麻豆區","佳里區","西港區","七股區","將軍區","學甲區","北門區","新營區","後壁區","白河區","東山區","六甲區","下營區","柳營區","鹽水區","善化區","大內區","山上區","新市區","安定區"],
    "高雄市": ["鹽埕區","鼓山區","左營區","楠梓區","三民區","新興區","前金區","苓雅區","前鎮區","旗津區","小港區","鳳山區","林園區","大寮區","大樹區","大社區","仁武區","鳥松區","岡山區","橋頭區","燕巢區","田寮區","阿蓮區","路竹區","湖內區","茄萣區","永安區","彌陀區","梓官區","旗山區","美濃區","六龜區","甲仙區","杉林區","內門區","茂林區","桃源區","那瑪夏區"],
    "屏東縣": ["屏東市","潮州鎮","東港鎮","恆春鎮","萬丹鄉","長治鄉","麟洛鄉","九如鄉","里港鄉","鹽埔鄉","高樹鄉","萬巒鄉","內埔鄉","竹田鄉","新埤鄉","枋寮鄉","新園鄉","崁頂鄉","林邊鄉","南州鄉","佳冬鄉","琉球鄉","車城鄉","滿州鄉","枋山鄉","三地門鄉","霧臺鄉","瑪家鄉","泰武鄉","來義鄉","春日鄉","獅子鄉","牡丹鄉"],
    "花蓮縣": ["花蓮市","鳳林鎮","玉里鎮","新城鄉","吉安鄉","壽豐鄉","光復鄉","豐濱鄉","瑞穗鄉","富里鄉","秀林鄉","萬榮鄉","卓溪鄉"],
    "台東縣": ["台東市","成功鎮","關山鎮","卑南鄉","鹿野鄉","池上鄉","東河鄉","長濱鄉","太麻里鄉","大武鄉","綠島鄉","海端鄉","延平鄉","金峰鄉","達仁鄉","蘭嶼鄉"],
    "澎湖縣": ["馬公市","湖西鄉","白沙鄉","西嶼鄉","望安鄉","七美鄉"],
    "金門縣": ["金城鎮","金湖鎮","金沙鎮","金寧鄉","烈嶼鄉","烏坵鄉"],
    "連江縣": ["南竿鄉","北竿鄉","莒光鄉","東引鄉"],
}


@dataclass
class ScrapedItem:
    title: str
    source_url: str
    source_name: str              # "教育部樂齡學習網"
    organizer_name: str | None    # e.g. "萬華區樂齡學習中心"
    city: str
    district: str | None
    category: str                 # 預設 learning
    summary: str | None
    published: str | None         # yyyy-mm-dd
    raw_section: str              # SeniorCenter | Education | Government


def fetch(url: str, *, retries: int = 3, backoff: float = 2.0, timeout: int = 60) -> str:
    """下載 URL,自動重試,回傳解碼 HTML。

    timeout 給 60s — 從 GitHub Actions(美國機房)連台灣政府網站會很慢。
    """
    last_exc = None
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                # 處理 gzip
                if resp.headers.get("Content-Encoding") == "gzip":
                    import gzip
                    raw = gzip.decompress(raw)
                return raw.decode("utf-8", errors="replace")
        except Exception as e:
            last_exc = e
            time.sleep(backoff * (attempt + 1))
    raise RuntimeError(f"fetch failed: {url}: {last_exc}")


# ---- 解析函式 ----

# 從 "04/14" 等格式 + 頁面當前年猜絕對日期
def parse_date(md: str, ref_year: int) -> str | None:
    m = re.match(r"(\d{1,2})\s*/\s*(\d{1,2})$", md.strip())
    if not m:
        return None
    mm, dd = int(m.group(1)), int(m.group(2))
    if 1 <= mm <= 12 and 1 <= dd <= 31:
        return f"{ref_year:04d}-{mm:02d}-{dd:02d}"
    return None


# 一個 Senior/Education 條目的 HTML 片段(來自 index table)通常看起來是:
#   <tr>
#     <td>04/14</td>
#     <td><a href="..." title="...">TITLE</a></td>
#     <td>...more links...</td>
#   </tr>
# 但這網站比較亂,用更寬鬆的 regex 對整個 table 掃。
#
# 另一種模式:首頁有三個獨立列表區,每區用 <div id="xxx"><ul> 或 <tbody> 包住。
# 最穩的做法:用「標題 anchor」的 href 特徵當錨點,往前回找日期。

# 從 href=".../*CenterMoreNews?...enFormId=XXX" 取 SeniorCenter
SENIOR_LINK_RE = re.compile(
    r"""<a[^>]+href="(/HomeSon/([A-Za-z]+)/\2CenterMoreNews\?seniorCenterMessageFileViewModel\.enFormId=([^"]+))"[^>]*>([^<]{5,200}?)</a>""",
    re.S,
)
# Education 類
EDU_LINK_RE = re.compile(
    r"""<a[^>]+href="(/HomeSon/([A-Za-z]+)/\2EduMoreNews\?educationMessageFileViewModel\.enFormId=([^"]+))"[^>]*>([^<]{5,200}?)</a>""",
    re.S,
)
# Government 類 (中央單位,通常是全台通用公告,對活動頁 UX 價值較低,先不納入)
GOV_LINK_RE = re.compile(
    r"""<a[^>]+href="(/HomeSon/([A-Za-z]+)/\2GovMoreNews\?governmentMessageFileViewModel\.enFormId=([^"]+))"[^>]*>([^<]{5,200}?)</a>""",
    re.S,
)

# 從 title 裡拆出「(臺/台)北市萬華區樂齡學習中心」→ district
DISTRICT_TAG_RE = re.compile(r"[臺台]?[北新桃中南高基宜苗彰投雲嘉屏花東澎金連]\w?[市縣]?([\u4e00-\u9fff]{2,4}[區鄉鎮市])")
# 中心名稱
CENTER_RE = re.compile(r"([\u4e00-\u9fff]{2,6}(?:樂齡學習|樂齡|長青|銀髮)[\u4e00-\u9fff]*(?:中心|據點|大學|教室))")
# 括號中的中心名 e.g. 【大同樂齡中心】
BRACKET_CENTER_RE = re.compile(r"[【\[]\s*([^】\]]{2,30})\s*[】\]]")


def clean_text(s: str) -> str:
    s = html_lib.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def extract_district(title: str, city: str) -> str | None:
    """從標題抽該縣市的合法鄉鎮市區。優先用白名單比對,fallback 用 regex。"""
    candidates = CITY_DISTRICTS.get(city, [])
    # 1. 完整名稱白名單(長字優先)
    matches = [d for d in candidates if d in title]
    if matches:
        matches.sort(key=len, reverse=True)
        return matches[0]
    # 2. 前綴白名單 — 容許標題寫「大同樂齡」而省略「區」
    prefix_matches: list[str] = []
    for d in candidates:
        if len(d) >= 3:  # 三字以上直接 match 前兩字(如「大同區」→「大同」)
            prefix = d[:-1]  # 去掉最後的「區/鄉/鎮/市」
            if prefix in title and len(prefix) >= 2:
                prefix_matches.append(d)
    if prefix_matches:
        prefix_matches.sort(key=len, reverse=True)
        return prefix_matches[0]
    # 3. Fallback:排除城市字首後 regex
    t = title
    for strip in ["臺北市", "台北市", "新北市", "臺中市", "台中市", "臺南市", "台南市", "臺東縣", "台東縣", "高雄市", "桃園市", "基隆市", "新竹市", "新竹縣", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義市", "嘉義縣", "屏東縣", "宜蘭縣", "花蓮縣", "澎湖縣", "金門縣", "連江縣"]:
        t = t.replace(strip, "")
    m = re.search(r"([\u4e00-\u9fff]{2,3}[區鄉鎮])", t)
    if m and m.group(1) in candidates:
        return m.group(1)
    return None


def extract_organizer(title: str) -> str | None:
    """從標題抽中心/單位名。"""
    # 優先抓 【...】
    m = BRACKET_CENTER_RE.search(title)
    if m:
        return m.group(1).strip()
    m = CENTER_RE.search(title)
    if m:
        return m.group(1)
    return None


def guess_category(title: str) -> str:
    """粗略分類 — 只匹配強訊號,其他歸 learning。"""
    t = title
    if re.search(r"運動|健走|太極|瑜珈|瑜伽|體操|舞蹈|拳|散步", t):
        return "sports"
    if re.search(r"健康|檢查|失智|保健|血壓|營養|醫|復健|長照", t):
        return "health"
    if re.search(r"旅遊|參訪|踏青|半日遊|一日遊|行旅", t):
        return "travel"
    if re.search(r"書法|繪畫|合唱|卡拉|歌唱|樂器|戲劇|藝術|文化|展覽|導覽|讀書", t):
        return "culture"
    if re.search(r"志工|志願|服務|陪伴|送餐", t):
        return "volunteer"
    if re.search(r"聯誼|聚會|交流|同樂|共餐", t):
        return "social"
    return "learning"


def scrape_city(city_code: str) -> list[ScrapedItem]:
    city_zh = CITY_MAP[city_code]
    url = f"{BASE}/HomeSon/{city_code}/{city_code}Index"
    html = fetch(url)

    items: list[ScrapedItem] = []
    seen_links = set()

    # SeniorCenter
    for m in SENIOR_LINK_RE.finditer(html):
        href, _code, _enid, title = m.group(1, 2, 3, 4)
        title = clean_text(title)
        link = BASE + href
        if link in seen_links:
            continue
        seen_links.add(link)
        items.append(
            ScrapedItem(
                title=title,
                source_url=link,
                source_name="教育部樂齡學習網",
                organizer_name=extract_organizer(title),
                city=city_zh,
                district=extract_district(title, city_zh),
                category=guess_category(title),
                summary=None,
                published=None,
                raw_section="SeniorCenter",
            )
        )

    # Education (縣市政府/大學/教育部 對該縣市 公告) — 以部分條目篩選過濾非活動
    for m in EDU_LINK_RE.finditer(html):
        href, _code, _enid, title = m.group(1, 2, 3, 4)
        title = clean_text(title)
        if not re.search(r"活動|課程|招生|報名|開放|舉辦|辦理|參加", title):
            continue
        link = BASE + href
        if link in seen_links:
            continue
        seen_links.add(link)
        items.append(
            ScrapedItem(
                title=title,
                source_url=link,
                source_name="教育部樂齡學習網",
                organizer_name=extract_organizer(title),
                city=city_zh,
                district=extract_district(title, city_zh),
                category=guess_category(title),
                summary=None,
                published=None,
                raw_section="Education",
            )
        )

    return items


def to_activity_row(item: ScrapedItem) -> dict[str, Any]:
    """把 ScrapedItem 轉成 Supabase activities row 的 insert payload。"""
    # 從 title 裡猜月份 e.g. "4月課程表"
    recurring_rule = None
    event_type = "recurring"
    m = re.search(r"(\d{1,2})\s*月", item.title)
    if m:
        recurring_rule = f"{m.group(1)}月課程表(按中心實際排程)"
    else:
        recurring_rule = "以主辦單位公告為準"

    # tags:樂齡中心課程絕大部分免費/極低費
    tags = ["免費", "樂齡中心"]
    cost = 0

    summary = (
        f"{item.organizer_name or item.city + '樂齡中心'}本期課程/活動公告。"
        "請點連結查看詳細日期、課名與聯絡方式。"
    )

    return {
        "title": item.title[:140],
        "summary": summary,
        "description": None,
        "organizer_name": item.organizer_name or "樂齡學習中心",
        "event_type": event_type,
        "recurring_rule": recurring_rule,
        "location_name": item.organizer_name,
        "city": item.city,
        "district": item.district,
        "category": item.category,
        "tags": tags,
        "target_audience": "55+",
        "cost": cost,
        # 樂齡中心公告沒附電話,導到原始公告讓用戶查看聯絡方式
        "signup_method": "online",
        "signup_url": item.source_url,
        "source_url": item.source_url,
        "source_name": item.source_name,
        "status": "active",
    }


# ---- Supabase upsert ----

def upsert_to_supabase(rows: list[dict[str, Any]], supa_url: str, supa_key: str) -> int:
    """以 source_url 為去重鍵,不覆蓋既有。新筆插入,回傳插入筆數。"""
    if not rows:
        return 0
    # 先撈既有 source_url 避免重複
    check_url = f"{supa_url}/rest/v1/activities?select=source_url&source_url=not.is.null"
    req = urllib.request.Request(check_url, headers={
        "apikey": supa_key,
        "Authorization": f"Bearer {supa_key}",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        existing = {x["source_url"] for x in json.loads(r.read()) if x.get("source_url")}

    new_rows = [r for r in rows if r.get("source_url") and r["source_url"] not in existing]
    if not new_rows:
        return 0

    # Supabase REST bulk insert
    insert_url = f"{supa_url}/rest/v1/activities"
    data = json.dumps(new_rows).encode("utf-8")
    req = urllib.request.Request(
        insert_url,
        data=data,
        method="POST",
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


# ---- main ----

def main() -> int:
    import os
    ap = argparse.ArgumentParser()
    ap.add_argument("--cities", nargs="*", default=list(CITY_MAP.keys()),
                    help="要抓的 city code 清單,預設全部 22")
    ap.add_argument("--out", type=str, help="輸出 JSON 檔路徑(不提供則不輸出檔案)")
    ap.add_argument("--upsert", action="store_true", help="直接 upsert 進 Supabase")
    ap.add_argument("--limit-per-city", type=int, default=50)
    ap.add_argument("--sleep", type=float, default=1.0, help="每城市之間停等秒數")
    args = ap.parse_args()

    all_items: list[ScrapedItem] = []
    for i, city in enumerate(args.cities):
        if city not in CITY_MAP:
            print(f"[skip] unknown city code: {city}", file=sys.stderr)
            continue
        try:
            items = scrape_city(city)
        except Exception as e:
            print(f"[error] {city}: {e}", file=sys.stderr)
            continue
        items = items[: args.limit_per_city]
        all_items.extend(items)
        print(f"[{i+1:>2}/{len(args.cities)}] {CITY_MAP[city]:6} → {len(items)} 筆")
        time.sleep(args.sleep)

    print(f"\n=== 總共爬到 {len(all_items)} 筆 ===")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump([asdict(x) for x in all_items], f, ensure_ascii=False, indent=2)
        print(f"已輸出 JSON → {args.out}")

    if args.upsert:
        supa_url = os.environ.get("SUPABASE_URL")
        supa_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not supa_url or not supa_key:
            print("[error] 未提供 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY", file=sys.stderr)
            return 2
        rows = [to_activity_row(x) for x in all_items]
        inserted = upsert_to_supabase(rows, supa_url, supa_key)
        print(f"Supabase 新插入 {inserted} 筆 (已去重 source_url)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
