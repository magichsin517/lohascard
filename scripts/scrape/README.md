# 樂活卡卡 — 資料爬蟲

## 目前有什麼

`senioredu_moe.py` — 教育部樂齡學習網(全台 22 縣市)爬蟲。

每個縣市子網站首頁會列出「最新的樂齡學習中心公告」,本爬蟲抓這些公告並寫入 Supabase `activities` 資料表。粒度是月(一筆公告 ≈ 一間中心當月課表),使用者點連結可看原始課表與聯絡方式。

資料來源:<https://moe.senioredu.moe.gov.tw/>

## 怎麼跑

先把 Supabase credentials export 到環境變數:

```bash
export SUPABASE_URL="https://gmkninjqovstadaztvmm.supabase.co"
export SUPABASE_SERVICE_ROLE_KEY="<你的 service_role key>"
```

service_role key 位置:Supabase Dashboard → Project Settings → API → `service_role`(灰色 Reveal)。**不要 commit 到 git,也不要公開**。

### 僅爬不寫 DB(除錯用)

```bash
python3 scripts/scrape/senioredu_moe.py --out /tmp/senioredu.json
```

### 爬完後直接寫入 Supabase(去重)

```bash
python3 scripts/scrape/senioredu_moe.py --upsert
```

去重鍵是 `source_url` — 同一筆公告重跑不會重複插入。

### 只抓特定縣市

```bash
python3 scripts/scrape/senioredu_moe.py --cities Taipei Kaohsiung --upsert
```

全部縣市代號見檔案最上方 `CITY_MAP`。

## 建議更新頻率

樂齡中心每月發一次當期課表,每月 1 號跑一次就好。可以手動跑,或之後接 cron / GitHub Actions。

## 待辦 / 可加強

- 分頁 — 目前只抓首頁 10 筆/縣市,每縣市其實有數十筆歷史資料。要完整抓要實作 `查看更多` 分頁。
- 詳細頁內容 — 現在只抓公告標題,詳細的課名、時段、費用都在原始公告頁(通常是 PDF 或圖片),沒解析。
- 其他資料源
  - 衛福部社區照顧關懷據點(venue 資料,3000+ 據點)
  - 各直轄市政府活動行事曆(雙北、桃竹中南高)
  - Accupass「樂齡」類活動(需要 headless browser)
