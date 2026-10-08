import { useEffect, useState } from 'react';
import { getJSON } from '../api';
import type { Reading } from '../api';
import type { Room } from '../useRoom';

/* Live hardware pieces for the left side: temperature hero, 10-minute graphs, hardware chips, Board B tile.
   Every number shown comes from the board's readings. LED and buzzer are shown as what board A is
   telling board B to do (the same rule the board program uses), not as a measured value. */

export const HOT_C = 37;          // must match HOT_ON_C10 in the board program
export const COOL_C = 36;

type Row = { ts: number; temp_c: number | null; gas_pct: number; hum_pct: number | null; level_mm: number };

export function useHistory(connected: boolean) {
  const [rows, setRows] = useState<Row[]>([]);
  useEffect(() => {
    let alive = true;
    const load = () => getJSON<Row[]>('/api/readings?minutes=10&max_points=150').then((r) => alive && setRows(r)).catch(() => {});
    load();
    const t = setInterval(load, 4000);
    return () => { alive = false; clearInterval(t); };
  }, [connected]);
  return rows;
}

/** hot with the same gap the board uses: on above 37, off below 36 */
export function useHot(r: Reading | null) {
  const [hot, setHot] = useState(false);
  const t = r?.temp_c ?? null;
  useEffect(() => {
    if (t === null) { setHot(false); return; }
    setHot((h) => (h ? t >= COOL_C : t > HOT_C));
  }, [t]);
  return hot;
}

function Dot({ ok }: { ok: boolean | null }) {
  return <span className="live-dot" style={{ color: ok === null ? '#B8B8B8' : ok ? '#7CE0A3' : '#FF5A4F' }} />;
}

export function HardwareChips({ room }: { room: Room }) {
  const r = room.reading;
  const real = room.link.source === 'BOARD';
  const chips: [string, string, boolean | null][] = [
    ['Board A', room.connected ? (real ? `USB ${room.link.port ?? ''}`.trim() : 'pretend') : 'not connected', room.connected],
    ['Board B', !r ? '–' : r.link_ok ? 'radio OK' : 'no reply', r ? r.link_ok : null],
    ['Qwen', room.state?.model?.ready ? 'on this laptop' : 'off', room.state?.model ? !!room.state.model.ready : null],
  ];
  return (
    <div className="absolute left-8 top-6 flex gap-2 rise">
      {chips.map(([name, sub, ok]) => (
        <div key={name} className="flex items-center gap-2 h-8 pl-3 pr-3.5 rounded-[999px] [backdrop-filter:blur(18px)] bg-[#0A0E0C66] border border-solid border-[#FFFFFF40]">
          <Dot ok={ok} />
          <div className="text-[12px] tracking-[0.08em] font-[600] leading-4 text-porcelain uppercase">{name}</div>
          <div className="text-[12px] leading-4 text-[#FFFFFFB3]">{sub}</div>
        </div>
      ))}
    </div>
  );
}

export function TempHero({ r, hot }: { r: Reading | null; hot: boolean }) {
  const t = r?.temp_c ?? null;
  const pct = t === null ? 0 : Math.max(0, Math.min(1, (t - 15) / (45 - 15)));
  const limitPct = (HOT_C - 15) / 30;
  return (
    <div className="absolute left-8 top-19 w-120 flex flex-col gap-3 rise soft-shadow">
      <div className="flex items-center gap-3">
        <div className={`text-[13px] tracking-[0.12em] font-[600] leading-4 ${hot ? 'text-[#FF8A80]' : 'text-porcelain'}`}>
          {hot ? 'HEAT ALARM · FAN, LED AND BUZZER ON' : 'TEMPERATURE'}
        </div>
      </div>
      <div className="flex items-start">
        <div className={`text-[148px] leading-32 tracking-[-0.06em] font-[500] whitespace-nowrap ${hot ? 'text-[#FF6B5E]' : 'text-porcelain'}`}>
          <span key={t ?? 'x'} className="tick">{t === null ? '––' : t.toFixed(1)}</span>
        </div>
        <div className={`text-[44px] leading-14 font-[400] pt-3 ${hot ? 'text-[#FF6B5E]' : 'text-porcelain'}`}>°C</div>
      </div>
      {/* a thermometer bar with the 37 °C mark */}
      <div className="relative w-110 h-2 rounded-[999px] bg-[#FFFFFF33]">
        <div className="absolute left-0 top-0 h-2 rounded-[999px] transition-[width] duration-700"
          style={{ width: `${pct * 100}%`, background: hot ? '#FF5A4F' : 'linear-gradient(90deg,#7CE0A3,#FFD400)' }} />
        <div className="absolute -top-1.5 w-0.5 h-5 bg-porcelain" style={{ left: `${limitPct * 100}%` }} />
        <div className="absolute top-4 text-[12px] font-[600] leading-4 text-porcelain -translate-x-1/2" style={{ left: `${limitPct * 100}%` }}>37 °C</div>
      </div>
    </div>
  );
}

