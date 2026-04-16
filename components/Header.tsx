import Link from 'next/link';

export default function Header() {
  return (
    <header className="border-b border-black/5 bg-paper/80 backdrop-blur-sm sticky top-0 z-40">
      <div className="max-w-6xl mx-auto px-5 md:px-8 py-4 flex items-center justify-between">
        <Link href="/" className="flex items-baseline gap-3 group">
          <span className="font-display text-2xl md:text-[26px] font-medium tracking-tight text-ink">
            樂活卡卡
          </span>
          <span className="hidden sm:inline text-xs text-ink-muted tracking-wider uppercase">
            Lohas Card
          </span>
        </Link>

        <a
          href="https://line.me"
          target="_blank"
          rel="noopener noreferrer"
          className="text-sm px-4 py-2 rounded-full bg-ink text-paper hover:bg-ink-soft transition-colors"
        >
          加入 LINE
        </a>
      </div>
    </header>
  );
}
