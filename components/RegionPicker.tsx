'use client';

/**
 * RegionPicker — 讓使用者選擇並記住所在縣市
 *
 * 三種狀態:
 *  1. hasCity = false (首次造訪,localStorage 無記錄) → 顯示底部 Banner 邀請選縣市
 *  2. hasCity = true  (已選,或 URL 帶 ?city=)         → 顯示頂部小 chip 可換縣市
 *  3. picking = true                                   → 展開全台縣市選擇器
 *
 * 資料流:
 *  URL ?city= ←→ localStorage lohascard_city ←→ RegionPicker state
 *  優先序:URL > localStorage。URL 變動時同步寫 localStorage。
 */

import { useRouter, useSearchParams, usePathname } from 'next/navigation';
import { useEffect, useState, useCallback } from 'react';
import { TAIWAN_REGIONS, GROUP_LABEL } from '@/lib/taiwan-regions';

const LS_KEY = 'lohascard_city';

const GROUP_ORDER = ['north', 'central', 'south', 'east', 'island'] as const;

const QUICK_CITIES = ['台北市', '新北市', '桃園市', '台中市', '台南市', '高雄市'];

export default function RegionPicker() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const urlCity = searchParams.get('city');

  const [mounted, setMounted] = useState(false);
  const [savedCity, setSavedCity] = useState<string | null>(null);
  const [picking, setPicking] = useState(false);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    setMounted(true);
    const stored = localStorage.getItem(LS_KEY);
    setSavedCity(stored);
  }, []);

  // URL ?city= 同步寫入 localStorage
  useEffect(() => {
    if (!mounted) return;
    if (urlCity) {
      localStorage.setItem(LS_KEY, urlCity);
      setSavedCity(urlCity);
    }
  }, [urlCity, mounted]);

  // 首次造訪:若 localStorage 有 city 但 URL 沒有,自動套用
  useEffect(() => {
    if (!mounted) return;
    if (savedCity && savedCity !== '__dismissed__' && savedCity !== '__picking__' && !urlCity) {
      const params = new URLSearchParams(searchParams.toString());
      params.set('city', savedCity);
      params.delete('page');
      router.replace(`${pathname}?${params.toString()}`);
    }
  }, [mounted]); // eslint-disable-line react-hooks/exhaustive-deps

  const setCity = useCallback(
    (city: string | null) => {
      const params = new URLSearchParams(searchParams.toString());
      params.delete('page');
      params.delete('district');
      if (city) {
        params.set('city', city);
        localStorage.setItem(LS_KEY, city);
        setSavedCity(city);
      } else {
        params.delete('city');
        localStorage.removeItem(LS_KEY);
        setSavedCity(null);
      }
      router.push(`${pathname}?${params.toString()}`);
      setPicking(false);
      setExpanded(false);
    },
    [searchParams, pathname, router]
  );

  if (!mounted) return null;

  const currentCity = urlCity ?? (savedCity && savedCity !== '__dismissed__' && savedCity !== '__picking__' ? savedCity : null);

  // =============================================
  // 展開縣市選擇器(picking 模式)
  // =============================================
  if (picking) {
    return (
      <div className="rounded-2xl border border-black/8 bg-paper-sunken p-5 space-y-4">
        <div className="flex items-center justify-between">
          <p className="text-[15px] font-medium text-ink">選擇你的地區</p>
          <button
            onClick={() => { setPicking(false); setExpanded(false); }}
            className="text-[13px] text-ink-faded hover:text-ink-soft"
          >
            取消
          </button>
        </div>

        <div>
          <p className="text-[12px] text-ink-faded mb-2 tracking-wide">六都快選</p>
          <div className="flex flex-wrap gap-2">
            {QUICK_CITIES.map((city) => (
              <button
                key={city}
                onClick={() => setCity(city)}
                className={`px-4 py-2 rounded-full text-[14px] border transition-colors ${
                  currentCity === city
                    ? 'bg-moss-700 text-paper border-moss-700'
                    : 'bg-paper border-black/10 text-ink hover:border-moss-400 hover:text-moss-800'
                }`}
              >
                {city}
              </button>
            ))}
          </div>
        </div>

        {!expanded ? (
          <button
            onClick={() => setExpanded(true)}
            className="text-[13px] text-ink-faded hover:text-ink-soft underline underline-offset-4"
          >
            其他縣市 →
          </button>
        ) : (
          <div className="space-y-3">
            {GROUP_ORDER.map((group) => {
              const cities = TAIWAN_REGIONS.filter((r) => r.group === group);
              return (
                <div key={group} className="flex flex-wrap gap-x-4 gap-y-1.5 items-center">
                  <span className="text-[12px] text-ink-faded w-10 shrink-0">{GROUP_LABEL[group]}</span>
                  {cities.map((r) => (
                    <button
                      key={r.city}
                      onClick={() => setCity(r.city)}
                      className={`text-[14px] transition-colors ${
                        currentCity === r.city
                          ? 'text-moss-700 font-medium underline underline-offset-4'
                          : 'text-ink-soft hover:text-ink'
                      }`}
                    >
                      {r.city}
                    </button>
                  ))}
                </div>
              );
            })}
            <button
              onClick={() => setExpanded(false)}
              className="text-[13px] text-ink-faded hover:text-ink-soft underline underline-offset-4"
            >
              ← 收起
            </button>
          </div>
        )}

        {currentCity && (
          <button
            onClick={() => setCity(null)}
            className="text-[13px] text-ink-faded hover:text-clay-600 underline underline-offset-4"
          >
            清除地區，看全台活動
          </button>
        )}
      </div>
    );
  }

  // =============================================
  // 已選縣市:顯示 chip
  // =============================================
  if (currentCity) {
    return (
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[13px] text-ink-faded">顯示地區</span>
        <button
          onClick={() => setPicking(true)}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-moss-700 text-paper text-[13px] font-medium hover:bg-moss-800 transition-colors"
        >
          <svg viewBox="0 0 24 24" className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0z" />
            <circle cx="12" cy="10" r="3" />
          </svg>
          {currentCity}
          <svg viewBox="0 0 24 24" className="w-3 h-3 opacity-70" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </button>
        <button
          onClick={() => setCity(null)}
          className="text-[12px] text-ink-faded hover:text-ink-soft transition-colors"
        >
          看全台
        </button>
      </div>
    );
  }

  // =============================================
  // 首次造訪:底部浮動 Banner
  // =============================================
  return (
    <div className="fixed bottom-0 left-0 right-0 z-50 p-4">
      <div className="max-w-2xl mx-auto bg-paper rounded-2xl shadow-2xl border border-black/8 p-5">
        <div className="flex items-start justify-between mb-4">
          <div>
            <p className="text-[16px] font-medium text-ink">你在哪個縣市？</p>
            <p className="text-[13px] text-ink-muted mt-0.5">選一個，幫你找附近的好活動</p>
          </div>
          <button
            onClick={() => {
              localStorage.setItem(LS_KEY + '_dismissed', '1');
              setSavedCity('__dismissed__');
            }}
            className="text-[22px] text-ink-faded leading-none hover:text-ink-soft ml-4"
            aria-label="關閉"
          >
            ×
          </button>
        </div>
        <div className="flex flex-wrap gap-2 mb-3">
          {QUICK_CITIES.map((city) => (
            <button
              key={city}
              onClick={() => setCity(city)}
              className="px-4 py-2 rounded-full text-[14px] border border-black/10 bg-paper text-ink hover:border-moss-400 hover:bg-moss-50 hover:text-moss-800 transition-colors"
            >
              {city}
            </button>
          ))}
        </div>
        <button
          onClick={() => { setPicking(true); setSavedCity('__picking__'); }}
          className="text-[13px] text-ink-faded hover:text-ink-soft underline underline-offset-4"
        >
          其他縣市 →
        </button>
      </div>
    </div>
  );
}
