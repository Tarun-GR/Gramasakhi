import { Sprout } from "lucide-react";
import { Link } from "react-router-dom";

export function BrandMark({ subtitle, className = "" }) {
  return (
    <div className={`flex items-center gap-3 ${className}`}>
      <div className="w-11 h-11 rounded-full bg-primary-container text-on-primary-container flex items-center justify-center shadow-inner ring-2 ring-secondary-container shrink-0">
        <Sprout className="w-6 h-6 text-tertiary-fixed-dim" />
      </div>
      <div>
        <p className="text-lg font-bold text-primary tracking-tight leading-tight">GramSakhi</p>
        {subtitle && (
          <p className="text-[11px] text-on-surface-variant font-normal">{subtitle}</p>
        )}
      </div>
    </div>
  );
}

export function MarketingNav({ rightSlot }) {
  return (
    <header className="fixed top-0 left-0 right-0 z-40 bg-surface/90 backdrop-blur-md border-b border-surface-variant/70">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
        <Link to="/" className="focus:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded-full">
          <BrandMark subtitle="Government scheme assistant" />
        </Link>
        <div className="flex items-center gap-2 sm:gap-3">{rightSlot}</div>
      </div>
    </header>
  );
}

export function MarketingFooter() {
  return (
    <footer className="py-8 border-t border-surface-variant text-center text-xs text-on-surface-variant px-4">
      GramSakhi — grounded vernacular assistance for last-mile governance
    </footer>
  );
}

export function MarketingPage({ children, navRight }) {
  return (
    <div
      className="min-h-screen bg-background text-on-background font-sans antialiased"
      style={{ fontFamily: "var(--font-vietnam), sans-serif" }}
    >
      <MarketingNav rightSlot={navRight} />
      {children}
      <MarketingFooter />
    </div>
  );
}
