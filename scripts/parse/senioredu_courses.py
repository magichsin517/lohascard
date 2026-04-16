#!/usr/bin/env python3
"""
樂齡中心月課表 → 單堂課 解析 pipeline
使用 Google Gemini 2.5 Flash 多模態 API。

對每一筆 `source_name = '教育部樂齡學習網'` 的 activity:
  1. 下載 detail page,抓出附件 URL (PDF / PNG / JPG / DOCX)
  2. DOCX → 用 libreoffice 轉 PDF
  3. 送去 Gemini,要求輸出單堂課的 JSON 列表
  4. 成功:刪掉月課表 parent,把每堂課 insert 成新 activity
  5. 失敗:保留 parent,加 tag [無課表附件] 或 [解析失敗]

執行:
  # 先處理 5 筆(測試)
  SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... GEMINI_API_KEY=... \
    python3 scripts/parse/senioredu_courses.py --limit 5

  # 全部處理
  python3 scripts/parse/senioredu_courses.py --all
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

# ===== 設定 =====
BASE = "https://moe.senioredu.moe.gov.tw"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 LohasCardBot/0.1"
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

PROMPT = """你正在看一張台灣「樂齡學習中心」的月份課程表(中文)。

請把其中每一門課/活動解析出來,用 JSON 陣列回覆,每一堂課一個 object,欄位:
- title: 課程/活動名稱(必要)
- weekday: 星期幾,文字格式例如「一」「二」「三」「四」「五」「六」「日」或「每週一」;若圖上寫明特定日期(例如 4/15),也放在這,若無則 null
- start_time: 開始時間(格式 HH:MM,例如 09:30),若無則 null
- end_time: 結束時間(格式 HH:MM),若無則 null
- teacher: 老師姓名,若無則 null
- location: 上課地點(若課表上寫明哪間教室或分館),若無則 null
- cost_note: 費用相關說明(例如「免費」、「材料費 100 元」、「每堂 80 元」),若無則 null
- category: 粗分類,必填,只能是以下之一:sports(運動)、learning(學習/書法/電腦/語言/手工)、health(健康/醫療/保健/長照)、culture(藝術/音樂/歌唱/展覽/讀書)、travel(旅遊/參訪)、social(社交/聯誼/共餐)、volunteer(志工/志願服務)
- remarks: 其他備註(例如「滿額停招」、「需自備」、「新班」、「招生 20 人」等),若無則 null

