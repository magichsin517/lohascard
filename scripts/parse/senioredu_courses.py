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
import html as html_lib
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
from datetime import date as date_cls

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
- target_audience: 課程對象年齡。只能填以下其中一種字串,不要自己編:「55+」「60+」「65+」「不限」;若 PDF/圖上沒特別寫,填 null(不要預設 55+)
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


# ===== HTML table 解析(零 token 成本的 fallback) =====
# 處理教育部樂齡網那種「沒上傳附件、課表直接貼成 HTML <table>」的公告。
# 表頭例:項次 | 活動名稱 | 日期 | 上課時間 | 地點 | 講師簡介

_TABLE_RE = re.compile(r"<table\b[^>]*>(.*?)</table>", re.DOTALL | re.IGNORECASE)
_TR_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
_TDH_RE = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


def _clean_cell(raw: str) -> str:
    text = _TAG_RE.sub(" ", raw)
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_tables(html: str) -> list[list[list[str]]]:
    """把 HTML 裡所有 <table> 抽成 [table][row][cell] 三層結構。"""
    out: list[list[list[str]]] = []
    for m in _TABLE_RE.finditer(html):
        rows: list[list[str]] = []
        for tr in _TR_RE.finditer(m.group(1)):
            cells = [_clean_cell(td.group(1)) for td in _TDH_RE.finditer(tr.group(1))]
            if cells:
                rows.append(cells)
        if rows:
            out.append(rows)
    return out


def _find_course_table(tables: list[list[list[str]]]) -> list[list[str]] | None:
    """挑出含『項次/活動名稱/日期/上課時間』header 的課表。"""
    for tbl in tables:
        for row in tbl[:3]:
            joined = "".join(row)
            if "項次" in joined and "活動名稱" in joined and "日期" in joined and "上課時間" in joined:
                return tbl
    return None


# 日期欄可能的格式:
#   2026/04/7.14.21.28       → 月內多次上課
#   4/15                     → 單次
#   每週三                    → 既有 recurring 寫法
_DATE_MONTH_DAYS_RE = re.compile(r"(\d{4})[/.\-](\d{1,2})[/.\-]([\d.\s、,，]+)")
_DATE_MD_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})\b")
_TIME_RANGE_RE = re.compile(r"(\d{1,2}:\d{2})\s*[~\-－–—～]\s*(\d{1,2}:\d{2})")

_WEEKDAY_CH = "日一二三四五六"  # Monday=1 in isoweekday, 但 Python datetime.weekday():Mon=0


def _infer_weekday_from_dates(date_str: str) -> str | None:
    """從 '2026/04/7.14.21.28' 這種字串推「每週幾」(若全部都是同一個星期幾)。"""
    m = _DATE_MONTH_DAYS_RE.match(date_str.strip())
    if not m:
        return None
    year, month, day_part = int(m.group(1)), int(m.group(2)), m.group(3)
    days = re.findall(r"\d{1,2}", day_part)
    if not days:
        return None
    weekdays = set()
    for d in days:
        try:
            dow = date_cls(year, month, int(d)).isoweekday()  # Mon=1..Sun=7
            weekdays.add(dow)
        except ValueError:
            continue
    if len(weekdays) == 1:
        # isoweekday 1..7 → 日一二三四五六 index (日=7→'日', 一=1→'一' ...)
        dow = weekdays.pop()
        return _WEEKDAY_CH[dow % 7]
    return None


def _parse_time_range(time_str: str) -> tuple[str | None, str | None]:
    m = _TIME_RANGE_RE.search(time_str.replace("：", ":"))
    if not m:
        return None, None
    return m.group(1), m.group(2)


# 以關鍵字推 category。比 Gemini 粗,但足夠作為 fallback。
_CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("sports",   ("太極", "拳", "瑜珈", "瑜伽", "舞", "體操", "健走", "健身", "體適能", "有氧", "桌球", "槌球", "羽球", "氣功", "慢跑", "散步", "登山", "拉丁", "運動", "彈力")),
    ("health",   ("健康", "養生", "保健", "長照", "血壓", "失智", "中醫", "穴", "按摩", "復健", "營養", "飲食", "照護", "口腔", "預防")),
    ("culture",  ("音樂", "唱", "合唱", "歌", "京劇", "讀書", "展", "藝術", "文學", "詩", "國樂", "鋼琴", "烏克麗麗", "戲劇", "電影")),
    ("travel",   ("旅遊", "參訪", "踏青", "郊遊", "走讀", "出遊")),
    ("social",   ("聯誼", "共餐", "聚會", "交誼", "社交")),
    ("volunteer", ("志工", "志願")),
    ("learning", ("書法", "電腦", "手機", "平板", "英語", "英文", "日語", "日文", "韓語", "手工", "烹飪", "料理", "花藝", "插畫", "繪畫", "繪本", "畫", "攝影", "工藝", "捲紙", "煮藝", "紓壓", "色鉛筆", "學習", "課程", "研習")),
]


def _infer_category(title: str) -> str:
    for cat, keywords in _CATEGORY_KEYWORDS:
        if any(k in title for k in keywords):
            return cat
    return "learning"  # default


def _extract_contact_line(html: str) -> tuple[str | None, str | None]:
    """從頁面內文抓『連絡電話: XXX』和可能的地址。"""
    text = _TAG_RE.sub(" ", html)
    text = html_lib.unescape(text)
    text = re.sub(r"\s+", " ", text)

    phone = None
    m = re.search(r"連絡電話[::]?\s*([0-9\-()#\s]{6,25})", text)
    if m:
        phone = m.group(1).strip()

    return phone, None