function Spark({ values, limit, color, minSpan = 1 }: { values: number[]; limit?: number; color: string; minSpan?: number }) {
  const W = 200, H = 40;
  if (values.length < 2) return <svg width={W} height={H}><text x="0" y="24" fill="#FFFFFF99" fontSize="12">collecting…</text></svg>;
  let lo = Math.min(...values), hi = Math.max(...values);
  if (limit !== undefined) { lo = Math.min(lo, limit); hi = Math.max(hi, limit); }
  if (hi - lo < minSpan) { const mid = (hi + lo) / 2; hi = mid + minSpan / 2; lo = mid - minSpan / 2; }
  const y = (v: number) => H - 3 - ((v - lo) / (hi - lo)) * (H - 6);
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * W},${y(v).toFixed(1)}`).join(' ');
  const area = `0,${H} ${pts} ${W},${H}`;
  return (
    <svg width={W} height={H} style={{ overflow: 'visible' }}>
      <polygon points={area} fill={color} opacity="0.14" />
      {limit !== undefined && <line x1="0" x2={W} y1={y(limit)} y2={y(limit)} stroke="#FFFFFF" strokeOpacity="0.7" strokeDasharray="3 4" />}
      <polyline points={pts} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={W} cy={y(values[values.length - 1])} r="3.5" fill={color} />
    </svg>
  );
}

export function GraphPanel({ rows, r, hot }: { rows: Row[]; r: Reading | null; hot: boolean }) {
  const temps = rows.map((x) => x.temp_c).filter((v): v is number => v !== null);
  const air = rows.filter((x) => x.gas_pct > 0).map((x) => x.gas_pct - 100);
  const water = rows.map((x) => x.level_mm).filter((v) => v >= 0);
  const lines: [string, string, number[], number | undefined, string, number][] = [
    ['Temperature', r?.temp_c != null ? `${r.temp_c.toFixed(1)} °C` : '–', temps, HOT_C, hot ? '#FF6B5E' : '#FFD400', 4],
    ['Air above normal', r && r.baseline_ok ? `${Math.max(0, r.gas_pct - 100)} %` : 'learning', air, 30, '#7CE0A3', 10],
    ['Water tank', r && r.level_mm >= 0 ? `${r.level_mm} mm` : '–', water, undefined, '#9EC9FF', 40],
  ];
  return (
    <div className="absolute left-142 top-6 w-104 flex flex-col gap-3 pt-4 pb-4 px-5 rounded-[24px] glass-tile rise [backdrop-filter:blur(26px)_saturate(150%)] bg-[#0A0E0C59] border border-solid border-[#FFFFFF52]">
      <div className="flex items-center justify-between">
        <div className="text-[12px] tracking-[0.12em] font-[600] leading-4 text-porcelain">LAST 10 MINUTES</div>
        <div className="text-[12px] leading-4 text-[#FFFFFFA6]">dashed line = limit</div>
      </div>
      {lines.map(([name, now, vals, lim, color, span]) => (
        <div key={name} className="flex items-center justify-between gap-4">
          <div className="flex flex-col w-30 shrink-0">
            <div className="text-[13px] leading-4 text-[#FFFFFFCC]">{name}</div>
            <div className="text-[22px] leading-7 tracking-[-0.02em] font-[500] text-porcelain whitespace-nowrap">{now}</div>
          </div>
          <Spark values={vals} limit={lim} color={color} minSpan={span} />
        </div>
      ))}
    </div>
  );
}

const ATTENTION = ['NEEDS_CLEANING', 'NO_WATER', 'FAULT'];

export function boardBState(r: Reading | null, hot: boolean) {
  const led = !!r && (hot || ATTENTION.includes(r.state) || r.tap_suspected);
  return { fan: r?.fan === 1, led, buzzer: hot, linked: !!r?.link_ok };
}

export function Pill({ on, label, warn }: { on: boolean; label: string; warn?: boolean }) {
  return (
    <div className={`flex items-center gap-1.5 h-6 px-2.5 rounded-[999px] border border-solid transition-colors duration-300 ${on ? (warn ? 'bg-[#FF5A4F] border-[#FF5A4F]' : 'bg-tag border-tag') : 'border-[#FFFFFF66]'}`}>
      <span className={`size-1.5 rounded-[999px] ${on ? 'bg-ink' : 'bg-[#FFFFFF80]'}`} />
      <span className={`text-[12px] font-[600] leading-4 ${on ? 'text-ink' : 'text-porcelain'}`}>{label}</span>
    </div>
  );
}
