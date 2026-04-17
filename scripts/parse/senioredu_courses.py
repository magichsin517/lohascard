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
    """挑出課表 — 必有「項次」+「活動名稱」,且至少有「日期」或「時間」欄位之一。

    涵蓋多種 header 變體(字首可能有空白、小括號註釋):
      - 項次 | 活動名稱 | 日期 | 上課時間 | 地點 | 講師                      (6 欄)
      - 項次 | 活動名稱 | 日期(時間) | 地點 | 講師 | 報名費用 | 備註         (7 欄,日期合併時間)
      - 項次 | 活動名稱 | 日期 | 地點 | 講師 | 報名費用 | 備註               (7 欄)
      - 項次 | 活動名稱 | 日期 | 時間 | 地點 | 講師 | 報名費用 | 備註         (8 欄)
      - 項次 | 活動名稱 | 日期(上課時間) | 地點(含地址) | 講師及簡歷 | 報名費 | 備註  (7 欄,欄名帶註釋)
      - 項 次 | 活動名稱 | ...                                                  (項次中間有空白)
    """
    for tbl in tables:
        for row in tbl[:3]:
            # 把所有 cell 合併後再剝空白,可容忍「項 次」這種中間有空白的 header
            joined_nospace = re.sub(r"\s+", "", "".join(row))
            # 序號欄:項次 / 班別 / 編號 / 序 / 課編 / 課號 都算
            has_item_col = any(k in joined_nospace for k in ("項次", "班別", "編號", "課編", "課號")) or \
                joined_nospace.startswith("序")
            # 課名欄:活動名稱 / 課程名稱 / 名稱
            has_name_col = any(k in joined_nospace for k in ("活動名稱", "課程名稱")) or \
                (joined_nospace.count("名稱") >= 1)
            has_date_col = "日期" in joined_nospace or "時間" in joined_nospace
            if has_item_col and has_name_col and has_date_col:
                return tbl
    return None


# 偵測「X月未辦理課程 / 暫停辦理 / 未開課」這種公告本身沒課的 case。
# 這跟「parser 解析不出 table」是兩回事 — 這類公告即使解析了也沒東西可看。
_NO_CLASS_PATTERNS = [
    "未辦理課程", "未辦理", "無辦理課程", "無辦理活動", "無辦理",
    "未開課", "無開課", "暫停辦理", "暫停開課", "本月無",
    "並無課程", "並無開課", "無招生", "本月停課",
]


def detect_no_class_announcement(html: str) -> str | None:
    """若公告內文實質是『本月沒開課』,回傳命中的關鍵字;否則 None。

    用於 process_one 短路:這類 parent 直接標 tag `本月無課` 並刪除,
    因為對使用者沒展示價值(就是一張『本月沒課』的公告)。
    """
    # 先剝 HTML tag,避免命中 CSS/JS/導覽列
    text = _TAG_RE.sub(" ", html)
    text = html_lib.unescape(text)
    text = re.sub(r"\s+", " ", text)
    # 只掃「內文區」— 用「附件下載」或「公告單位」當右界,避免誤中 footer
    end_anchors = ["附件下載", "公告單位", "公告日期"]
    for anchor in end_anchors:
        idx = text.find(anchor)
        if idx > 0:
            text = text[:idx]
            break
    for pat in _NO_CLASS_PATTERNS:
        if pat in text:
            return pat
    return None


