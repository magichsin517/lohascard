-- 樂活卡卡:簡轉繁 UPDATE SQL
-- 在 Supabase SQL Editor 執行一次即可

BEGIN;

UPDATE activities SET
  title = '樂齡太極拳班 - 初階',
  description = '每週二早上在士林老人服務中心的太極拳課程。由資深師傅教學,適合完全沒基礎的初學者。動作和緩,重視呼吸與放鬆,是很好的身心調養。可自行前往或電話報名。',
  summary = '適合完全沒經驗的長輩,老師很有耐心',
  organizer_name = '士林區公所',
  recurring_rule = '每週二',
  location_name = '士林老人服務中心',
  address = '台北市士林區中正路439號',
  city = '台北市',
  district = '士林區',
  tags = ARRAY['免費', '初學者']::text[]
WHERE id = 1;

UPDATE activities SET
  title = '智慧手機新手班',
  description = '教你手機的基本功能,包括 LINE 通話與貼圖、照片拍攝與傳送、Google 搜尋。每堂課都有年輕志工一對一協助,不怕學不會。',
  summary = '從 LINE 視訊到拍照,一對一志工協助',
  organizer_name = '士林區樂齡學習中心',
  location_name = '士林區樂齡學習中心',
  address = '台北市士林區士東路308號',
  city = '台北市',
  district = '士林區',
  tags = ARRAY['免費', '熱門', '初學者']::text[]
WHERE id = 2;

UPDATE activities SET
  title = '北美館導覽 - 春季特展',
  description = '特別為長輩安排的導覽時段,資深導覽員講解速度較慢,並安排休息時間。參觀完有茶點時間,與其他觀眾交流心得。',
  summary = '資深導覽員慢慢講解,適合慢步調',
  organizer_name = '台北市立美術館',
  location_name = '台北市立美術館',
  address = '台北市中山區中山北路三段181號',
  city = '台北市',
  district = '中山區',
  tags = ARRAY['小額收費']::text[]
WHERE id = 3;

UPDATE activities SET
  title = '社群健康檢查日',
  description = '護理師現場檢測血壓、血糖、體脂,並提供健康諮詢。無需事先報名,直接前往即可。建議空腹前往以便進行血糖測試。',
  summary = '免費血壓、血糖、體脂檢測',
  organizer_name = '士林健康服務中心',
  location_name = '天母社群活動中心',
  address = '台北市士林區中山北路六段88號',
  city = '台北市',
  district = '士林區',
  tags = ARRAY['免費', '不需報名']::text[]
WHERE id = 4;

UPDATE activities SET
  title = '銀髮卡拉 OK 下午',
  description = '經典國台語老歌為主,由志工帶領。適合喜歡唱歌、想結交朋友的長輩。現場提供簡單茶點。',
  summary = '國台語老歌,跟朋友聚會唱歌',
  organizer_name = '天主教失智老人基金會',
  recurring_rule = '每週三',
  location_name = '士林社群關懷據點',
  address = '台北市士林區文林路235號',
  city = '台北市',
  district = '士林區',
  tags = ARRAY['免費', '每週固定']::text[]
WHERE id = 5;

UPDATE activities SET
  title = '平溪半日遊 - 春日踏青',
  description = '專為長輩設計的慢步調行程。上午前往平溪老街散步,中午品嚐當地特色便當,下午參觀菁桐車站後返程。全程有領隊陪同。',
  summary = '含遊覽車、簡餐、保險,行程輕鬆',
  organizer_name = '士林區公所',
  location_name = '士林區公所集合',
  address = '台北市士林區中正路439號',
  city = '台北市',
  district = '士林區',
  tags = ARRAY['報名截止 4/28']::text[]
WHERE id = 6;

UPDATE activities SET
  title = '長青書法班',
  description = '由退休書法老師帶領,從握筆、姿勢開始教學。每人一套筆墨紙硯,不需自備。適合想培養靜心興趣的長輩。',
  summary = '從握筆開始教,不怕沒基礎',
  organizer_name = '士林老人服務中心',
  recurring_rule = '每週四',
  location_name = '士林老人服務中心',
  address = '台北市士林區中正路439號',
  city = '台北市',
  district = '士林區',
  tags = ARRAY['免費', '每週固定']::text[]
WHERE id = 7;

UPDATE activities SET
  title = '失智友善咖啡館',
  description = '每月一次的聚會,提供失智症患者與家屬一個放鬆、交流、互相支援的空間。有專業人員帶領簡單活動,也有悠閒的喝咖啡時間。',
  summary = '失智症家庭互助聚會',
  organizer_name = '天主教失智老人基金會',
  location_name = '萬華老人服務中心',
  address = '台北市萬華區東園街19號',
  city = '台北市',
  district = '萬華區',
  tags = ARRAY['免費', '每月一次']::text[]
WHERE id = 8;

UPDATE organizers SET
  name = '士林區公所'
WHERE id = 1;

UPDATE organizers SET
  name = '士林老人服務中心'
WHERE id = 2;

UPDATE organizers SET
  name = '士林區樂齡學習中心'
WHERE id = 3;

UPDATE organizers SET
  name = '天主教失智老人基金會'
WHERE id = 4;

UPDATE organizers SET
  name = '台北市立美術館'
WHERE id = 5;

UPDATE organizers SET
  name = '士林健康服務中心'
WHERE id = 6;

COMMIT;
