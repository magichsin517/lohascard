# 樂活卡卡 Lohas Card

台灣 60+ 活力銀髮族的活動聚合平台

---

## 這份檔案教你:從 zip 檔到看到網頁

全程大約 15-20 分鐘,完全不需要會寫 code,照著做就好。

遇到任何步驟卡住,**把錯誤訊息截圖,告訴 Claude 「跑到第 X 步卡住了」,他會幫你處理**。

---

## 準備工作 (只需做一次)

### 1. 確認 Node.js 已經裝好

開啟 **終端機 (Terminal)** (Mac 在 應用程式 → 工具程式 → 終端機),輸入:

```bash
node -v
```

應該會印出 `v22.x.x` 或更高的版本號。如果印出版本號,就 OK,跳到第 2 步。

如果印出 `command not found`,去 https://nodejs.org/ 下載 LTS 版本 (大的綠色按鈕),裝好再回來。

### 2. 把這個專案放到電腦裡

假設你解壓 zip 後,資料夾在 `~/Downloads/lohascard`。用終端機切換過去:

```bash
cd ~/Downloads/lohascard
```

(`cd` 是 change directory,切換資料夾的意思。你的路徑可能不一樣,依照你實際放的位置調整。)

### 3. 安裝專案需要的套件

```bash
npm install
```

會花 1-3 分鐘,終端機會跑一堆字。結束時會看到類似 `added 234 packages` 的訊息。

如果你有開 VPN / 代理 (你之前截圖有這情況),可能會裝不起來。關掉 VPN 再試。

---

## 建立資料庫 (只需做一次)

### 4. 開啟 Supabase 的 SQL Editor

- 開啟 https://supabase.com/dashboard
- 點進你的 `lohascard` 專案
- 左側選單找到「SQL Editor」
- 按上方「New query」

### 5. 執行 schema.sql

- 用文字編輯器開啟專案裡的 `supabase/schema.sql`
- 全選、複製
- 貼到 Supabase 的 SQL Editor 裡
- 點右下角綠色的「Run」

成功的話,會看到 `Success. No rows returned`。

### 6. 驗證資料進去了

- 左側選單點「Table Editor」
- 你會看到兩個資料表:`activities` 和 `organizers`
- 點 `activities`,應該看到 8 筆示範活動

---

## 跑起來!

### 7. 啟動本地開發伺服器

回到終端機 (還在 `lohascard` 資料夾裡),輸入:

```bash
npm run dev
```

看到類似這樣的訊息就是成功了:

```
  ▲ Next.js 15.0.3
  - Local:        http://localhost:3000
  ✓ Ready in 1.2s
```

### 8. 開啟瀏覽器看網頁

開啟 **Chrome / Safari**,網址列輸入:

```
http://localhost:3000
```

🎉 **你應該會看到樂活卡卡的首頁,上面有 8 張活動卡片**。

點任何一張卡片,會進入活動詳情頁。

---

## 每次要開發的 routine

以後每次你要回來工作:

```bash
cd ~/Downloads/lohascard
npm run dev
```

就這樣。不用再 `npm install`。

要停止,在終端機按 `Ctrl + C`。

---

## 檔案結構導覽 (想知道哪裡改哪裡)

```
lohascard/
├── app/
│   ├── page.tsx                  ← 首頁 (活動列表)
│   ├── activities/[id]/page.tsx  ← 活動詳情頁
│   ├── layout.tsx                ← 全站外框
│   ├── globals.css               ← 全域 CSS
│   └── not-found.tsx             ← 404 頁
│
├── components/
│   ├── Header.tsx                ← 頂部導航
│   ├── ActivityCard.tsx          ← 活動卡片
│   ├── CategoryFilter.tsx        ← 分類篩選 (運動/學習/...)
│   ├── DistrictFilter.tsx        ← 區域篩選 (士林區/信義區/...)
│   └── LineCallout.tsx           ← LINE 加入引導區塊
│
├── lib/
│   └── supabase.ts               ← 連 Supabase + 型別定義
│
├── public/images/categories/     ← 7 張分類預設圖
│
├── supabase/
│   └── schema.sql                ← 資料庫建立指令碼
│
├── .env.local                    ← 🔐 Supabase 連線設定 (不要傳到 Git)
├── package.json                  ← 專案依賴清單
└── tailwind.config.ts            ← 設計 token (顏色、字型)
```

---

## 接下來做什麼

第一次跑起來之後,建議你按這個順序前進:

### 第一週
- [ ] 網站在電腦上跑起來,看到活動列表
- [ ] 進去 Supabase 的 Table Editor,手動新增一筆真實活動試試
- [ ] 重整網頁,確認你新增的活動出現了

### 第二週
- [ ] 部署到 Vercel,拿到一個公開網址 (xxx.vercel.app)
- [ ] 發給岳父岳母看:「這是我做的,你覺得這些活動你會想去嗎?」
- [ ] 根據他們反應,調整首頁文案 / 卡片資訊的呈現

### 第三~四周
- [ ] 申請 LINE 官方帳號 (manager.line.biz)
- [ ] 寫第一支爬蟲,從 data.taipei 抓社群照顧關懷據點資料
- [ ] 把真實活動資料灌進 Supabase

### 遇到任何不會的,回來找 Claude。
不管是 code 出錯、想改設計、想加功能、想寫爬蟲,都可以。

---

## 小提醒:環境變數安全

`.env.local` 這個檔案裡有你的 Supabase 連線設定。

- ✅ `NEXT_PUBLIC_SUPABASE_URL` — 公開的,沒關係
- ✅ `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` — 公開的,是設計來給前端用的
- ❌ **Database password** 不在這裡,也不該放這裡

`.gitignore` 已經設定好不會把 `.env.local` commit 進 Git,放心。

之後如果你要做爬蟲,會需要 `SUPABASE_SERVICE_ROLE_KEY` (這個是高許可權的),那個放在另一個 `.env.local` 裡,而且**只在後端/爬蟲 script 用,絕對不會出現在前端 code**。到時候再說。

---

## 部署到 Vercel (之後才做)

當你本地跑順了,想讓別人用網址看到:

1. 把 code 推到 GitHub (建一個 private repo)
2. 去 https://vercel.com/new
3. 選你剛推的 repo,點「Import」
4. 在 Environment Variables 欄位,貼上 `.env.local` 裡的兩行
5. 點「Deploy」

約 2 分鐘,你就有一個 `lohascard-xxx.vercel.app` 的網址了。

---

## 技術棧說明 (給好奇的你)

| 工具 | 做什麼 |
|------|-------|
| **Next.js 15** | 網頁框架,讓一份 code 能同時處理前端和後端 |
| **React 19** | 畫面元件 |
| **TypeScript** | 加上型別檢查,避免亂改東西出 bug |
| **Tailwind CSS** | 樣式系統,直接在 HTML 裡寫 CSS class |
| **Supabase** | 免費的 Postgres 資料庫 + 使用者認證 + API |
| **Vercel** | 免費部署,push 到 GitHub 就自動更新網站 |

這個棧在 2026 年是主流,資源豐富,未來擴充套件性高。

---

**祝你順利。跑起來之後發個畫面給 Claude 看看。**