def _parse_header_cols(header_row: list[str]) -> dict[str, int]:
    """從 header 列決定每個欄位對應的 column index。

    回傳 dict,key 可能有:title / date / time / location / teacher / cost / remarks
    找不到的欄位不會放進 dict。

    欄名可能帶括號註釋(例如「地點(含地址)」、「講師及簡歷」、「報名費用(如無則免費)」)
    或中間有空白(例如「項 次」、「備 註」)。使用子字串 + 空白容忍匹配。
    """
    cols: dict[str, int] = {}
    for i, cell in enumerate(header_row):
        c = re.sub(r"\s+", "", cell)  # 把所有空白吃掉,方便子字串比對
        if not c:
            continue
        # 活動名稱 / 課程名稱 / 名稱(單獨出現)
        # 注意:不把「班別」當 title — 班別是編號欄,真正課名仍是後面的「活動名稱」。
        if ("活動名稱" in c or "課程名稱" in c or c == "名稱") and "title" not in cols:
            cols["title"] = i
        # 日期 (可能含時間)
        elif "日期" in c and "date" not in cols:
            cols["date"] = i
            if "時間" in c:
                cols["time"] = i  # 合併欄位
        # 純時間欄
        elif "時間" in c and "time" not in cols:
            cols["time"] = i
        # 地點 / 上課地點 / 地點(含地址)
        elif "地點" in c and "location" not in cols:
            cols["location"] = i
        # 講師 / 老師 / 講師及簡歷 / 講師簡介
        elif ("講師" in c or "老師" in c) and "teacher" not in cols:
            cols["teacher"] = i
        # 費用 / 報名費 / 收費
        elif ("費" in c or "收費" in c) and "cost" not in cols:
            cols["cost"] = i
        # 備註
        elif "備註" in c and "remarks" not in cols:
            cols["remarks"] = i
    return cols


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
    沒抓到回 [] → 外層會走原本「無課表附件」tagging。

    支援多種 header 變體(見 _find_course_table doc),動態建立 column index。
    也支援「多場次續列」(2-cell: date + location)把額外場次 append 到 remarks。
    """
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

    header_row = tbl[header_idx]
    cols = _parse_header_cols(header_row)
    # title/date 是最低要求,沒有就放棄
    if "title" not in cols or "date" not in cols:
        return []
    n_cols = len(header_row)

    phone, _ = _extract_contact_line(html)

    courses: list[dict] = []
    current: dict | None = None

    def cell(row: list[str], key: str) -> str:
        idx = cols.get(key)
        if idx is None or idx >= len(row):
            return ""
        return row[idx].strip()

    # 判斷是否為「項次/班別/編號欄」— 這欄有值才算 main row(除非是 rowspan 合併 → 空值也算)
    header_first_cell = re.sub(r"\s+", "", header_row[0]) if header_row else ""
    is_classify_col = any(k in header_first_cell for k in ("班別", "編號", "課編", "課號"))

    def _is_item_no(s: str) -> bool:
        """項次欄可能的值:'1' / '1.' / '01' / '一' / '' (rowspan 首筆)。
        若首欄其實是「班別/編號」型字串分類,則接受任何非空字串。"""
        t = s.strip().rstrip("..、,.")
        if not t:
            return True  # 空的 → rowspan 合併,視為主列(由 title 欄是否有值把關)
        if is_classify_col:
            # 班別欄可能是「古風」「本部」「N20」等 — 任何非空都算
            return len(t) <= 20
        if t.isdigit():
            return True
        if re.match(r"^\d+[、,\.]?$", t):
            return True
        if t in "一二三四五六七八九十":
            return True
        return False

    title_idx = cols.get("title", 1)
    for row in tbl[header_idx + 1:]:
        # 主資料列:欄數跟 header 接近 + title 欄必有內容 + 項次欄符合數字 pattern(含空值)
        is_main = (
            len(row) >= max(4, n_cols - 2)
            and title_idx < len(row)
            and row[title_idx].strip()
            and _is_item_no(row[0])
        )
        if is_main:
            if current:
                courses.append(current)
            title = cell(row, "title").rstrip("、，,").strip()
            date_str = cell(row, "date")
            time_str = cell(row, "time") if "time" in cols else ""
            loc = cell(row, "location")
            teacher = cell(row, "teacher") or None
            cost_note = cell(row, "cost") or None
            remarks_cell = cell(row, "remarks")

            # 若 date 欄合併了時間(例「4/22(三) 9:30~11:30」或「4/13、4/20、4/27 上午 9:00-11:00」),
            # 優先從 date_str 抽時間;若抽不到再用 time 欄。
            start_time, end_time = _parse_time_range(date_str)
            if not start_time and time_str:
                start_time, end_time = _parse_time_range(time_str)

            # 推星期:先試 2026/04/7.14 那種,再試「星期三/週三/(三)」,最後 fallback 到原文
            weekday_inferred = _infer_weekday_from_dates(date_str)
            if not weekday_inferred:
                m = re.search(r"[週星期]\s*([一二三四五六日])", date_str)
                if m:
                    weekday_inferred = m.group(1)
            if not weekday_inferred:
                # (三) 這種括號標注
                m = re.search(r"[(\(]\s*([一二三四五六日])\s*[)\)]", date_str)
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
                "cost_note": cost_note,
                "category": _infer_category(title),
                "target_audience": None,
                "remarks": (f"日期:{date_str}" if date_str else None),
                "_location_extras": [],
                "_extra_sessions": [],
            }
            if remarks_cell and remarks_cell not in ("無", "-", "—"):
                existing = current.get("remarks") or ""
                current["remarks"] = existing + (" | " if existing else "") + remarks_cell
        elif current and len(row) == 2 and row[0].strip() and row[1].strip():
            # 2-cell 續列 → 同一堂課的下一場次:第 1 格=日期時間,第 2 格=地點
            sess_date = row[0].strip()
            sess_loc = row[1].strip()
            current["_extra_sessions"].append(f"{sess_date} @ {sess_loc}")
        elif current and len(row) == 1 and row[0].strip():
            cell_text = row[0].strip()
            # 1-cell 接續列 → 地點/地址補充;但過濾掉尾段聯絡資訊
            if not re.search(r"連絡電話|聯絡電話|連絡人|聯絡人|理事長|主任|校長", cell_text):
                current["_location_extras"].append(cell_text)

    if current:
        courses.append(current)

    # 把 location_extras / extra_sessions 合併,並把第一筆的 remarks 補上中心電話
    for i, c in enumerate(courses):
        extras = c.pop("_location_extras", [])
        if extras:
            c["location"] = " / ".join(filter(None, [c["location"]] + extras))
        sessions = c.pop("_extra_sessions", [])
        if sessions:
            extra = "其他場次: " + "; ".join(sessions)
            c["remarks"] = (c.get("remarks") + " | " if c.get("remarks") else "") + extra
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
ATTACH_RE = re.compile(r'(?:href|src)="(/UploadFiles/[^"]+\.(?:pdf|png|jpg|jpeg|gif|docx|doc|xlsx|xls))"', re.I)
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
    """backward-compat wrapper,內部呼叫通用的 office_to_pdf。"""
    return office_to_pdf(docx_bytes, "docx")


def office_to_pdf(raw: bytes, ext: str) -> bytes:
    """把 Office 系列檔案(docx/doc/xlsx/xls)用 libreoffice headless 轉 PDF。回傳 PDF bytes。"""
    ext = ext.lower().lstrip(".")
    with tempfile.TemporaryDirectory() as tmp:
        in_path = os.path.join(tmp, f"in.{ext}")
        with open(in_path, "wb") as f:
            f.write(raw)
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

# 這幾個 tag 代表「parser 處理後的狀態」— 它們互斥,任一時刻 parent 最多有一個。
# 狀態轉換時要把舊的那個清掉,不然會 double-tag(舊 bug)。
_STATE_TAGS = {"無課表附件", "解析失敗", "解析0堂", "課表已解析"}


def _with_state_tag(existing_tags: list[str] | None, new_state: str | None) -> list[str]:
    """把舊的 state tag 拿掉,套上新的 state tag(若 new_state=None 就只剝舊的)。"""
    kept = [t for t in (existing_tags or []) if t not in _STATE_TAGS]
    return kept + ([new_state] if new_state else [])


def process_one(
    parent: Activity,
    supa: Supa,
    api_key: str,
    *,
    dry_run: bool = False,
    html_only: bool = False,
) -> tuple[str, int]:
    """回傳 (狀態, 插入數)。狀態:ok/no_attachment/parse_failed/http_failed/docx_failed
    html_only=True 時,遇到有附件的 parent 直接 skip(不動 tag),只跑 HTML table path。

    重要:本函式對 parent.tags 的修改是 atomic 的 — 無論 parent 原本帶哪個 state tag
    (無課表附件/解析失敗/解析0堂),處理完之後 state tag 會被正確換成新的結果;
    若中途失敗(例如 HTTP timeout),不會把原本的 state tag 拿掉。"""
    try:
        html = fetch_text(parent.source_url, timeout=30)
    except Exception as e:
        print(f"  [http] {e}")
        return "http_failed", 0

    found = find_attachment(html)
    if html_only and found:
        # 有附件但我們只想跑 HTML 模式 → 保留 parent 給之後 Gemini 路徑處理
        return "skipped_has_attachment", 0
    if not found:
        # 先檢查是不是「本月未辦理」公告 — 這類對 UX 沒價值,直接刪除
        no_class = detect_no_class_announcement(html)
        if no_class:
            if dry_run:
                print(f"  [dry-no-class] 命中『{no_class}』 → 會刪 parent {parent.id}")
                return "no_class", 0
            supa.delete_id(parent.id)
            return "no_class", 0
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
        # 真的沒東西能解析,標記 tag(atomic:clear 舊 state + set 新 state)
        if not dry_run:
            supa.patch_id(parent.id, {"tags": _with_state_tag(parent.tags, "無課表附件")})
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
    elif ext in ("docx", "doc", "xlsx", "xls"):
        # Office 檔案都先經 libreoffice 轉成 PDF 再送 Gemini(xlsx 尤其要,因為 Gemini 不吃 spreadsheet)
        try:
            data = office_to_pdf(raw, ext)
            mime = "application/pdf"
        except Exception as e:
            print(f"  [office-convert] {e}")
            if not dry_run:
                supa.patch_id(parent.id, {"tags": _with_state_tag(parent.tags, "解析失敗")})
            return "office_failed", 0
    else:
        if not dry_run:
            supa.patch_id(parent.id, {"tags": _with_state_tag(parent.tags, "解析失敗")})
        return "unsupported_ext", 0

    try:
        courses = gemini_parse(data, mime, api_key)
    except Exception as e:
        print(f"  [gemini] {e}")
        if not dry_run:
            supa.patch_id(parent.id, {"tags": _with_state_tag(parent.tags, "解析失敗")})
        return "parse_failed", 0

    rows = []
    for c in courses:
        row = course_to_row(c, parent)
        if row:
            rows.append(row)
    if not rows:
        if not dry_run:
            supa.patch_id(parent.id, {"tags": _with_state_tag(parent.tags, "解析0堂")})
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
    ap.add_argument(
        "--html-only",
        action="store_true",
        help="僅走 HTML table path,遇到有附件的 parent 直接 skip(不動 tag)。"
             "配合 --all 可以一口氣救出『tag 已被剝掉但 Gemini 還沒處理』的中間狀態。"
             "不需要 GEMINI_API_KEY。",
    )
    args = ap.parse_args()

    supa_url = os.environ.get("SUPABASE_URL")
    supa_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    # retry-no-attachment / html-only 模式不走 Gemini,不需要 API key
    api_key = os.environ.get("GEMINI_API_KEY") or ""
    if not (supa_url and supa_key):
        print("[error] 缺 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY", file=sys.stderr)
        return 2
    if not args.retry_no_attachment and not args.html_only and not api_key:
        print("[error] 缺 GEMINI_API_KEY(一般模式要用 Gemini 解析 PDF)", file=sys.stderr)
        return 2

    supa = Supa(supa_url, supa_key)

    limit = None if args.all else args.limit
    ids = None
    if args.ids:
        ids = [int(x) for x in args.ids.split(",") if x.strip()]
    retry_tag = "無課表附件" if args.retry_no_attachment else None
    parents = supa.list_parents(limit=limit, ids=ids, retry_tag=retry_tag)

    # ATOMIC 設計:不再事先把『無課表附件』tag 全部剝掉。
    # process_one 在每筆成功處理後會用 _with_state_tag() 把舊的 state tag 換成新的,
    # 失敗(HTTP timeout 等)則完全不動 tag。這樣即使中途 cancel,未處理的 parent
    # 仍保有『無課表附件』tag,下次 --retry-no-attachment 還能找到、不會變 orphan。
    print(f"=== 將處理 {len(parents)} 筆月課表(workers={args.workers}) ===", flush=True)

    stats: dict[str, int] = {}
    total_inserted = 0

    def _work(p: Activity):
        try:
            status, n = process_one(p, supa, api_key, dry_run=args.dry_run, html_only=args.html_only)
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
