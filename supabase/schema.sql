-- ========================================
-- 樂活卡卡 - 資料庫 Schema
-- ========================================
-- 執行方式: 去 Supabase Dashboard → SQL Editor → New query → 
-- 把這整個檔案貼進去 → Run
-- ========================================

-- 清除舊資料表 (如果之前建過),方便重新來過
drop table if exists activities cascade;
drop table if exists organizers cascade;

-- ========================================
-- 主辦單位資料表
-- ========================================
create table organizers (
  id bigserial primary key,
  name text not null,
  type text check (type in ('gov', 'ngo', 'community', 'commercial')),
  website text,
  phone text,
  created_at timestamptz default now()
);

create index idx_organizers_type on organizers(type);

-- ========================================
-- 活動資料表 (核心)
-- ========================================
create table activities (
  id bigserial primary key,
  
  -- 基本資訊
  title text not null,
  description text,
  summary text,              -- 一句話簡短說明 (給卡片用)
  
  -- 主辦
  organizer_id bigint references organizers(id),
  organizer_name text,       -- 冗餘欄位,方便查詢不用 join
  
  -- 時間 (兩種活動形式)
  event_type text check (event_type in ('single', 'recurring')) default 'single',
  start_date date,           -- 單次活動的日期
  end_date date,             -- 單次活動的結束日期
  start_time time,
  end_time time,
  recurring_rule text,       -- 定期活動的規則,例如 "每週二"
  
  -- 地點
  location_name text,
  address text,
  city text,                 -- 台北市 / 新北市 / 桃園市...
  district text,             -- 士林區 / 信義區...
  latitude numeric,
  longitude numeric,
  
  -- 分類
  category text check (category in (
    'sports',     -- 運動
    'learning',   -- 學習
    'health',     -- 健康
    'culture',    -- 文娛
    'travel',     -- 旅遊
    'social',     -- 社交
    'volunteer'   -- 志願服務
  )),
  tags text[] default '{}',  -- 彈性標籤:免費、熱門、初學者...
  
  -- 對象
  target_audience text,      -- "55+" / "60+" / "65+" / "不限"
  
  -- 費用
  cost integer default 0,    -- 費用 (新台幣),0 = 免費
  cost_note text,
  
  -- 報名
  signup_method text check (signup_method in ('phone', 'online', 'walk_in', 'email', 'none')),
  signup_url text,
  signup_phone text,
  signup_deadline date,
  capacity integer,
  
  -- 圖片
  image_url text,
  
  -- 資料來源
  source_url text,
  source_name text,
  last_verified_at timestamptz,
  
  -- 狀態
  status text check (status in ('active', 'cancelled', 'ended', 'draft')) default 'active',
  
  -- 自動時間戳
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- 索引 (讓查詢更快)
create index idx_activities_status on activities(status);
create index idx_activities_city_district on activities(city, district);
create index idx_activities_category on activities(category);
create index idx_activities_start_date on activities(start_date);
create index idx_activities_tags on activities using gin(tags);

-- 自動更新 updated_at 的 trigger
create or replace function update_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

create trigger activities_updated_at
  before update on activities
  for each row execute function update_updated_at();

-- ========================================
-- Row Level Security (安全性設定)
-- ========================================
-- 讓網頁前端可以"讀取" activities,但不能"寫入"
-- 寫入只能透過 service_role key (爬蟲/管理後台用)
alter table activities enable row level security;
alter table organizers enable row level security;

create policy "anyone can read active activities"
  on activities for select
  using (status = 'active');

create policy "anyone can read organizers"
  on organizers for select
  using (true);

-- ========================================
-- 塞入示範資料 (讓網頁馬上有東西看)
-- ========================================

insert into organizers (name, type, phone) values
  ('士林區公所', 'gov', '02-2882-6200'),
  ('士林老人服務中心', 'gov', '02-2882-9706'),
  ('士林區樂齡學習中心', 'gov', '02-2881-1203'),
  ('天主教失智老人基金會', 'ngo', '02-2332-0992'),
  ('台北市立美術館', 'gov', '02-2595-7656'),
  ('士林健康服務中心', 'gov', '02-2881-3039');

insert into activities (
  title, summary, description, 
  organizer_name, event_type, start_date, start_time, end_time, recurring_rule,
  location_name, address, city, district,
  category, tags, target_audience, cost, 
  signup_method, signup_phone, image_url
) values
(
  '樂齡太極拳班 - 初階',
  '適合完全沒經驗的長輩,老師很有耐心',
  '每週二早上在士林老人服務中心的太極拳課程。由資深師傅教學,適合完全沒基礎的初學者。動作和緩,重視呼吸與放鬆,是很好的身心調養。可自行前往或電話報名。',
  '士林區公所',
  'recurring', null, '09:30', '11:00', '每週二',
  '士林老人服務中心', '台北市士林區中正路439號', '台北市', '士林區',
  'sports', array['免費', '初學者'], '55+', 0,
  'phone', '02-2882-9706',
  null
),
(
  '智慧手機新手班',
  '從 LINE 視訊到拍照,一對一志工協助',
  '教你手機的基本功能,包括 LINE 通話與貼圖、照片拍攝與傳送、Google 搜尋。每堂課都有年輕志工一對一協助,不怕學不會。',
  '士林區樂齡學習中心',
  'single', '2026-04-22', '14:00', '16:00', null,
  '士林區樂齡學習中心', '台北市士林區士東路308號', '台北市', '士林區',
  'learning', array['免費', '熱門', '初學者'], '55+', 0,
  'phone', '02-2881-1203',
  null
),
(
  '北美館導覽 - 春季特展',
  '資深導覽員慢慢講解,適合慢步調',
  '特別為長輩安排的導覽時段,資深導覽員講解速度較慢,並安排休息時間。參觀完有茶點時間,與其他觀眾交流心得。',
  '台北市立美術館',
  'single', '2026-04-24', '10:00', '12:00', null,
  '台北市立美術館', '台北市中山區中山北路三段181號', '台北市', '中山區',
  'culture', array['小額收費'], '不限', 100,
  'online', null,
  null
),
(
  '社群健康檢查日',
  '免費血壓、血糖、體脂檢測',
  '護理師現場檢測血壓、血糖、體脂,並提供健康諮詢。無需事先報名,直接前往即可。建議空腹前往以便進行血糖測試。',
  '士林健康服務中心',
  'single', '2026-04-25', '09:00', '11:30', null,
  '天母社群活動中心', '台北市士林區中山北路六段88號', '台北市', '士林區',
  'health', array['免費', '不需報名'], '55+', 0,
  'walk_in', null,
  null
),
(
  '銀髮卡拉 OK 下午',
  '國台語老歌,跟朋友聚會唱歌',
  '經典國台語老歌為主,由志工帶領。適合喜歡唱歌、想結交朋友的長輩。現場提供簡單茶點。',
  '天主教失智老人基金會',
  'recurring', null, '14:00', '16:30', '每週三',
  '士林社群關懷據點', '台北市士林區文林路235號', '台北市', '士林區',
  'culture', array['免費', '每週固定'], '60+', 0,
  'walk_in', null,
  null
),
(
  '平溪半日遊 - 春日踏青',
  '含遊覽車、簡餐、保險,行程輕鬆',
  '專為長輩設計的慢步調行程。上午前往平溪老街散步,中午品嚐當地特色便當,下午參觀菁桐車站後返程。全程有領隊陪同。',
  '士林區公所',
  'single', '2026-05-08', '08:30', '16:00', null,
  '士林區公所集合', '台北市士林區中正路439號', '台北市', '士林區',
  'travel', array['報名截止 4/28'], '60+', 680,
  'phone', '02-2882-6200',
  null
),
(
  '長青書法班',
  '從握筆開始教,不怕沒基礎',
  '由退休書法老師帶領,從握筆、姿勢開始教學。每人一套筆墨紙硯,不需自備。適合想培養靜心興趣的長輩。',
  '士林老人服務中心',
  'recurring', null, '09:00', '11:00', '每週四',
  '士林老人服務中心', '台北市士林區中正路439號', '台北市', '士林區',
  'learning', array['免費', '每週固定'], '55+', 0,
  'phone', '02-2882-9706',
  null
),
(
  '失智友善咖啡館',
  '失智症家庭互助聚會',
  '每月一次的聚會,提供失智症患者與家屬一個放鬆、交流、互相支援的空間。有專業人員帶領簡單活動,也有悠閒的喝咖啡時間。',
  '天主教失智老人基金會',
  'single', '2026-04-27', '14:00', '16:00', null,
  '萬華老人服務中心', '台北市萬華區東園街19號', '台北市', '萬華區',
  'health', array['免費', '每月一次'], '不限', 0,
  'phone', '02-2332-0992',
  null
);

-- ========================================
-- 完成 ✅
-- ========================================
-- 可以到 Table Editor 看一下 activities 資料表
-- 應該會看到 8 筆示範活動