def parse_html_course_table(html: str) -> list[dict]:
    """若 detail page 內文有 HTML course table,回傳跟 Gemini 相同格式的 list[dict]。
    沒抓到回 [] → 外層會走原本「無課表附件」tagging。"""
    tables = _extract_tables(html)
    tbl = _find_course_table(tables)
    if not tbl:
        return []

    # 找到 header 列的位置
    header_idx = 0
    for i, row in enumerate(tbl[:5]):
        if "項次" in "".join(row):
            header_idx = i
            break

    phone, _ = _extract_contact_line(html)

    courses: list[dict] = []
    current: dict | None = None

    for row in tbl[header_idx + 1:]:
        # 新的主資料列:>=6 cells 且第一格是數字(項次)
        if len(row) >= 6 and row[0].strip().isdigit() and row[1].strip():
            if current:
                courses.append(current)
            title = row[1].strip().rstrip("、，,").strip()
            date_str = row[2].strip()
            time_str = row[3].strip()
            loc = row[4].strip()
            teacher = row[5].strip() or None

            start_time, end_time = _parse_time_range(time_str)

            # 推星期:先試 2026/04/7.14 那種,再試文字「每週三/週三/星期三」,最後 fallback 到原文
            weekday_inferred = _infer_weekday_from_dates(date_str)
            if not weekday_inferred:
                m = re.search(r"[週星期]\s*([一二三四五六日])", date_str)
                if m:
                    weekday_inferred = m.group(1)
            weekday = weekday_inferred or date_str or None

            current = {
                "title": title,
                "weekday": weekday,
                "start_time": start_time,
                "end_time": end_time,
                "teacher": teacher,
                "location": loc or None,
                "cost_note": None,
                "category": _infer_category(title),
                "target_audience": None,
                "remarks": f"日期:{date_str}" if date_str else None,
                "_location_extras": [],
            }
        elif current and len(row) == 1 and row[0].strip():
            cell = row[0].strip()
            # 1-cell 接續列 → 地點/地址補充;但過濾掉尾段聯絡資訊
            if not re.search(r"連絡電話|聯絡電話|連絡人|聯絡人|理事長|主任|校長", cell):
                current["_location_extras"].append(cell)

    if current:
        courses.append(current)

    # 把 location_extras 合併進 location,並把第一筆的 remarks 補上中心電話
    for i, c in enumerate(courses):
        extras = c.pop("_location_extras", [])
        if extras:
            c["location"] = " / ".join(filter(None, [c["location"]] + extras))
        if i == 0 and phone:
            prefix = f"中心電話:{phone}"
            c["remarks"] = prefix + (" | " + c["remarks"] if c.get("remarks") else "")

    return courses


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

    def list_parents(
        self,
        limit: int | None = None,
        ids: list[int] | None = None,
        retry_tag: str | None = None,
    ) -> list[Activity]:
        """列出待處理的 parent 公告。
        retry_tag='無課表附件' 時,只撈已經被標「無課表附件」的(用於 HTML-table fallback 補救)。"""
        q = "?source_name=eq." + urllib.parse.quote("教育部樂齡學習網")
        q += "&select=id,title,source_url,organizer_name,city,district,tags"
        if retry_tag:
            q += "&tags=cs.{" + urllib.parse.quote(f'"{retry_tag}"') + "}"
        else:
            # 排除已處理過的 tag
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

    # target_audience:Gemini 抽出來的,只接受白名單值
    ta_raw = (course.get("target_audience") or "").strip()
    ta = ta_raw if ta_raw in ("55+", "60+", "65+", "不限") else None

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
        "target_audience": ta,
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
        # 沒有 PDF/圖片附件 → 嘗試直接解析頁面內的 HTML <table> 課表
        courses = parse_html_course_table(html)
        if courses:
            rows = [r for c in courses for r in [course_to_row(c, parent)] if r]
            if rows:
                if dry_run:
                    print(f"  [dry-html] 會插入 {len(rows)} 筆(HTML table),刪 parent {parent.id}")
                    return "ok_html", len(rows)
                supa.insert_many(rows)
                supa.delete_id(parent.id)
                return "ok_html", len(rows)
        # 真的沒東西能解析,標記 tag
        new_tags = list(parent.tags)
        if "無課表附件" not in new_tags:
            new_tags.append("無課表附件")
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
    ap.add_argument(
        "--retry-no-attachment",
        action="store_true",
        help="只重跑已被標成『無課表附件』的 parent(HTML table fallback 新功能補救用)。"
             "重跑時會先把它們的『無課表附件』tag 拿掉,再嘗試解析。",
    )
    args = ap.parse_args()

    supa_url = os.environ.get("SUPABASE_URL")
    supa_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    # retry-no-attachment 模式不走 Gemini,不需要 API key
    api_key = os.environ.get("GEMINI_API_KEY") or ""
    if not (supa_url and supa_key):
        print("[error] 缺 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY", file=sys.stderr)
        return 2
    if not args.retry_no_attachment and not api_key:
        print("[error] 缺 GEMINI_API_KEY(一般模式要用 Gemini 解析 PDF)", file=sys.stderr)
        return 2

    supa = Supa(supa_url, supa_key)

    limit = None if args.all else args.limit
    ids = None
    if args.ids:
        ids = [int(x) for x in args.ids.split(",") if x.strip()]
    retry_tag = "無課表附件" if args.retry_no_attachment else None
    parents = supa.list_parents(limit=limit, ids=ids, retry_tag=retry_tag)

    # retry 模式:把『無課表附件』tag 先拿掉,才能讓 process_one 正常處理
    if args.retry_no_attachment and not args.dry_run:
        for p in parents:
            cleaned = [t for t in p.tags if t != "無課表附件"]
            p.tags = cleaned
            supa.patch_id(p.id, {"tags": cleaned})
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
