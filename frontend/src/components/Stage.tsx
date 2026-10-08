import stageImg from '../assets/washroom_stage.jpg';
import type { Decision, Ev, Job, Reading } from '../api';
import type { Room } from '../useRoom';
import { GraphPanel, HardwareChips, Pill, TempHero, boardBState, useHistory, useHot } from './Live';

const GLASS = 'glass-tile rise flex flex-col justify-between w-53 h-41.5 py-4 px-4.5 rounded-[24px] shrink-0 ' +
  '[backdrop-filter:blur(26px)_saturate(150%)] bg-[#FFFFFF24] border border-solid border-[#FFFFFF61]';
const TILE_NAME = 'text-[15px] font-[500] leading-4.5 text-porcelain';
const TILE_BIG = 'text-[50px] leading-12.5 tracking-[-0.04em] font-[300] text-porcelain whitespace-nowrap';
const TILE_SUB = 'text-[14px] opacity-90 leading-4.5 text-porcelain';

function JobTag({ job, onWhy }: { job: Job; onWhy: (eventId: number) => void }) {
  return (
    <div className="rise absolute left-160 top-70 w-67 flex flex-col pt-4.5 pb-4 rounded-panel gap-5.5 px-5 bg-tag">
      <div className="flex justify-between items-start gap-3">
        <div className="text-[31px] leading-7.5 tracking-[-0.04em] font-[500] text-ink uppercase">
          Job due<br />{job.title}
        </div>
        <div className="w-2.75 h-2.75 shrink-0 rounded-[999px] bg-ink" />
      </div>
      <div className="text-[15px] leading-5 font-[500] text-ink">{job.reason}</div>
      <button type="button" className="flex gap-2.5 w-max" onClick={() => onWhy(job.event_ids[job.event_ids.length - 1])}>
        <div className="text-[12px] tracking-[0.1em] font-[600] leading-4 text-ink">(</div>
        <div className="text-[12px] tracking-[0.1em] font-[600] leading-4 text-ink">WHY THIS JOB</div>
        <div className="text-[12px] tracking-[0.1em] font-[600] leading-4 text-ink">)</div>
      </button>
    </div>
  );
}

