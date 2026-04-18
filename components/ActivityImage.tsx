'use client';

import { useState } from 'react';

/**
 * 活動卡片圖片 — 用原生 <img> 避開 Next Image 的 remotePatterns 限制,
 * 因為爬蟲抓回來的 image_url 來自一堆不同 gov 網域,一個個加白名單不實際。
 * 圖片壞掉(e.g. gov DB 裡 filename 對不上實際檔案,回 302 redirect 到
 * error 頁)時自動 fallback 到 category SVG。
 */
type Props = {
  imageUrl: string | null;
  category: string | null;
  title: string;
};

function fallbackSrc(category: string | null): string {
  return `/images/categories/${category || 'social'}.svg`;
}

export default function ActivityImage({ imageUrl, category, title }: Props) {
  const [broken, setBroken] = useState(false);
  const src = imageUrl && !broken ? imageUrl : fallbackSrc(category);

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt={title}
      loading="lazy"
      className="absolute inset-0 w-full h-full object-cover group-hover:scale-[1.03] transition-transform duration-500"
      onError={() => {
        if (!broken) setBroken(true);
      }}
    />
  );
}
