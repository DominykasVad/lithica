/** The Sardonyx mark: a banded stone, in the app's own colours. */
export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden className={className}>
      <ellipse cx="16" cy="16" rx="14" ry="12" className="fill-primary" />
      <path
        d="M3.5 12.5c4 2.2 9 2.6 13.5 1.2s8.8-1.4 11.6.6"
        fill="none"
        className="stroke-primary-foreground"
        strokeWidth="2.4"
        strokeLinecap="round"
      />
      <path
        d="M2.6 18.2c4.4 1.7 9.4 1.5 13.8-.2s8.6-1.8 12.8.4"
        fill="none"
        className="stroke-primary-foreground"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
      <path
        d="M6 23.4c3.4.9 7.2.4 10.4-.8s6.6-1.2 9.4.2"
        fill="none"
        className="stroke-primary-foreground/60"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
    </svg>
  );
}
