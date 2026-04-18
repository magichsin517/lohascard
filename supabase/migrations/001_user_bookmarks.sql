-- ========================================
-- 樂活卡卡 - 豆瓣式個人收藏功能 (Phase 1)
-- ========================================
-- 執行方式: Supabase Dashboard → SQL Editor → New query →
-- 把整個檔案貼進去 → Run
-- 這個 migration 獨立於 schema.sql,不會動到 activities 資料
-- ========================================

-- 個人收藏表
-- 使用 anon_id (client 產生的 uuid,存 localStorage) 做匿名識別
-- 未來若要做 LIFF 登入,可加 line_user_id 欄位並 backfill
create table if not exists user_bookmarks (
  id bigserial primary key,
  anon_id uuid not null,
  activity_id bigint not null references activities(id) on delete cascade,
  status text not null check (status in ('want', 'registered', 'done')),
  -- want       = 想去
  -- registered = 已報名
  -- done       = 去過了
  note text,               -- 預留給 Phase 2 寫心得
  rating smallint check (rating between 1 and 5),  -- 預留給 Phase 2 打星
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique (anon_id, activity_id)  -- 一個 user 對同一活動只有一個狀態
);

create index if not exists idx_user_bookmarks_anon_id on user_bookmarks(anon_id);
create index if not exists idx_user_bookmarks_activity_id on user_bookmarks(activity_id);
create index if not exists idx_user_bookmarks_status on user_bookmarks(status);

-- 自動更新 updated_at
drop trigger if exists user_bookmarks_updated_at on user_bookmarks;
create trigger user_bookmarks_updated_at
  before update on user_bookmarks
  for each row execute function update_updated_at();

-- ========================================
-- RLS (Row Level Security)
-- ========================================
-- 匿名模式:anon_id 是 client 產生的 UUID (不可猜測),
-- 因此允許 public 對 user_bookmarks 做 CRUD。
-- 未來接 LIFF 登入後,改用 auth.uid() 綁定 line_user_id 才能嚴格做隔離。
alter table user_bookmarks enable row level security;

drop policy if exists "anyone can read bookmarks" on user_bookmarks;
drop policy if exists "anyone can insert bookmarks" on user_bookmarks;
drop policy if exists "anyone can update bookmarks" on user_bookmarks;
drop policy if exists "anyone can delete bookmarks" on user_bookmarks;

create policy "anyone can read bookmarks"
  on user_bookmarks for select
  using (true);

create policy "anyone can insert bookmarks"
  on user_bookmarks for insert
  with check (true);

create policy "anyone can update bookmarks"
  on user_bookmarks for update
  using (true);

create policy "anyone can delete bookmarks"
  on user_bookmarks for delete
  using (true);

-- ========================================
-- 完成 ✅
-- ========================================
