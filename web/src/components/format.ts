export function formatWatts(watts: number | null): string {
  if (watts === null) return "—";
  return watts >= 1000 ? `${(watts / 1000).toFixed(1)} kW` : `${Math.round(watts)} W`;
}
