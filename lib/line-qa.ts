// 樂活卡卡 — LINE bot Q&A 比對邏輯
// 使用者訊息進來 → 用關鍵字覆蓋率打分 → 取最高分 → 低於門檻走 fallback

export interface QAItem {
  /** 標準問題(顯示用/debug 用) */
  q: string;
  /** 回覆內容 */
  a: string;
  /** 比對用關鍵字,越多、越精準越好 */
  keywords: string[];
}

/** 30 題 — 跟 樂姐-AI聊天機器人-Q&A-v1.csv 對應 */
export const QA_BANK: QAItem[] = [
  {
    q: '樂活卡卡是什麼',
    a: '樂活卡卡是 55+ 的活動聚集地 ☀️ 免費講座、展覽、小旅行、志工、市集我都整理在這裡。直接上網看 → https://lohascard.vercel.app/?utm_source=line&utm_medium=bot',
    keywords: ['樂活卡卡', '什麼', '介紹', '這裡是', '做什麼'],
  },
  {
    q: '樂姐你是誰',
    a: '我是樂姐,58,退休 3 年。以前我也以為退休就沒事做,結果這 3 年是最自在的時候。找到好玩的就放到樂活卡卡,推薦給你 🌿',
    keywords: ['樂姐', '你是誰', '妳是誰', '介紹自己', '你好', '嗨'],
  },
  {
    q: '這是給誰用的',
    a: '給 55+ 剛開始有自己時間的人。退休、準退休,或單純想把生活過得有意思一點的都合。',
    keywords: ['給誰', '誰可以用', '誰適合', '年齡', '幾歲'],
  },
  {
    q: '跟其他活動網站差在哪',
    a: '我們只挑 55+ 合的。不是什麼都塞進來,是我先感覺「這 55+ 的人會喜歡嗎」再放上去。',
    keywords: ['差別', '不一樣', '差在哪', '特色', '其他網站', '為什麼用'],
  },
  {
    q: '要付費嗎',
    a: '樂活卡卡完全免費看。活動本身有的免費、有的要錢,卡片上都寫清楚了。免費的在這 → https://lohascard.vercel.app/?pricing=免費&utm_source=line&utm_medium=bot',
    keywords: ['付費', '收費', '要錢', '錢', '費用', '免費嗎', '要不要錢'],
  },
  {
    q: '怎麼找活動',
    a: '兩個方法。一是開 https://lohascard.vercel.app/?utm_source=line&utm_medium=bot 用上面篩選。二是直接跟我說「台北」「免費」「這週」這種關鍵字,我幫你挑。',
    keywords: ['怎麼找', '怎麼用', '怎麼看', '使用方法', '怎麼搜', '如何'],
  },
  {
    q: '下面的選單是什麼',
    a: '下面六格是快速分類:最新活動、免費好康、學習課程、健康養生、運動戶外、文娛旅遊。點哪格就帶你去那類的清單。',
    keywords: ['選單', '下面', '六格', '按鈕', '功能', '選項'],
  },
  {
    q: '活動多久更新一次',
    a: '每天自動更新。晚上補新的進來,早上看最新鮮 ☕️',
    keywords: ['多久更新', '更新', '多久', '頻率', '什麼時候更新'],
  },
  {
    q: '活動資料哪裡來',
    a: '目前從樂齡網、弘道基金會、台北旅遊網這些官方和基金會單位整理過來。都是正規的,放心看。',
    keywords: ['哪裡來', '資料來源', '來源', '真的嗎', '可靠嗎', '是真的嗎'],
  },
  {
    q: '最近有什麼活動',
    a: '最新的都在這 → https://lohascard.vercel.app/?utm_source=line&utm_medium=bot 最上面就是最新,滑一滑有沒有想去的。',
    keywords: ['最近', '最新', '新活動', '有什麼活動', '最近有', '新的'],
  },
  {
    q: '有沒有不用錢的',
    a: '免費的一籮筐 → https://lohascard.vercel.app/?pricing=免費&utm_source=line&utm_medium=bot 大部分是展覽、講座、社區活動。',
    keywords: ['免費', '不用錢', '不要錢', '白嫖', '省錢', '沒錢'],
  },
  {
    q: '想學點東西',
    a: '學習類的在這 → https://lohascard.vercel.app/?category=learning&utm_source=line&utm_medium=bot 攝影、語言、手工藝、電腦課都有。',
    keywords: ['學習', '上課', '學點', '課程', '想學', '進修'],
  },
  {
    q: '想找健康的活動',
    a: '健康養生類 → https://lohascard.vercel.app/?category=health&utm_source=line&utm_medium=bot 瑜伽、太極、養生講座、營養諮詢都在。',
    keywords: ['健康', '養生', '瑜伽', '太極', '身體', '保健'],
  },
  {
    q: '有運動或戶外的嗎',
    a: '運動戶外類 → https://lohascard.vercel.app/?category=sports&utm_source=line&utm_medium=bot 登山、健走、球類、戶外探險都有。',
    keywords: ['運動', '戶外', '登山', '健走', '爬山', '球類'],
  },
  {
    q: '想看展或小旅行',
    a: '文娛旅遊類 → https://lohascard.vercel.app/?category=culture&utm_source=line&utm_medium=bot 展覽、音樂會、小旅行、走讀都在。',
    keywords: ['展覽', '看展', '小旅行', '走讀', '音樂會', '文娛', '旅遊', '出遊'],
  },
  {
    q: '台北有什麼',
    a: '台北的活動 → https://lohascard.vercel.app/?city=台北市&utm_source=line&utm_medium=bot 最近展覽和講座特別多。',
    keywords: ['台北', '臺北', '北部', '台北市'],
  },
  {
    q: '台中有什麼',
    a: '台中這邊 → https://lohascard.vercel.app/?city=台中市&utm_source=line&utm_medium=bot 市集跟走讀還不錯。',
    keywords: ['台中', '臺中', '中部', '台中市'],
  },
  {
    q: '高雄有什麼',
    a: '高雄看這 → https://lohascard.vercel.app/?city=高雄市&utm_source=line&utm_medium=bot 戶外和文化類的蠻多。',
    keywords: ['高雄', '南部', '高雄市'],
  },
  {
    q: '這週末有什麼',
    a: '這週能去的 → https://lohascard.vercel.app/?utm_source=line&utm_medium=bot 最近的會排最上面,看到有興趣就點進去看細節。',
    keywords: ['這週', '本週', '這周', '週末', '周末', '這禮拜'],
  },
  {
    q: '下週可以去什麼',
    a: '下週的活動 → https://lohascard.vercel.app/?utm_source=line&utm_medium=bot 早一點規劃,比較不會撞到別的事。',
    keywords: ['下週', '下周', '下禮拜', '下星期'],
  },
  {
    q: '一個人可以去的活動',
    a: '一個人最適合的是講座、展覽、走讀這類。55+ 的場子大家滿開放的,去了很容易認識人。告訴我你住哪,我挑幾個給你。',
    keywords: ['一個人', '單獨', '自己去', '獨自', '交朋友'],
  },
  {
    q: '有可以帶孫子的嗎',
    a: '有!親子市集、博物館、自然走讀這類最合。最近好幾場都適合帶小朋友,要我挑給你嗎?',
    keywords: ['孫子', '孫女', '小朋友', '親子', '小孩', '帶小孩'],
  },
  {
    q: '想跟老伴一起去',
    a: '兩個人一起的話,小旅行、展覽、手作課最剛好。週末的場子很多,告訴我地區我幫你篩。',
    keywords: ['老伴', '老公', '老婆', '先生', '太太', '另一半', '兩個人'],
  },
  {
    q: '可以收藏活動嗎',
    a: '收藏功能上線了 ☕️ 上 https://lohascard.vercel.app 每張卡右上角有個愛心,點下去就能標「想去」「已報名」「去過了」。收藏完去「我的」頁看自己的清單。',
    keywords: ['收藏', '想去', '紀錄', '記下來', '加到', '存起來'],
  },
  {
    q: '我想記錄我去過的活動',
    a: '可以的 🌿 在 https://lohascard.vercel.app/me 有「我的」頁,可以記錄「想去」「已報名」「去過了」,看自己的生活慢慢累積。',
    keywords: ['記錄', '去過', '我的', '我去過', '清單', '手帳'],
  },
  {
    q: '推薦活動給我',
    a: '給我三個線索:你人在哪、喜歡哪類、這週還是下週要出門。我挑 3 個給你。',
    keywords: ['推薦', '幫我挑', '挑幾個', '介紹給我', '建議'],
  },
  {
    q: '樂姐你會記得我嗎',
    a: '現在還不會 😊 但這正是我們在做的事。之後你收藏什麼、去過什麼我都會記得,看你一年走過幾場、嘗試過幾種新體驗。慢慢來。',
    keywords: ['記得我', '認識我', '認得', '會不會記得'],
  },
  {
    q: '我身體不舒服怎麼辦',
    a: '身體的事要去給醫生看,別拖 🌿 緊急情況打 119。我這邊只能陪你找活動。',
    keywords: ['身體', '不舒服', '生病', '醫生', '醫療', '頭痛', '發燒'],
  },
  {
    q: '我有法律問題',
    a: '法律的事我不懂,建議你找法律扶助基金會(412-8518)或打 1999 市民專線問問。我這邊是活動資訊為主。',
    keywords: ['法律', '律師', '訴訟', '契約', '糾紛'],
  },
  {
    q: '我要找客服',
    a: '想找人聊可以直接在這裡留言,平日會有真人看。緊急事項打 1999 市民專線最快。',
    keywords: ['客服', '找人', '真人', '聯絡', '有人嗎'],
  },
];

