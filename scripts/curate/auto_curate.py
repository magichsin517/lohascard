#!/usr/bin/env python3
"""
樂活卡卡 自動本週精選 & LINE 推播
每週一 09:00 台北時間由 GitHub Actions 執行

選活動邏輯:
  - 候選池: 雙北 + 未來 30 天 + event_type=single + 有 location_name
  - 選 1 筆 learning (排除重複性高的導覽/VR)
  - 選 6-7 筆 culture (場地多樣, 優先有圖/免費/傳統戲曲)
  - 確保至少 1 筆免費、1 筆傳統戲曲(若有)
  - 總共 8-9 筆
"""

import os
import sys
import requests
from datetime import date, timedelta
from supabase import create_client

# ─── 環境變數 ───────────────────────────────────────────
SUPABASE_URL  = os.environ["SUPABASE_URL"]
SUPABASE_KEY  = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
LINE_SECRET   = os.environ["LINE_BROADCAST_SECRET"]
BROADCAST_URL = "https://lohascard.vercel.app/api/line/broadcast-curated"

TODAY    = date.today()
WIN_END  = TODAY + timedelta(days=30)

# ─── 常數 ───────────────────────────────────────────────
TRADITIONAL_KW = [
    "京劇","掌中戲","布袋戲","歌仔戲","客家戲","豫劇","崑曲",
    "傳統戲","戲曲","南管","北管","皮影","相聲","南北管",
]
SKIP_LEARNING_KW = ["專人定時導覽", "VR虛擬實境", "VR 虛擬實境", "VR"]
PRESTIGIOUS_VENUES = [
    "國家戲劇院","國家音樂廳","國家兩廳院","兩廳院",
    "臺北市中山堂","中山堂","大稻埕戲苑","臺北表演藝術中心",
    "誠品表演廳","城市舞台","國家電影",
]

# ─── 工具函式 ────────────────────────────────────────────
def is_traditional(title: str) -> bool:
    return any(kw in title for kw in TRADITIONAL_KW)

def is_free(tags) -> bool:
    return isinstance(tags, list) and "免費" in tags

def has_image(row: dict) -> bool:
    url = row.get("image_url") or ""
    return bool(url) and not url.endswith(".svg")

def is_prestigious(location: str) -> bool:
    return any(v in (location or "") for v in PRESTIGIOUS_VENUES)

def score_culture(row: dict) -> float:
    s = 0.0
    title    = row.get("title", "")
    location = row.get("location_name", "")
    tags     = row.get("tags")
    if has_image(row):           s += 3.0
    if is_free(tags):            s += 2.5
    if is_traditional(title):    s += 2.0
    if is_prestigious(location): s += 1.0
    try:
        days = (date.fromisoformat(row["start_date"]) - TODAY).days
        s += max(0.0, 1.5 - days * 0.04)
    except Exception:
        pass
    return s

# ─── 撈資料 ─────────────────────────────────────────────
def fetch_candidates(supabase) -> list:
    res = (
        supabase.table("activities")
        .select("id,title,category,start_date,location_name,city,tags,image_url")
        .eq("event_type", "single")
        .gt("start_date", TODAY.isoformat())
        .lte("start_date", WIN_END.isoformat())
        .not_.is_("location_name", "null")
        .or_(
            "city.in.(台北市,新北市),"
            "location_name.ilike.%台北%,"
            "location_name.ilike.%新北%"
        )
        .order("start_date")
        .limit(500)
        .execute()
    )
    return res.data or []

# ─── 選活動 ─────────────────────────────────────────────
def select_picks(candidates: list) -> list:
    learning = [r for r in candidates
                if r["category"] == "learning"
                and not any(kw in r.get("title","") for kw in SKIP_LEARNING_KW)]
    culture  = [r for r in candidates if r["category"] == "culture"]

    picks = []
    used_venues = set()

    def try_add(row: dict) -> bool:
        venue = row.get("location_name", "") or ""
        if venue in used_venues:
            return False
        picks.append(row)
        used_venues.add(venue)
        return True

    # 1 筆 learning
    for row in learning:
        if try_add(row):
            break

    # culture: 按分數排序，場地不重複
    culture_sorted = sorted(culture, key=score_culture, reverse=True)
    for row in culture_sorted:
        if len(picks) >= 9:
            break
        try_add(row)

    # 確保至少 1 筆傳統戲曲
    has_trad = any(is_traditional(r.get("title","")) for r in picks if r["category"] == "culture")
    if not has_trad:
        trad_pool = [r for r in culture_sorted
                     if is_traditional(r.get("title",""))
                     and r.get("location_name","") not in used_venues]
        if trad_pool and len(picks) >= 2:
            for i in range(len(picks)-1, -1, -1):
                if picks[i]["category"] == "culture" and not is_traditional(picks[i].get("title","")):
                    old_venue = picks[i].get("location_name","")
                    picks[i] = trad_pool[0]
                    used_venues.discard(old_venue)
                    used_venues.add(trad_pool[0].get("location_name",""))
                    break

    # 確保至少 1 筆免費
    has_free = any(is_free(r.get("tags")) for r in picks)
    if not has_free and len(picks) < 10:
        free_pool = [r for r in culture_sorted
                     if is_free(r.get("tags"))
                     and r.get("location_name","") not in used_venues]
        if free_pool:
            picks.append(free_pool[0])
            used_venues.add(free_pool[0].get("location_name",""))

    return picks

# ─── 主流程 ─────────────────────────────────────────────
def main():
    print(f"=== 樂活卡卡 自動本週精選 {TODAY} (週一) ===\n")

    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Step 1: 清除上週 curated
    supabase.table("activities").update({"is_curated": False}).eq("is_curated", True).execute()
    print("✓ Step 1: 清除上週 curated")

    # Step 2: 撈候選
    candidates = fetch_candidates(supabase)
    print(f"✓ Step 2: 候選池 {len(candidates)} 筆")
    if not candidates:
        print("❌ 候選池是空的，終止")
        sys.exit(1)

    # Step 3: 選
    picks = select_picks(candidates)
    ids   = [r["id"] for r in picks]
    print(f"✓ Step 3: 選出 {len(picks)} 筆:")
    for r in sorted(picks, key=lambda x: x["start_date"]):
        tags = " ".join(filter(None, [
            "免費" if is_free(r.get("tags")) else "",
            "📷"  if has_image(r) else "",
            "傳統" if is_traditional(r.get("title","")) else "",
        ]))
        print(f"   [{r['start_date']}] {r['title'][:38]:<38} | {(r.get('location_name') or '')[:20]} {tags}")

    # Step 4: 寫入 DB
    supabase.table("activities").update({"is_curated": True}).in_("id", ids).execute()
    print(f"\n✓ Step 4: DB 已標記 {len(ids)} 筆 is_curated=TRUE")

    # Step 5: 推播
    print("\n推播中...")
    resp = requests.post(
        f"{BROADCAST_URL}?mode=broadcast",
        headers={"x-broadcast-secret": LINE_SECRET},
        timeout=30,
    )
    if resp.status_code == 200:
        body = resp.json()
        print(f"✅ Step 5: broadcast 成功")
        print(f"   bubblesSent={body.get('bubblesSent')}")
        print(f"   curatedIds={body.get('curatedIds')}")
        print(f"   altText={body.get('altText','')[:80]}")
    else:
        print(f"❌ Step 5: broadcast 失敗 HTTP {resp.status_code}: {resp.text}")
        sys.exit(1)

    print("\n=== 完成 ===")

if __name__ == "__main__":
    main()
