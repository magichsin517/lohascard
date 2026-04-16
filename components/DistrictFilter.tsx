'use client';

import { useRouter, useSearchParams, usePathname } from 'next/navigation';
import { useState, useMemo } from 'react';
import { TAIWAN_REGIONS, GROUP_LABEL, Region } from '@/lib/taiwan-regions';

// 地區 filter:兩層
// 1. 第一層:縣市(22 個,按北/中/南/東/離島分組)
// 2. 第二層:選了縣市後才顯示該縣市的鄉鎮市區
// URL 參數:?city=台北市&district=士林區

export default function DistrictFilter() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const currentCity = searchParams.get('city');
  const currentDistrict = searchParams.get('district');
  const [expanded, setExpanded] = useState(false);

  const grouped = useMemo(() => {
    const groups: Record<Region['group'], Region[]> = { north: [], central: [], south: [], east: [], island: [] };
    for (const r of TAIWAN_REGIONS) groups[r.group].push(r);
    return groups;
  }, []);

  const selectedRegion = useMemo(
    () => TAIWAN_REGIONS.find((r) => r.city === currentCity) ?? null,
    [currentCity]
  );

  const setCity = (city: string | null) => {
    const params = new URLSearchParams(searchParams.toString());
    if (!city) {
      params.delete('city');
      params.delete('district');
    } else {
      params.set('city', city);
      params.delete('district');
    }
    router.push(`${pathname}?${params.toString()}`);
  };

  const setDistrict = (district: string | null) => {
    const params = new URLSearchParams(searchParams.toString());
    if (!district) {
      params.delete('district');
    } else {
      params.set('district', district);
    }
    router.push(`${pathname}?${params.toString()}`);
  };

  // 常用縣市(精選,未展開時顯示)
  const quickCities = ['台北市', '新北市', '桃園市', '台中市', '台南市', '高雄市'];

  return (
    <div className="text-[12.5px] text-ink-muted space-y-3">
      {/* 第一層:縣市 */}
      {!selectedRegion && !expanded && (
        <div className="flex gap-x-2 gap-y-1 flex-wrap items-baseline">
          <span className="text-ink-faded text-[11px] tracking-wider shrink-0 mr-1">縣市</span>
          {quickCities.map((city) => (
            <button key={city} onClick={() => setCity(city)} className="hover:text-ink-soft transition-colors">
              {city}
            </button>
          ))}
          <button
            onClick={() => setExpanded(true)}
            className="text-[11px] text-ink-faded hover:text-ink-soft underline underline-offset-4"
          >
            全部縣市 →
          </button>
        </div>
      )}

      {!selectedRegion && expanded && (
        <div className="space-y-1.5">
          {(['north', 'central', 'south', 'east', 'island'] as const).map((group) => (
            <div key={group} className="flex gap-x-2 gap-y-1 flex-wrap items-baseline">
              <span className="text-ink-faded text-[11px] tracking-wider shrink-0 mr-1">
                {GROUP_LABEL[group]}
              </span>
              {grouped[group].map((r) => (
                <button
                  key={r.city}
                  onClick={() => setCity(r.city)}
                  className="hover:text-ink-soft transition-colors"
                >
                  {r.city}
                </button>
              ))}
            </div>
          ))}
          <button
            onClick={() => setExpanded(false)}
            className="text-[11px] text-ink-faded hover:text-ink-soft underline underline-offset-4"
          >
            ← 收起
          </button>
        </div>
      )}

      {/* 第二層:選了縣市後顯示該縣市鄉鎮市區 */}
      {selectedRegion && (
        <div className="space-y-2">
          <div className="flex items-baseline gap-2">
            <span className="text-ink-faded text-[11px] tracking-wider">縣市</span>
            <span className="text-ink font-medium">{selectedRegion.city}</span>
            <button
              onClick={() => setCity(null)}
              className="text-[11px] text-clay-500 hover:text-clay-700"
            >
              ← 換一個縣市
            </button>
          </div>
          <div className="flex gap-x-2 gap-y-1 flex-wrap items-baseline">
            <span className="text-ink-faded text-[11px] tracking-wider shrink-0 mr-1">鄉鎮區</span>
            {selectedRegion.districts.map((d) => {
              const isActive = currentDistrict === d;
              return (
                <button
                  key={d}
                  onClick={() => setDistrict(isActive ? null : d)}
                  className={`transition-colors ${
                    isActive
                      ? 'text-ink font-medium underline underline-offset-4'
                      : 'hover:text-ink-soft'
                  }`}
                >
                  {d}
                </button>
              );
            })}
            {currentDistrict && (
              <button
                onClick={() => setDistrict(null)}
                className="text-[11px] text-clay-500 hover:text-clay-700 ml-2"
              >
                清除
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