function DecisionStrip({ decision }: { decision: Decision }) {
  const checking = decision.status === 'checking';
  const left = decision.seconds_left;
  return (
    <div className="rise absolute left-8 top-73 w-147 flex flex-col pt-3 pb-3 rounded-[24px] gap-2.5 px-4.5 [backdrop-filter:blur(30px)_saturate(150%)] bg-[#0A0E0C80] border border-solid border-[#FFFFFF57]">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="rounded-[999px] shrink-0 bg-tag size-2" />
          <div className="text-[12px] tracking-[0.1em] font-[600] leading-4 text-porcelain">THE BOARD DECIDED THIS BY ITSELF</div>
        </div>
        <div className="text-[13px] opacity-90 leading-4 text-porcelain">{decision.time}, no laptop or internet needed</div>
      </div>
      <div className="flex">
        {decision.steps.map((s, i) => {
          const last = i === decision.steps.length - 1;
          const live = last && checking;
          const pad = i === 0 ? 'pr-3.5' : last ? 'pl-3.5 border-l border-l-solid border-l-[#FFFFFF59]' : 'px-3.5 border-l border-l-solid border-l-[#FFFFFF59]';
          return (
            <div key={s.key} className={`rise flex flex-col grow basis-[0%] min-w-0 gap-1 ${pad}`} style={{ animationDelay: `${0.15 + i * 0.22}s` }}>
              <div className={`text-[12px] tracking-[0.1em] font-[600] leading-4 ${live ? 'text-tag' : 'text-porcelain opacity-85'}`}>
                {i + 1} {s.label.toUpperCase()}
              </div>
              <div className="text-[16px] leading-5 tracking-[-0.01em] font-[500] text-porcelain line-clamp-2" title={s.head}>{s.head}</div>
              {s.sub && (
                <div className="text-[12px] leading-4 opacity-90 text-porcelain line-clamp-1" title={s.sub}>
                  {s.sub}{live && left !== null ? `. ${left} s left` : ''}
                </div>
              )}
              {live && left !== null && (
                <div className="w-29.5 h-0.75 flex rounded-[999px] shrink-0 bg-[#FFFFFF4D]">
                  <div className="h-0.75 rounded-[999px] shrink-0 bg-tag" style={{ width: `${Math.min(100, Math.max(0, ((60 - left) / 60) * 100))}%` }} />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function WaterTile({ r }: { r: Reading | null }) {
  const ok = !!r && r.level_mm >= 0;
  const fill = ok ? Math.min(1, r!.level_mm / 300) : 0;       // the glyph is full at 300 mm
  const top = 35.25 - 28.5 * fill;
  let sub = 'No reading';
  if (ok) {
    sub = 'Steady, no tap left on';
    if (r!.level_rate <= -6) sub = `Falling ${-r!.level_rate} mm a minute`;
    if (r!.tap_suspected) sub = 'A tap may be left on';
  }
  return (
    <div className={GLASS}>
      <div className="flex justify-between items-start">
        <div className={TILE_NAME}>Water tank</div>
        <svg width="34" height="40" viewBox="0 0 34 40" style={{ flexShrink: 0 }}>
          <defs><clipPath id="tank-inside"><rect x="2.75" y="6.75" width="28.5" height="28.5" rx="6.25" /></clipPath></defs>
          <rect x="10" y="1" width="14" height="5" rx="1.5" fill="none" stroke="#FFFFFF" strokeWidth="1.5" />
          <rect x="2" y="6" width="30" height="30" rx="7" fill="none" stroke="#FFFFFF" strokeWidth="1.5" />
          {ok && <rect x="2" y={top} width="30" height={36 - top} fill="#FFFFFF" opacity="0.55" clipPath="url(#tank-inside)" />}
        </svg>
      </div>
      <div className="flex flex-col gap-0.5">
        <div className="flex items-baseline gap-1.5">
          <div className={TILE_BIG}>{ok ? r!.level_mm : '–'}</div>
          {ok && <div className="text-[17px] leading-5.5 text-porcelain">mm</div>}
        </div>
        <div className={TILE_SUB}>{sub}</div>
      </div>
    </div>
  );
}

function HumidityTile({ r }: { r: Reading | null }) {
  const ok = !!r && r.hum_pct !== null;
  return (
    <div className={GLASS}>
      <div className="flex justify-between items-start">
        <div className={TILE_NAME}>Humidity</div>
        <svg width="30" height="40" viewBox="0 0 30 40" style={{ flexShrink: 0 }}>
          <path d="M2 38V15a13 13 0 0 1 26 0V38Z" fill="none" stroke="#FFFFFF" strokeWidth="1.5" strokeLinejoin="round" />
          <path d="M2.75 24c5 3 9-3 13-1s7 3 11.5 0V37.25H2.75Z" fill="#FFFFFF" opacity={r?.steam_gate ? 0.9 : 0.55} />
        </svg>
      </div>
      <div className="flex flex-col gap-0.5">
        <div className="flex items-baseline gap-1">
          <div className={TILE_BIG}>{ok ? Math.round(r!.hum_pct!) : '–'}</div>
          {ok && <div className="text-[17px] leading-5.5 text-porcelain">%</div>}
        </div>
        <div className={TILE_SUB}>{!ok ? 'No reading' : r!.steam_gate ? 'Steam in the room' : 'No steam in the room'}</div>
      </div>
    </div>
  );
}

function FanTile({ r, decision, hot }: { r: Reading | null; decision: Decision | null; hot: boolean }) {
  const b = boardBState(r, hot);
  const on = r?.fan === 1;
  const fanChain = decision && decision.code === 'FAN_ON' ? decision : null;
  const left = fanChain?.status === 'checking' ? fanChain.seconds_left : null;
  let sub = 'No reading';
  if (r) {
    if (r.fan_manual) sub = 'Manual control';
    else if (!on) sub = fanChain?.status === 'failed' ? 'Last check failed' : 'Automatic';
    else if (fanChain?.status === 'checking') sub = 'Checking it worked';
    else if (fanChain?.status === 'passed') sub = 'Check passed';
    else if (fanChain?.status === 'failed') sub = 'Check failed';
    else sub = 'Running';
  }
  const blade = 'M19 19C17 12 21 6.5 27.5 7.5C27 13 23.5 17 19 19Z';
  return (
    <div className={GLASS}>
      <div className="flex justify-between items-start">
        <div className={TILE_NAME}>Board B · fan</div>
        <svg width="38" height="38" viewBox="0 0 38 38" style={{ flexShrink: 0 }}>
          <rect x="1" y="1" width="36" height="36" rx="8" fill="none" stroke="#FFFFFF" strokeWidth="1.5" />
          <g className={on ? 'fan-turning' : undefined}>
            <circle cx="19" cy="19" r="14" fill="none" />
            {[0, 90, 180, 270].map((a) => <path key={a} d={blade} transform={`rotate(${a} 19 19)`} fill="#FFFFFF" />)}
          </g>
        </svg>
      </div>
      <div className="flex flex-col gap-2">
        <div className="flex items-end justify-between">
          <div className={TILE_BIG}>{!r ? '–' : on ? 'On' : 'Off'}</div>
          <div className="flex flex-col gap-1 pb-1">
            <Pill on={b.led} label="LED" />
            <Pill on={b.buzzer} label="Buzzer" warn />
          </div>
        </div>
        <div className="flex flex-col gap-1.5">
          <div className="w-44 h-0.75 flex rounded-[999px] shrink-0" style={{ background: left !== null ? '#FFFFFF4D' : 'transparent' }}>
            {left !== null && <div className="h-0.75 rounded-[999px] shrink-0 bg-tag" style={{ width: `${Math.min(100, Math.max(0, ((60 - left) / 60) * 100))}%` }} />}
          </div>
          <div className={TILE_SUB}>{sub}</div>
        </div>
      </div>
    </div>
  );
}

function AirTile({ r }: { r: Reading | null }) {
  const learning = !!r && !r.baseline_ok;
  const above = r && r.baseline_ok ? Math.max(0, r.gas_pct - 100) : null;
  const bad = !!r?.air_bad;
  const haze = above === null ? 0.15 : Math.min(0.9, 0.15 + above / 80);
  return (
    <div className={GLASS + (bad ? ' !border-[#FF8A80]' : '')}>
      <div className="flex justify-between items-start">
        <div className={TILE_NAME}>Air (MQ-135)</div>
        <svg width="40" height="40" viewBox="0 0 40 40" style={{ flexShrink: 0 }}>
          <circle cx="20" cy="20" r="18" fill="none" stroke="#FFFFFF" strokeWidth="1.5" />
          {[0, 1, 2].map((k) => (
            <path key={k} d={`M9 ${14 + k * 6}c3-3 6 3 9 0s6-3 9 0 4 2 4 2`} fill="none" stroke="#FFFFFF" strokeWidth="1.5" strokeLinecap="round" opacity={haze} />
          ))}
        </svg>
      </div>
      <div className="flex flex-col gap-0.5">
        <div className="flex items-baseline gap-1">
          <div className={TILE_BIG}>{above === null ? '–' : `+${above}`}</div>
          {above !== null && <div className="text-[17px] leading-5.5 text-porcelain">%</div>}
        </div>
        <div className={TILE_SUB}>{!r ? 'No reading' : learning ? 'Learning normal air' : bad ? 'The air changed' : 'Normal air'}</div>
      </div>
    </div>
  );
}

function Star() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" style={{ flexShrink: 0 }}>
      <path d="M7 0v14M0 7h14M2 2l10 10M12 2L2 12" stroke="#FFD400" strokeWidth="1.6" />
    </svg>
  );
}

function EventStrip({ room, events }: { room: Room; events: Ev[] }) {
  const { serverUp, connected, link } = room;
  let label = 'BOARD NOT CONNECTED';
  let tone = 'text-alarm';
  if (!serverUp) label = 'LAPTOP PROGRAM NOT RUNNING';
  else if (connected && link.source === 'SIMULATED') { label = 'PRETEND BOARD, SAMPLE DATA'; tone = 'text-tag'; }
  else if (connected && link.source === 'BOARD') { label = `LIVE FROM THE BOARD ON ${link.port ?? ''}`.trim(); tone = 'text-tag'; }
  else if (connected) { label = 'CONNECTED, WAITING FOR THE BOARD TO SAY HELLO'; tone = 'text-tag'; }
  const recent = events.slice(-4);
  return (
    <div className="absolute left-0 top-160 w-250 h-11 flex items-center px-8 gap-4.5 bg-ink overflow-hidden">
      <div className={`flex items-center gap-2.5 shrink-0 ${tone}`}>
        {connected && <span className="live-dot" />}
        <div className="text-[13px] tracking-[0.08em] w-max font-[500] leading-4">{label}</div>
      </div>
      {recent.map((e) => (
        <div key={e.id} className="flex items-center gap-4.5 shrink-0">
          <Star />
          <div className="text-[13px] tracking-[0.08em] w-max whitespace-pre font-[500] leading-4 text-porcelain">
            {e.time.slice(0, 5)}{'  '}{e.title.toUpperCase()}
          </div>
        </div>
      ))}
    </div>
  );
}

export function Stage({ room, onWhy }: { room: Room; onWhy: (eventId: number) => void }) {
  const { reading, jobs, events } = room;
  const hot = useHot(reading);
  const rows = useHistory(room.connected);
  const decision = room.connected ? room.decision : null;    // a frozen countdown would mislead
  return (
    <div className={`grow basis-[0%] min-h-0 overflow-clip relative bg-[#3B4442] bg-cover bg-position-[50%] ${hot ? 'alarm-glow' : ''}`} style={{ backgroundImage: `url(${stageImg})` }}>
      <div className="stage-shade" />
      {room.connected && jobs[0] && <JobTag job={jobs[0]} onWhy={onWhy} />}
      <HardwareChips room={room} />
      <TempHero r={reading} hot={hot} />
      <GraphPanel rows={rows} r={reading} hot={hot} />
      {decision && <DecisionStrip decision={decision} />}
      <div className="tiles absolute left-8 top-111.5 flex gap-3">
        <WaterTile r={reading} />
        <HumidityTile r={reading} />
        <AirTile r={reading} />
        <FanTile r={reading} decision={decision} hot={hot} />
      </div>
      <EventStrip room={room} events={events} />
    </div>
  );
}
