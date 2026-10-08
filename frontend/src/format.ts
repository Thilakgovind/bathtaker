export const STATE_WORDS: Record<string, string> = {
  FREE: 'Free', IN_USE: 'In use', VENTILATING: 'Clearing the air',
  NEEDS_CLEANING: 'Needs cleaning', NO_WATER: 'No water', FAULT: 'Fault',
};

/** "4 min", "1 h 12 min", "under a minute" */
export function ago(seconds: number): string {
  const m = Math.max(0, Math.floor(seconds / 60));
  if (m < 1) return 'under a minute';
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h ${m % 60} min`;
}

/** "the last 2 hours", "the last 14 minutes" */
export function span(seconds: number): string {
  const m = Math.max(1, Math.round(seconds / 60));
  if (m < 90) return `the last ${m} ${m === 1 ? 'minute' : 'minutes'}`;
  const h = Math.round(m / 60);
  return `the last ${h} hours`;
}

export const two = (n: number) => String(n).padStart(2, '0');
