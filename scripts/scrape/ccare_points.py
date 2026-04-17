#!/usr/bin/env python3
"""
衛福部社會家庭署 · 社區照顧關懷據點爬蟲
https://ccare.sfaa.gov.tw/home/community-point

全台 5,831 個社區關懷據點,每個有據點名稱、地址、電話。入 DB 後作為
「可以去走走的鄰近據點」— event_type=recurring、長期開放、社交類。

互動結構:
  1. GET /home/community-point → 拿 cookies + _csrf token
  2. POST /home/community-point with form { page=N, _csrf=..., ... } 翻頁
  3. 解析 HTML 每一 <a class="row"> 內的 3 個 div

執行:
  SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... \\
    python3 scripts/scrape/ccare_points.py --upsert

  # 或先只輸出到 JSON 看結果
  python3 scripts/scrape/ccare_points.py --out /tmp/ccare.json

旗標:
  --limit-pages N  只抓前 N 頁(預設全部 389)
  --sleep S        每 request 間等幾秒(避免被 rate limit,預設 0.3)
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
from dataclasses import dataclass, asdict
from http.cookiejar import CookieJar
from typing import Any

BASE = "https://ccare.sfaa.gov.tw"
LIST_URL = f"{BASE}/home/community-point"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 LohasCardBot/0.1"

# 匹配一筆據點 row,三欄:據點名稱 / 據點地址 / 據點電話(電話可無)
ROW_RE = re.compile(
    r'<a class="row"[^>]+href="(?P<url>/home/community-point/(?P<pid>[^"]+))"[^>]*>\s*'
    r'<div rs-title="據點名稱"[^>]*>(?P<name>[^<]+?)</div>\s*'
    r'<div rs-title="據點地址"[^>]*>(?P<address>[^<]*?)</div>\s*'
    r'(?:<div rs-title="據點電話"[^>]*>(?P<phone>[^<]*?)</div>)?',
    re.S,
)
CSRF_RE = re.compile(r'<input[^>]+name="_csrf"[^>]+value="([^"]+)"')
TOTAL_RE = re.compile(r"共\s*([\d,]+)\s*筆")

# 台灣縣市白名單(title 開頭或 address 開頭通常會命中)
CITIES = [
    "臺北市", "台北市", "新北市", "基隆市", "桃園市", "新竹市", "新竹縣",
    "宜蘭縣", "苗栗縣", "臺中市", "台中市", "彰化縣", "南投縣", "雲林縣",
    "嘉義市", "嘉義縣", "臺南市", "台南市", "高雄市", "屏東縣", "花蓮縣",
    "臺東縣", "台東縣", "澎湖縣", "金門縣", "連江縣",
]

# 統一「臺」→「台」(跟 senioredu 爬蟲一致)
CITY_NORMALIZE = {
    "臺北市": "台北市", "臺中市": "台中市", "臺南市": "台南市", "臺東縣": "台東縣",
}


@dataclass
class Point:
    pid: str           # 據點 ID e.g. NP3800059
    name: str
    address: str | None
    phone: str | None
    city: str | None
    district: str | None


def clean_text(s: str) -> str:
    s = html_lib.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def extract_city_district(address: str | None) -> tuple[str | None, str | None]:
    """從 address 開頭抽縣市 + 鄉鎮市區。"""
    if not address:
        return None, None
    addr = address.strip()
    # 尋找縣市
    for c in CITIES:
        if addr.startswith(c):
            rest = addr[len(c):]
            # 鄉鎮市區
            m = re.match(r"([\u4e00-\u9fff]{2,4}[區鄉鎮市])", rest)
            district = m.group(1) if m else None
            return CITY_NORMALIZE.get(c, c), district
    return None, None


class CcareSession:
    """管理 cookie + CSRF 的 session。"""
    def __init__(self) -> None:
        self.cj = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self.opener.addheaders = [("User-Agent", UA)]
        self.csrf: str | None = None
        self.total_size: int = 0  # 實測:field 名叫 totalSize,其實是總筆數(不是 per-page)

    def bootstrap(self) -> None:
        """GET 首頁拿 cookie + csrf token + total 筆數。"""
        with self.opener.open(LIST_URL, timeout=30) as r:
            html = r.read().decode("utf-8", errors="replace")
        m = CSRF_RE.search(html)
        if not m:
            raise RuntimeError("無法從首頁抓到 _csrf token")
        self.csrf = m.group(1)
        tm = TOTAL_RE.search(html)
        if tm:
            self.total_size = int(tm.group(1).replace(",", ""))

    def fetch_page(self, page: int) -> str:
        """POST 翻頁。server 會用 rawConditions[totalSize](=總筆數)+ page 算 offset。
        CSRF token 每次 response 都會更新,下次 POST 要用最新的。"""
        assert self.csrf is not None, "先呼叫 bootstrap()"
        data = urllib.parse.urlencode({
            "_csrf": self.csrf,
            "rawConditions[departmentTypes]": "",
            "conditions[institutionCountyId]": "",
            "conditions[institutionTownId]": "",
            "conditions[institutionVillageId]": "",
            "conditions[like-institutionName]": "",
            "rawConditions[totalSize]": str(self.total_size or 5831),
            "page": str(page),
        }).encode()
        req = urllib.request.Request(
            LIST_URL, data=data, method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": LIST_URL,
                "User-Agent": UA,
            },
        )
        with self.opener.open(req, timeout=30) as r:
            html = r.read().decode("utf-8", errors="replace")
        # 從 response 抓新的 csrf 給下次 POST 用(舊的會被伺服器 invalidate)
        m = CSRF_RE.search(html)
        if m:
            self.csrf = m.group(1)
        return html


def parse_page(html: str) -> list[Point]:
    pts: list[Point] = []
    for m in ROW_RE.finditer(html):
        pid = m.group("pid").strip()
        name = clean_text(m.group("name") or "")
        address = clean_text(m.group("address") or "") or None
        phone = clean_text(m.group("phone") or "") or None
        city, district = extract_city_district(address)
        if not name:
            continue
        pts.append(Point(pid=pid, name=name, address=address, phone=phone, city=city, district=district))
    return pts


def to_activity_row(p: Point) -> dict[str, Any]:
    return {
        "title": p.name,
        "summary": f"{p.address or ''} · {p.phone or ''}".strip(" ·") or None,
        "description": "社區照顧關懷據點提供共餐、健康促進、電話問安、餐食服務、關懷訪視等服務。可電話洽詢實際活動時間。",
        "organizer_name": p.name,
        "event_type": "recurring",
        "recurring_rule": "長期據點 · 詳情電洽",
        "location_name": p.name,
        "address": p.address,
        "city": p.city,
        "district": p.district,
        "category": "social",
        "tags": ["樂齡據點", "社區關懷", "免費"],
        "target_audience": "55+",
        "cost": 0,
        "signup_method": "phone" if p.phone else "walk_in",
        "signup_phone": p.phone,
        "source_url": f"{BASE}/home/community-point/{p.pid}",
        "source_name": "衛福部社區照顧關懷據點",
        "status": "active",
    }


def upsert_to_supabase(rows: list[dict[str, Any]], supa_url: str, supa_key: str) -> int:
    """以 source_url 為去重鍵。只 insert 尚未存在的。批次 500 筆一次。"""
    if not rows:
        return 0
    # 先撈既有
    existing: set[str] = set()
    # 用 in 過濾太長,改用全撈
    check = f"{supa_url}/rest/v1/activities?select=source_url&source_name=eq.{urllib.parse.quote('衛福部社區照顧關懷據點')}"
    req = urllib.request.Request(check, headers={
        "apikey": supa_key,
        "Authorization": f"Bearer {supa_key}",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
            existing = {x["source_url"] for x in data if x.get("source_url")}
    except Exception as e:
        print(f"[warn] 撈既有資料失敗 (當作空): {e}", file=sys.stderr)

    new_rows = [r for r in rows if r.get("source_url") and r["source_url"] not in existing]
    if not new_rows:
        return 0

    # 分批 insert,避免單次 payload 過大
    CHUNK = 500
    inserted = 0
    for i in range(0, len(new_rows), CHUNK):
        batch = new_rows[i:i + CHUNK]
        req = urllib.request.Request(
            f"{supa_url}/rest/v1/activities",
            data=json.dumps(batch).encode(),
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
            inserted += len(out)
        print(f"  已 insert {inserted}/{len(new_rows)}", flush=True)
    return inserted


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-pages", type=int, default=None, help="只抓前 N 頁(debug 用)")
    ap.add_argument("--out", type=str, help="輸出 JSON 檔路徑(不提供則不輸出檔案)")
    ap.add_argument("--upsert", action="store_true", help="直接 upsert 進 Supabase")
    ap.add_argument("--sleep", type=float, default=0.3, help="每 request 間停等秒數")
    args = ap.parse_args()

    sess = CcareSession()
    print("=== bootstrap (GET /home/community-point) ===", flush=True)
    sess.bootstrap()
    print(f"  csrf token: {sess.csrf[:20]}...", flush=True)

    # 先 fetch page 1 拿總筆數
    html1 = sess.fetch_page(1)
    total_m = TOTAL_RE.search(html1)
    total = int(total_m.group(1).replace(",", "")) if total_m else 0
    total_pages = (total + 14) // 15 if total else 389
    print(f"  總筆數:{total} / 預計 {total_pages} 頁", flush=True)
    if args.limit_pages:
        total_pages = min(total_pages, args.limit_pages)
        print(f"  (受 --limit-pages 限制為 {total_pages} 頁)", flush=True)

    all_points: list[Point] = []
    # page 1 已經 fetch 過
    pts1 = parse_page(html1)
    all_points.extend(pts1)
    print(f"  page 1: +{len(pts1)} 筆 (累計 {len(all_points)}),第一筆 pid: {pts1[0].pid if pts1 else '(none)'}", flush=True)

    for pg in range(2, total_pages + 1):
        time.sleep(args.sleep)
        try:
            html = sess.fetch_page(pg)
        except Exception as e:
            print(f"  [err] page {pg}: {e}", file=sys.stderr, flush=True)
            continue
        pts = parse_page(html)
        all_points.extend(pts)
        # 前幾頁一律印出第一筆的 pid,方便 debug 是否真的翻頁
        if pg <= 5 or pg % 20 == 0 or pg == total_pages:
            first_pid = pts[0].pid if pts else '(none)'
            print(f"  page {pg}: +{len(pts)} 筆 (累計 {len(all_points)}),第一筆 pid: {first_pid}", flush=True)

    # 去重(同 pid 只留一筆)
    seen_pid: set[str] = set()
    unique_points = []
    for p in all_points:
        if p.pid in seen_pid:
            continue
        seen_pid.add(p.pid)
        unique_points.append(p)

    print(f"\n=== 抓到共 {len(unique_points)} 個唯一據點 ===", flush=True)

    # 縣市分布
    by_city: dict[str, int] = {}
    for p in unique_points:
        k = p.city or "(null)"
        by_city[k] = by_city.get(k, 0) + 1
    for c, n in sorted(by_city.items(), key=lambda x: -x[1]):
        print(f"  {c}: {n}", flush=True)

    if args.out:
        with open(args.out, "w") as f:
            json.dump([asdict(p) for p in unique_points], f, ensure_ascii=False, indent=2)
        print(f"\n  已寫入 {args.out}", flush=True)

    if args.upsert:
        supa_url = os.environ.get("SUPABASE_URL")
        supa_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not (supa_url and supa_key):
            print("[error] 缺 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY", file=sys.stderr)
            return 2
        rows = [to_activity_row(p) for p in unique_points]
        print(f"\n=== upsert 到 Supabase ({len(rows)} 筆待檢查) ===", flush=True)
        inserted = upsert_to_supabase(rows, supa_url, supa_key)
        print(f"  共 insert 新增 {inserted} 筆", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
