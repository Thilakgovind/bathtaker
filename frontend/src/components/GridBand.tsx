import { useState } from 'react';
import { send } from '../api';
import { STATE_WORDS, ago } from '../format';
import type { Room } from '../useRoom';
import { useHot } from './Live';

const ROOM_NAME = 'WASHROOM 01';

function Bracket({ children, size = 13 }: { children: string; size?: number }) {
  const cls = `tracking-[0.08em] font-[500] leading-4 text-ink`;
  return (
    <div className="flex gap-2.5" style={{ fontSize: size }}>
      <div className={cls}>(</div>
      <div className={cls}>{children}</div>
      <div className={cls}>)</div>
    </div>
  );
}

export function GridBand({ room }: { room: Room }) {
  const { connected, reading, state, events, now } = room;
  const [sent, setSent] = useState<string | null>(null);

  const hot = useHot(reading);
  const headline = !connected
    ? 'NOT CONNECTED'
    : !reading
      ? 'WAITING FOR THE BOARD'
      : hot
        ? 'TOO HOT'
        : (STATE_WORDS[reading.state] ?? reading.state).toUpperCase();
  const headSize = headline.length > 16 ? 46 : 58;

  const markCleaned = async () => {
    try {
      await send('/api/command', { cmd: 'CLEANED' });
      setSent('SENT TO THE BOARD');
      room.refreshAll();
    } catch (e) {
      setSent((e as Error).message.toUpperCase());
    }
    setTimeout(() => setSent(null), 3000);
  };

  // the big number: how far the air is above this room's normal
  const learning = !!reading && !reading.baseline_ok;
  const above = reading && reading.baseline_ok ? Math.max(0, reading.gas_pct - 100) : null;
  const lastAirBad = [...events].reverse().find((e) => e.code === 'AIR_BAD');
  let under = 'NO READING';
  if (reading) {
    if (learning) under = "LEARNING THIS ROOM'S NORMAL AIR";
    else if (reading.air_bad) {
      const secs = lastAirBad ? now - lastAirBad.ts : null;
      const when = secs === null ? 'CHANGED' : secs < 60 ? 'CHANGED JUST NOW' : `CHANGED ${ago(secs).toUpperCase()} AGO`;
      under = `${when}, ${reading.steam_gate ? 'STEAM' : 'NO STEAM'}`;
    } else under = reading.steam_gate ? 'NORMAL, STEAM IN THE ROOM' : 'NORMAL';
  }

  const jobsOpen = state?.jobs_open ?? room.jobs.length;

  return (
    <div className="flex h-54 shrink-0 border-b border-b-solid border-b-ink bg-porcelain">
      <div className="flex flex-col justify-between w-175 shrink-0 pt-6.5 pb-6 px-8 border-r border-r-solid border-r-ink">
        <div className="flex flex-col">
          <div className={`tracking-[-0.045em] font-[500] whitespace-nowrap ${hot ? 'text-[#E5372B]' : 'text-ink'}`} style={{ fontSize: headSize, lineHeight: '54px' }}>
            <span key={headline} className="tick">{headline}</span>
          </div>
          <div className="text-[58px] leading-13.5 tracking-[-0.045em] font-[500] text-quiet">{ROOM_NAME}</div>
        </div>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-6.5">
            <Bracket>ROOM</Bracket>
            <div className="flex items-center gap-2">
              <div className="text-[13px] tracking-[0.08em] font-[500] leading-4 text-ink">JOBS</div>
              <div className={`py-px px-2 rounded-[999px] ${jobsOpen ? 'bg-tag' : 'bg-[#EEEEEE]'}`}>
                <div className="text-[13px] font-[500] leading-4 text-ink">{jobsOpen}</div>
              </div>
            </div>
            <div className="text-[13px] tracking-[0.08em] font-[500] leading-4 text-ink">RULES</div>
            <div className="text-[13px] font-[500] leading-4 text-ink">
              <span className="py-px px-2 rounded-[999px] bg-[#EEEEEE]">{state?.rules_count ?? 0}</span>
            </div>
          </div>
          <button
            type="button"
            onClick={markCleaned}
            disabled={!connected}
            className={`flex items-center pr-4 pl-5 rounded-[999px] gap-3.5 py-2.75 ${connected ? 'bg-ink' : 'bg-quiet'}`}
          >
            <div className="text-[13px] tracking-[0.08em] font-[500] leading-4 text-porcelain whitespace-nowrap">
              {sent ?? 'MARK AS CLEANED'}
            </div>
            <svg width="16" height="16" viewBox="0 0 16 16" style={{ flexShrink: 0 }}>
              <path d="M3 8.5l3.2 3.2L13 4.5" fill="none" stroke="#FFFFFF" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </div>
      </div>

      <div className="flex flex-col justify-between w-75 shrink-0 pt-5.5 pb-6 px-7">
        <Bracket size={12}>AIR ABOVE NORMAL</Bracket>
        <div className="flex flex-col items-center gap-1.5">
          <div className="flex items-start">
            {learning
              ? <div className="h-24 flex items-center"><div className="learning-bar" /></div>
              : <div className="text-[112px] leading-24 tracking-[-0.05em] text-ink"><span key={above ?? 'x'} className="tick">{above === null ? '–' : above}</span></div>}
            {above !== null && <div className="text-[30px] leading-9 text-ink">%</div>}
          </div>
          {above !== null && <div className="h-2.25 shrink-0 bg-ink transition-[width] duration-700" style={{ width: Math.min(74 + above * 1.2, 230) }} />}
        </div>
        <div className="text-[13px] tracking-[0.02em] font-[600] leading-4 text-ink whitespace-nowrap">{under}</div>
      </div>
    </div>
  );
}