規則:
- 只回 JSON 陣列本體,不要 markdown code fence,不要任何解釋文字
- 若有中心聯絡電話,放在第一筆的 remarks 開頭,格式「中心電話:XXXXXXX」
- 若有中心地址,放在第一筆的 remarks 後半,格式「中心地址:XXX」
- 保留繁體中文台灣慣用寫法
- 把課名清理乾淨(去掉序號、多餘空白)
- 若無法判讀任何課程(例如只是海報圖),回空陣列 []
"""

# ===== 基本 I/O =====

def fetch(url: str, *, timeout: int = 40, retries: int = 3) -> bytes:
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"fetch failed: {url}: {last}")


def fetch_text(url: str, **kw) -> str:
    raw = fetch(url, **kw)
    return raw.decode("utf-8", errors="replace")


# ===== Supabase REST =====

@dataclass
class Activity:
    id: int
    title: str
    source_url: str
    organizer_name: str | None
    city: str | None
    district: str | None
    tags: list[str]


class Supa:
    def __init__(self, url: str, key: str):
        self.url = url.rstrip("/")
        self.key = key

    def _req(self, method: str, path: str, body: object | None = None, prefer: str | None = None) -> bytes:
        headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()

    def list_parents(self, limit: int | None = None, ids: list[int] | None = None) -> list[Activity]:
        # 用 source_name 過濾
        q = "?source_name=eq." + urllib.parse.quote("教育部樂齡學習網")
        q += "&select=id,title,source_url,organizer_name,city,district,tags"
        # 排除已處理過的 tag — 不論是成功解析、無附件、還是失敗,都不要再重試
        for skip_tag in ("課表已解析", "無課表附件", "解析失敗", "解析0堂"):
            q += "&tags=not.cs.{" + urllib.parse.quote(f'"{skip_tag}"') + "}"
        q += "&order=id.asc"
        if ids:
            q += "&id=in.(" + ",".join(str(i) for i in ids) + ")"
        if limit:
            q += f"&limit={limit}"
        data = json.loads(self._req("GET", "/rest/v1/activities" + q))
        return [Activity(**d) for d in data]

    def insert_many(self, rows: list[dict]) -> list[dict]:
        if not rows:
            return []
        out = self._req("POST", "/rest/v1/activities", rows, prefer="return=representation")
        return json.loads(out)

    def delete_id(self, aid: int) -> None:
        self._req("DELETE", f"/rest/v1/activities?id=eq.{aid}", prefer="return=minimal")

    def patch_id(self, aid: int, body: dict) -> None:
        self._req("PATCH", f"/rest/v1/activities?id=eq.{aid}", body, prefer="return=minimal")


# ===== 附件抓取 =====

# detail page HTML 裡的附件樣式
ATTACH_RE = re.compile(r'(?:href|src)="(/UploadFiles/[^"]+\.(?:pdf|png|jpg|jpeg|gif|docx|doc))"', re.I)
IMAGE_EXTS = {"png", "jpg", "jpeg", "gif"}

def find_attachment(detail_html: str) -> tuple[str, str] | None:
    """回傳 (attachment_url, file_ext_lower) 或 None。"""
    m = ATTACH_RE.search(detail_html)
    if not m:
        return None
    rel = m.group(1)
    url = BASE + rel
    ext = rel.rsplit(".", 1)[-1].lower()
    return url, ext


def docx_to_pdf(docx_bytes: bytes) -> bytes:
    """Libreoffice headless 轉檔。回傳 PDF bytes。"""
    with tempfile.TemporaryDirectory() as tmp:
        in_path = os.path.join(tmp, "in.docx")
        with open(in_path, "wb") as f:
            f.write(docx_bytes)
        subprocess.run(
            ["libreoffice", "--headless", "--convert-to", "pdf", "--outdir", tmp, in_path],
            check=True, capture_output=True, timeout=120,
        )
        pdf_path = os.path.join(tmp, "in.pdf")
        with open(pdf_path, "rb") as f:
            return f.read()


# ===== Gemini 呼叫 =====

def gemini_parse(data: bytes, mime: str, api_key: str) -> list[dict]:
    """把二進位資料送 Gemini,要求解析課表,回傳 list[dict]。"""
    payload = {
        "contents": [{
            "parts": [
                {"text": PROMPT},
                {"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode("ascii")}},
            ]
        }],
        "generationConfig": {
            "temperature": 0.0,
            "response_mime_type": "application/json",
        },
    }
    req = urllib.request.Request(
        GEMINI_ENDPOINT,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            resp = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Gemini API error: {e.code}: {e.read().decode()[:300]}")

    try:
        text = resp["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise RuntimeError(f"Gemini 回傳格式異常: {json.dumps(resp)[:300]}")

    courses = json.loads(text)
    if not isinstance(courses, list):
        raise RuntimeError(f"Gemini 沒回 array: {type(courses)}")
    return courses


# ===== 課程 → activity row =====

VALID_CATS = {"sports", "learning", "health", "culture", "travel", "social", "volunteer"}

def pricing_tier_from_text(cost_note: str | None) -> tuple[int, str]:
    """從 cost_note 推 cost (NT$ int) + 定價 tag。預設免費。"""
    if not cost_note:
        return 0, "免費"
    t = cost_note
    if re.search(r"免費|免|不收|0\s*元", t):
        return 0, "免費"
    # 抓第一組數字
    m = re.search(r"(\d{2,5})\s*元", t)
    if m:
        cost = int(m.group(1))
        if cost == 0:
            return 0, "免費"
        elif cost <= 300:
            return cost, "小額收費"
        else:
            return cost, "收費"
    # 沒具體數字但有提到材料費
    if re.search(r"材料|自費", t):
        return 0, "小額收費"  # 不確定金額,歸小額
    return 0, "免費"


def course_to_row(course: dict, parent: Activity) -> dict | None:
    title = (course.get("title") or "").strip()
    if not title or len(title) > 140:
        return None

    category = course.get("category")
    if category not in VALID_CATS:
        category = "learning"  # fallback

    cost, pricing_tag = pricing_tier_from_text(course.get("cost_note"))

    # 星期/時間
    weekday = (course.get("weekday") or "").strip() or None
    # 清理 weekday
    if weekday:
        weekday = weekday.replace("週", "").replace("星期", "").strip()
        if not weekday:
            weekday = None
    recurring_rule = f"每週{weekday}" if weekday and weekday in "一二三四五六日" else weekday

    start_time = course.get("start_time")
    end_time = course.get("end_time")
    if start_time and not re.match(r"^\d{1,2}:\d{2}$", start_time):
        start_time = None
    if end_time and not re.match(r"^\d{1,2}:\d{2}$", end_time):
        end_time = None

    # 電話/地址 從 remarks 第一項拆出來
    remarks = course.get("remarks") or ""
    phone_m = re.search(r"中心電話[::]?\s*([0-9\-()#\s　]{6,25})", remarks)
    addr_m = re.search(r"中心地址[::]?\s*([\u4e00-\u9fff0-9\-號巷弄樓段路街市區縣市\s]{4,60})", remarks)

    phone = phone_m.group(1).strip() if phone_m else None
    address = addr_m.group(1).strip() if addr_m else None

    teacher = (course.get("teacher") or "").strip() or None
    location = (course.get("location") or "").strip() or None

    tags = [pricing_tag, "樂齡中心", "單堂課"]

    summary_parts = []
    if teacher:
        summary_parts.append(f"老師:{teacher}")
    if recurring_rule and (start_time or end_time):
        summary_parts.append(f"{recurring_rule} {start_time or ''}-{end_time or ''}".strip())
    if remarks and not phone_m and not addr_m:
        summary_parts.append(remarks[:60])
    summary = " | ".join(summary_parts) or None

    return {
        "title": title,
        "summary": summary,
        "description": remarks or None,
        "organizer_name": parent.organizer_name,
        "event_type": "recurring",
        "recurring_rule": recurring_rule,
        "location_name": location or parent.organizer_name,
        "address": address,
        "city": parent.city,
        "district": parent.district,
        "category": category,
        "tags": tags,
        "target_audience": "55+",
        "cost": cost,
        "cost_note": course.get("cost_note"),
        "signup_method": "phone" if phone else "online",
        "signup_phone": phone,
        "signup_url": parent.source_url if not phone else None,
        "start_time": start_time,
        "end_time": end_time,
        "source_url": parent.source_url,
        "source_name": "教育部樂齡學習網(課表解析)",
        "status": "active",
    }


# ===== 主流程 =====

def process_one(parent: Activity, supa: Supa, api_key: str, *, dry_run: bool = False) -> tuple[str, int]:
    """回傳 (狀態, 插入數)。狀態:ok/no_attachment/parse_failed/http_failed/docx_failed"""
    try:
        html = fetch_text(parent.source_url, timeout=30)
    except Exception as e:
        print(f"  [http] {e}")
        return "http_failed", 0

    found = find_attachment(html)
    if not found:
        # 沒有附件,標記 tag
        new_tags = list(parent.tags) + ["無課表附件"]
        if not dry_run:
            supa.patch_id(parent.id, {"tags": new_tags})
        return "no_attachment", 0

    attach_url, ext = found
    try:
        raw = fetch(attach_url, timeout=60)
    except Exception as e:
        print(f"  [attach-http] {attach_url}: {e}")
        return "http_failed", 0

    # 決定 mime
    if ext in IMAGE_EXTS:
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif"}[ext]
        data = raw
    elif ext == "pdf":
        mime, data = "application/pdf", raw
    elif ext in ("docx", "doc"):
        # 先轉 pdf
        try:
            data = docx_to_pdf(raw)
            mime = "application/pdf"
        except Exception as e:
            print(f"  [docx-convert] {e}")
            if not dry_run:
                supa.patch_id(parent.id, {"tags": list(parent.tags) + ["解析失敗"]})
            return "docx_failed", 0
    else:
        if not dry_run:
            supa.patch_id(parent.id, {"tags": list(parent.tags) + ["解析失敗"]})
        return "unsupported_ext", 0

    try:
        courses = gemini_parse(data, mime, api_key)
    except Exception as e:
        print(f"  [gemini] {e}")
        new_tags = list(parent.tags) + ["解析失敗"]
        if not dry_run:
            supa.patch_id(parent.id, {"tags": new_tags})
        return "parse_failed", 0

    rows = []
    for c in courses:
        row = course_to_row(c, parent)
        if row:
            rows.append(row)
    if not rows:
        new_tags = list(parent.tags) + ["解析0堂"]
        if not dry_run:
            supa.patch_id(parent.id, {"tags": new_tags})
        return "parse_empty", 0

    if dry_run:
        print(f"  [dry] 會插入 {len(rows)} 筆,刪 parent {parent.id}")
        return "ok", len(rows)

    supa.insert_many(rows)
    # 刪 parent
    supa.delete_id(parent.id)
    return "ok", len(rows)


def main() -> int:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10, help="一次處理幾筆(預設 10)")
    ap.add_argument("--all", action="store_true", help="全部處理(忽略 --limit)")
    ap.add_argument("--ids", type=str, help="只處理指定 id 清單,逗號分隔")
    ap.add_argument("--dry-run", action="store_true", help="只看,不寫 DB")
    ap.add_argument("--sleep", type=float, default=0.0, help="每筆之間等幾秒(worker=1 時有用)")
    ap.add_argument("--workers", type=int, default=4, help="並行 worker 數(預設 4)")
    args = ap.parse_args()

    supa_url = os.environ.get("SUPABASE_URL")
    supa_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not (supa_url and supa_key and api_key):
        print("[error] 缺 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY / GEMINI_API_KEY", file=sys.stderr)
        return 2

    supa = Supa(supa_url, supa_key)

    limit = None if args.all else args.limit
    ids = None
    if args.ids:
        ids = [int(x) for x in args.ids.split(",") if x.strip()]
    parents = supa.list_parents(limit=limit, ids=ids)
    print(f"=== 將處理 {len(parents)} 筆月課表(workers={args.workers}) ===", flush=True)

    stats: dict[str, int] = {}
    total_inserted = 0

    def _work(p: Activity):
        try:
            status, n = process_one(p, supa, api_key, dry_run=args.dry_run)
            return p, status, n, None
        except Exception as e:
            return p, "exception", 0, str(e)

    if args.workers <= 1:
        for i, p in enumerate(parents, 1):
            print(f"[{i:>3}/{len(parents)}] id={p.id} {p.city}/{p.district or '-'} {p.title[:40]}", flush=True)
            _, status, n, err = _work(p)
            stats[status] = stats.get(status, 0) + 1
            total_inserted += n
            print(f"  → {status} (+{n}){' '+err if err else ''}", flush=True)
            if args.sleep:
                time.sleep(args.sleep)
    else:
        done = 0
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(_work, p): p for p in parents}
            for fut in as_completed(futures):
                done += 1
                p, status, n, err = fut.result()
                stats[status] = stats.get(status, 0) + 1
                total_inserted += n
                print(f"[{done:>3}/{len(parents)}] id={p.id} {p.city}/{p.district or '-'} {p.title[:32]} → {status} (+{n}){' '+err if err else ''}", flush=True)

    print("\n=== 結果統計 ===", flush=True)
    for k, v in sorted(stats.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}", flush=True)
    print(f"  共插入單堂課 {total_inserted} 筆", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