export const FALLBACK_REPLY =
  '欸我一下沒接上。你想找什麼?直接打關鍵字我幫你看看:「免費」、「台北」、「這週」、「展」、「講座」、「市集」。或開網站逛 → https://lohascard.vercel.app';

export const WELCOME_REPLY = `嗨,我是樂姐 ☀️
今年 58,退休 3 年。

以前我也以為退休就是「沒事做」,結果這 3 年是我這輩子最自在的時候。

我把找到好玩的都整理在樂活卡卡 — 課程、展覽、小旅行、志工、市集都有。
不用急,先逛逛,點下面的選單看看。

想找什麼直接打字跟我說:
「免費」、「台北」、「這週」都行,我幫你挑。

網站:https://lohascard.vercel.app`;

/**
 * 比對使用者訊息跟 Q&A bank
 * 策略:
 *   1. 如果訊息包含標準問題 q,直接命中(score 999)
 *   2. 否則計算 keyword overlap(訊息包含幾個 keyword)
 *   3. 取最高分。低於 1 就走 fallback
 */
export function matchQA(userText: string): string {
  const text = userText.trim();
  if (!text) return FALLBACK_REPLY;

  let best = { score: 0, answer: FALLBACK_REPLY };

  for (const item of QA_BANK) {
    let score = 0;
    // 標準問題完全包含 → 最高分
    if (text.includes(item.q)) {
      score = 999;
    } else {
      // 關鍵字覆蓋率
      for (const kw of item.keywords) {
        if (text.includes(kw)) score += 1;
      }
    }
    if (score > best.score) {
      best = { score, answer: item.a };
    }
  }

  // 門檻:至少要命中一個 keyword 才算匹配
  if (best.score < 1) return FALLBACK_REPLY;
  return best.answer;
}
