/**
 * Feature flags.
 *
 * 預設所有 flag 都 off。切 on 需要在 Vercel 環境變數(或 .env.local)
 * 把對應的 NEXT_PUBLIC_* 變數設成 "on"(不分大小寫)。
 */

export const CURATED_MODE =
  (process.env.NEXT_PUBLIC_CURATED_MODE ?? 'off').toLowerCase() === 'on';
