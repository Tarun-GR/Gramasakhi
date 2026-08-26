/** Primary action button — matches uploaded GramSakhi chat UI. */
export function GsButton({
  variant = "primary",
  size = "md",
  fullWidth = false,
  className = "",
  children,
  ...rest
}) {
  const base =
    "inline-flex items-center justify-center gap-2 font-bold rounded-full transition-all duration-200 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40";
  const sizes = {
    sm: "px-4 py-2 text-xs",
    md: "px-5 py-2.5 text-sm",
    lg: "px-7 py-3.5 text-base",
  };
  const variants = {
    primary: "bg-primary text-on-primary hover:bg-surface-tint shadow-sm",
    secondary:
      "bg-secondary-container text-primary hover:bg-surface-container-high border border-surface-variant/60",
    ghost:
      "text-on-surface-variant hover:bg-surface-variant hover:text-primary bg-transparent",
    outline:
      "border-2 border-primary text-primary hover:bg-primary-container/30 bg-transparent",
  };
  return (
    <button
      type="button"
      className={`${base} ${sizes[size] || sizes.md} ${variants[variant] || variants.primary} ${fullWidth ? "w-full" : ""} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}
