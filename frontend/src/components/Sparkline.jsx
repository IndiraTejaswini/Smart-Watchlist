export default function Sparkline({ value = 0, className = "" }) {
  const points = value >= 0 ? "1,16 12,14 24,15 36,9 48,11 59,3" : "1,3 12,5 24,4 36,10 48,8 59,16";
  return (
    <svg aria-hidden="true" width="60" height="18" viewBox="0 0 60 18" className={className}>
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

