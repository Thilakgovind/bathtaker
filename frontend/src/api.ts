// The shapes the laptop program sends. docs/API.md is the description; backend/app/main.py is the code.

export type Reading = {
  state: string; door: number; level_mm: number; level_rate: number; gas_pct: number;
  hum_pct: number | null; temp_c: number | null; fan: number; uses: number;
  steam_gate: boolean; baseline_ok: boolean; link_ok: boolean; fan_manual: boolean;
  tap_suspected: boolean; air_bad: boolean; ts: number; time: string; source: string;
};
export type Link = {
  connected: boolean; port: string | null; source: 'BOARD' | 'SIMULATED' | 'UNKNOWN';
  hello: { firmware: string } | null; silent_for_s: number | null; error: string;
};
export type Stamp = { ts: number; time: string };
export type Model = { model: string; ready: boolean; detail: string };
export type RoomState = {
  link: Link; stale: boolean; reading: Reading | null; state_word: string | null;
  headline_reason: string | null; jobs_open: number; last_cleaned: Stamp | null;
  last_use_ended: Stamp | null; model: Model; rules_count: number; now: number;
};
export type Job = {
  key: string; title: string; priority: number; reason: string; since: number; since_time: string;
  event_ids: number[]; closes_with: string; can_mark_done: boolean; code: string;
};
export type Step = { key: string; label: string; head: string; sub: string };
export type Decision = {
  event_id: number; time: string; code: string; status: 'checking' | 'passed' | 'failed' | 'done' | 'open';
  seconds_left: number | null; steps: Step[]; event_ids: number[];
};
export type Ev = { id: number; ts: number; time: string; code: string; a: number; b: number; title: string; source: string };
export type Rule = {
  name: string; trigger: { type: string; event?: string }; when: { sensor: string; is: string; value: number }[];
  match: string; hold_seconds: number; action: { type: string; set?: string; text?: string };
  for_seconds: number; priority: number;
};
export type Parts = { when: string; do: string; for: string | null; hold: string | null; sentence: string; kind: 'fan' | 'job' };
export type Replay = { count: number; fan_seconds: number; fired: number[]; from: number | null; to: number | null; sources: string[] };
export type Draft = {
  kind?: string; sentence: string; rule: Rule | null; by: 'pattern' | 'model' | 'none'; problems: string[]; notes: string[];
  parts: Parts | null; slot?: number | null; line?: string; replay?: Replay; ms: number;
};
export type Notice = { id: string; text: string; sentence: string | null; rule: Rule | null; event_ids: number[] };
export type UploadSteps = { drafted: boolean; approved: boolean; sent: boolean; board_ok: boolean };
export type Upload = { ok: boolean; steps: UploadSteps; detail: string; slot?: number };
export type Answer =
  | (Draft & { kind: 'rule' })
  | { kind: 'why'; answer: string; by: string; chain: Decision | null; event_ids: number[] }
  | { kind: 'report'; text: string; by: string }
  | { kind: 'status'; text: string; by: string; jobs: Job[] };

export async function getJSON<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(await problem(r));
  return r.json();
}

export async function send<T>(url: string, body?: unknown, method = 'POST'): Promise<T> {
  const r = await fetch(url, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await problem(r));
  return r.json();
}

async function problem(r: Response): Promise<string> {
  try {
    const d = await r.json();
    return typeof d.detail === 'string' ? d.detail : 'The laptop program refused that.';
  } catch {
    return 'The laptop program did not answer.';
  }
}
