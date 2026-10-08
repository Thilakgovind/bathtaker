import { useState } from 'react';
import heroImg from '../assets/caretaker_hero.jpg';
import blueImg from '../assets/agent_blue.jpg';
import { getJSON, send } from '../api';
import type { Answer, Decision, Draft, Notice, Upload, UploadSteps } from '../api';
import { span, two } from '../format';
import type { Room } from '../useRoom';

const PROJECT_SMALL = 'WASHROOM';
const PROJECT_BIG = 'CARETAKER';
const EXAMPLES = [
  'Run the fan for 30 seconds after every use',
  'Tell me when the water level is below 60',
  'Ask for cleaning after 4 uses',
];
const QUICK = ['Why did the fan run?', 'Shift report', 'What needs me?'];
const BY: Record<string, string> = {
  pattern: 'Written by fixed patterns, no model',
  model: 'Written by Qwen on this laptop',
  template: 'Built from the event log, no model',
  none: 'No rule was written',
};

function Arrow({ dark = false, up = false }: { dark?: boolean; up?: boolean }) {
  return (
    <div className={`flex items-center justify-center rounded-[7px] shrink-0 size-7.5 ${dark ? 'bg-porcelain' : 'bg-ink'}`}>
      {up ? (
        <svg width="15" height="15" viewBox="0 0 16 16"><path d="M8 13V3M3.5 7.5L8 3l4.5 4.5" fill="none" stroke={dark ? '#000' : '#FFF'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
      ) : (
        <svg width="12" height="12" viewBox="0 0 12 12"><path d="M4 2l4 4-4 4" fill="none" stroke={dark ? '#000' : '#FFF'} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ the top: photo, headline, what it noticed */

function Hero({ room, notice, onDraft, onShow, onDismiss }: {
  room: Room; notice: Notice | null; onDraft: (n: Notice) => void; onShow: (n: Notice) => void; onDismiss: (n: Notice) => void;
}) {
  const model = room.state?.model;
  const line = !room.serverUp
    ? 'The laptop program is not running, so I cannot see the room.'
    : !room.connected
      ? 'The board is not connected, so I cannot see the room.'
      : room.reading?.temp_c != null && room.reading.temp_c > 37
        ? `It is ${room.reading.temp_c.toFixed(1)} °C, above the 37 °C line. The board switched on the fan, LED and buzzer.`
        : notice ? notice.text : 'Nothing unusual in the last 24 hours.';
  return (
    <div className="h-84.5 shrink-0 flex flex-col justify-between overflow-clip bg-[#2B3331] bg-cover bg-position-[50%_top]" style={{ backgroundImage: `url(${heroImg})` }}>
      <div className="hero-top flex items-center justify-between pt-4 pb-3.5 px-5 border-b border-b-solid border-b-[#FFFFFF59]">
        <div className="flex items-center gap-2.5">
          <svg width="20" height="20" viewBox="0 0 20 20" style={{ flexShrink: 0 }}>
            <path d="M10 1.5c3.2 3.4 5.5 6.3 5.5 9.3a5.5 5.5 0 0 1-11 0c0-3 2.3-5.9 5.5-9.3Z" fill="none" stroke="#FFFFFF" strokeWidth="1.6" strokeLinejoin="round" />
            <path d="M7.2 11.2a2.8 2.8 0 0 0 2.8 2.8" fill="none" stroke="#FFFFFF" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
          <div className="text-[16px] tracking-[-0.01em] font-[500] leading-5 text-porcelain">Caretaker agent</div>
        </div>
        <div className="flex items-center gap-2" title={model?.detail}>
          <span className="live-dot" style={{ color: model?.ready ? '#7CE0A3' : '#FFD400' }} />
          <div className="text-[13px] font-[500] leading-4 text-porcelain">
            {model?.ready ? 'Qwen ready, no internet needed' : 'Model off: fixed patterns only'}
          </div>
        </div>
      </div>
      <div className="flex flex-col pt-14 pb-4.5 gap-2.5 px-5" style={{ backgroundImage: 'linear-gradient(180deg, rgba(0,0,0,0) 0%, rgba(0,0,0,0.72) 55%)' }}>
        <div className="rise font-serif text-[40px] leading-9.5 tracking-[-0.01em] font-[500] text-porcelain">
          I watch the room.<br />You make the call.
        </div>
        <div className="text-[14px] leading-5 max-w-95 text-porcelain">{line}</div>
        {notice && room.connected && (
          <div className="flex items-center pt-0.5 gap-4">
            {notice.rule && (
              <button type="button" onClick={() => onDraft(notice)} className="flex items-center pr-1.25 pl-3.5 rounded-[10px] gap-3 py-1.25 bg-porcelain">
                <div className="text-[14px] font-[500] leading-4.5 text-ink">Draft that rule</div>
                <Arrow />
              </button>
            )}
            <button type="button" onClick={() => onShow(notice)} className="text-[14px] font-[500] leading-4.5 underline underline-offset-2 text-porcelain">
              Show me the last time
            </button>
            <button type="button" onClick={() => onDismiss(notice)} className="text-[14px] font-[500] leading-4.5 text-porcelain opacity-80">
              Not now
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ the rule as an ID badge */

function Glyph({ kind }: { kind: 'fan' | 'job' }) {
  if (kind === 'job') {
    return (
      <svg width="100%" height="100%" viewBox="0 0 54 54">
        <rect x="9" y="8" width="36" height="42" rx="5" fill="#000" />
        <rect x="19" y="3" width="16" height="10" rx="3" fill="#000" stroke="#FFF" strokeWidth="2" />
        <path d="M17 24h20M17 32h20M17 40h12" stroke="#FFF" strokeWidth="3" strokeLinecap="round" />
      </svg>
    );
  }
  const blade = 'M27 27C23 14 31 3 43.5 5C42.5 15.5 35.5 23 27 27Z';
  return (
    <svg width="100%" height="100%" viewBox="0 0 54 54">
      {[0, 90, 180, 270].map((a) => <path key={a} d={blade} transform={`rotate(${a} 27 27)`} fill="#000" />)}
    </svg>
  );
}

function Chip({ children, small = false }: { children: string; small?: boolean }) {
  return (
    <div className="py-px px-2 rounded-[7px] bg-[#E9EBFF] min-w-0">
      <div className={`font-[600] text-cobalt ${small ? 'text-[13px] leading-4.5' : 'text-[14px] leading-5.5'}`}>{children}</div>
    </div>
  );
}

function Badge({ draft }: { draft: Draft }) {
  const rule = draft.rule!;
  const parts = draft.parts!;
  const rp = draft.replay;
  const W = 172;
  const bars = rp && rp.from !== null && rp.to !== null && rp.to > rp.from
    ? rp.fired.map((t) => 4 + ((t - rp.from!) / (rp.to! - rp.from!)) * (W - 8))
    : [];
  let caption = 'No history yet to test it on';
  if (rp && rp.from !== null && rp.to !== null) {
    const over = span(rp.to - rp.from);
    caption = rp.count > 0 ? `Tested: ${rp.count} ${rp.count === 1 ? 'run' : 'runs'} in ${over}` : `Tested: no runs in ${over}`;
    if (rp.sources.includes('SIMULATED')) caption += ', sample data';
  }
  const long = parts.when.length + parts.do.length + (parts.hold ? 8 : 0) > 30;
  const nameSize = rule.name.length <= 14 ? 30 : rule.name.length <= 22 ? 22 : 18;
  const word = `leading-5 text-ink ${long ? 'text-[13px]' : 'text-[14px]'}`;
  const doText = parts.kind === 'job' ? (rule.action.text ?? '') : parts.do;
  return (
    <div className="w-51 h-72.5 overflow-hidden shrink-0 flex flex-col justify-between gap-2 pt-3 pb-3.5 rounded-[16px] px-4 [box-shadow:#00002859_0px_16px_30px] bg-porcelain origin-center" style={{ rotate: '-2.5deg' }}>
      <div className="self-center w-11.5 h-2.25 rounded-[999px] shrink-0 bg-cobalt" />
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between">
          <div style={{ width: long ? 34 : 54, height: long ? 34 : 54 }} className="shrink-0"><Glyph kind={parts.kind} /></div>
          <div className="flex gap-1.5">
            <div className="text-[12px] tracking-[0.1em] font-[500] leading-4 text-ink">(</div>
            <div className="text-[12px] tracking-[0.1em] font-[500] leading-4 text-ink">RULE {two(draft.slot ?? 0)}</div>
            <div className="text-[12px] tracking-[0.1em] font-[500] leading-4 text-ink">)</div>
          </div>
        </div>
        <div className="font-serif tracking-[-0.01em] font-[600] text-ink" style={{ fontSize: nameSize, lineHeight: `${nameSize}px` }}>{rule.name}</div>
      </div>
      <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
        <div className={word}>When</div>
        <Chip small={long}>{parts.when}</Chip>
        {parts.hold && <><div className={word}>for</div><Chip small={long}>{parts.hold}</Chip></>}
        <div className={word}>{parts.kind === 'fan' ? 'turn' : 'raise job'}</div>
        <Chip small={long}>{doText}</Chip>
        {parts.for && <><div className={word}>for</div><Chip small={long}>{parts.for}</Chip></>}
      </div>
      <div className="flex flex-col pt-2.5 gap-1.25 border-t border-t-solid border-t-ink">
        <svg width={W} height="20" viewBox={`0 0 ${W} 20`} style={{ flexShrink: 0 }}>
          <path d={`M0 10H${W}`} stroke="#000000" />
          {bars.map((x, i) => <path key={i} d={`M${x.toFixed(1)} 2v16`} stroke="#1B2CFF" strokeWidth="4" strokeLinecap="round" />)}
        </svg>
        <div className="text-[12px] leading-4 font-[500] text-ink">{caption}</div>
      </div>
    </div>
  );
}

function StepsList({ steps }: { steps: UploadSteps | null }) {
  const rows: [string, boolean][] = [
    ['Drafted', true],
    ['Approved by you', !!steps?.approved],
    ['Sent to the board', !!steps?.sent],
    ['Board said OK', !!steps?.board_ok],
  ];
  return (
    <div className="flex flex-col pt-3 border-t border-t-solid border-t-[#FFFFFF80]">
      {rows.map(([name, done]) => (
        <div key={name} className={`flex items-center h-6.5 gap-2.5 shrink-0 ${done ? '' : 'opacity-75'}`}>
          <div className={`w-2.75 h-2.75 rounded-[999px] shrink-0 ${done ? 'bg-tag' : '[border-width:1.5px] border-solid border-porcelain'}`} />
          <div className="text-[14px] font-[500] leading-4.5 text-porcelain">{name}</div>
        </div>
      ))}
    </div>
  );
}

function Bubble({ children }: { children: string }) {
  return (
    <div className="[align-self:end] max-w-full py-2.5 px-3.5 rounded-tl-[16px] rounded-tr-[16px] rounded-br-[4px] rounded-bl-[16px] bg-ink" title={children}>
      <div className="text-[15px] leading-5 font-[500] text-porcelain line-clamp-3">{children}</div>
    </div>
  );
}

function Card({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-col gap-2.5 rounded-[16px] p-4 bg-porcelain text-ink overflow-y-auto min-h-0">{children}</div>;
}

function ByLine({ by }: { by: string }) {
  return <div className="text-[12px] tracking-[0.06em] font-[600] leading-4 text-[#555555] uppercase">{BY[by] ?? by}</div>;
}

function ChainRows({ chain }: { chain: Decision }) {
  return (
    <div className="flex flex-col border-t border-t-solid border-t-ink pt-2.5 gap-2">
      {chain.steps.map((s, i) => (
        <div key={s.key} className="flex gap-2.5 text-[13px] leading-4.5">
          <div className="w-23 shrink-0 font-[600] tracking-[0.06em] uppercase whitespace-nowrap">{i + 1} {s.label}</div>
          <div className="min-w-0"><span className="font-[600]">{s.head}</span>{s.sub ? `${/[?.!]$/.test(s.head) ? '' : '.'} ${s.sub}` : ''}</div>
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ the whole right side */

export function AgentSide({ room, agent }: { room: Room; agent: Agent }) {
  const { answer, sentence, busy, error, upload, input } = agent;
  const notice = room.notices[0] ?? null;
  const draft = answer?.kind === 'rule' ? answer : null;
  const goodDraft = draft && draft.rule && draft.problems.length === 0 ? draft : null;
  const saved = !!upload?.ok;

  return (
    <div className="absolute left-250 top-0 w-110 h-225 flex flex-col bg-ink">
      <Hero
        room={room}
        notice={notice}
        onDraft={(n) => n.sentence && agent.draft(n.sentence)}
        onShow={(n) => agent.why(n.event_ids[n.event_ids.length - 1])}
        onDismiss={(n) => { send(`/api/notices/${encodeURIComponent(n.id)}/dismiss`).then(room.refreshAll).catch(() => {}); }}
      />
      <div className="grow basis-[0%] min-h-0 flex flex-col overflow-clip gap-2.25 py-3.5 relative px-4 bg-cobalt bg-cover bg-position-[50%_top]" style={{ backgroundImage: `url(${blueImg})` }}>
        <div className="flex flex-col shrink-0">
          <div className="pl-1"><div className="text-[12px] tracking-[0.42em] font-[600] leading-4 text-porcelain">{PROJECT_SMALL}</div></div>
          <div className="text-[70px] leading-15 tracking-[-0.05em] font-[800] italic text-porcelain">{PROJECT_BIG}</div>
        </div>

        <div className="grow basis-[0%] min-h-0 flex flex-col gap-2.25 relative z-10">
          {busy && (
            <>
              {sentence && <Bubble>{sentence}</Bubble>}
              <div className="text-[15px] leading-5 font-[500] text-porcelain">
                Working on it. {room.state?.model.ready ? 'If Qwen is needed, this can take up to 45 seconds on this laptop.' : ''}
              </div>
            </>
          )}

          {!busy && error && (
            <>
              {sentence && <Bubble>{sentence}</Bubble>}
              <Card><div className="text-[15px] leading-5.5 font-[500]">{error}</div></Card>
            </>
          )}

          {!busy && !error && !answer && (
            <div className="flex flex-col gap-2.5 pt-2">
              <div className="text-[15px] leading-5.5 font-[500] text-porcelain max-w-90">
                Tell me a rule in plain words, or ask why something happened. Nothing reaches the board until you approve it.
              </div>
              {EXAMPLES.map((t) => (
                <button key={t} type="button" onClick={() => agent.ask(t)} className="w-max max-w-full text-[14px] leading-5 font-[500] text-porcelain underline underline-offset-2">
                  {t}
                </button>
              ))}
            </div>
          )}

          {!busy && !error && goodDraft && (
            <>
              <div className="flex items-start pt-1.5 gap-4.5">
                <Badge draft={goodDraft} />
                <div className="flex flex-col grow basis-[0%] min-w-0 gap-2.5">
                  <Bubble>{goodDraft.sentence}</Bubble>
                  <div className="flex items-start gap-2">
                    <svg width="18" height="18" viewBox="0 0 18 18" style={{ flexShrink: 0 }}>
                      <circle cx="9" cy="9" r="9" fill="#FFFFFF" />
                      <path d="M5 9.4l2.6 2.6L13 6.4" fill="none" stroke="#1B2CFF" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                    <div className="text-[14px] leading-4.75 text-porcelain">
                      {saved
                        ? `The board now holds ${room.state?.rules_count ?? 1} ${(room.state?.rules_count ?? 1) === 1 ? 'rule' : 'rules'}`
                        : agent.others === 0 ? 'Passed the checks. No other rules on the board'
                          : `No clash with your ${agent.others} other ${agent.others === 1 ? 'rule' : 'rules'}`}
                    </div>
                  </div>
                  {goodDraft.notes.map((n) => <div key={n} className="text-[13px] leading-4.5 text-tag">{n}</div>)}
                  <StepsList steps={upload?.steps ?? null} />
                  <div className="text-[12px] tracking-[0.06em] font-[600] leading-4 text-porcelain opacity-85 uppercase">{BY[goodDraft.by]}</div>
                </div>
              </div>
              {upload && !upload.ok && <div className="text-[14px] leading-5 font-[500] text-tag">{upload.detail}</div>}
              <div className="flex items-center mt-auto gap-2 shrink-0">
                <button type="button" disabled={saved || !room.connected} onClick={agent.approve} className={`grow basis-[0%] flex items-center justify-between pr-1.25 pl-3.5 rounded-[10px] py-1.25 bg-porcelain ${saved || !room.connected ? 'opacity-70' : ''}`}>
                  <div className="text-[14px] w-max font-[600] leading-4.5 text-ink">
                    {saved ? `Saved on the board, rule ${upload!.slot}` : room.connected ? 'Approve and send to board' : 'Board not connected'}
                  </div>
                  <Arrow />
                </button>
                <button type="button" onClick={agent.change} className="py-2.25 px-3.5 rounded-[10px] border border-solid border-porcelain">
                  <div className="text-[14px] w-max font-[600] leading-4.5 text-porcelain">{saved ? 'New rule' : 'Change it'}</div>
                </button>
              </div>
            </>
          )}

          {!busy && !error && draft && !goodDraft && (
            <>
              <Bubble>{draft.sentence}</Bubble>
              <Card>
                <div className="font-serif text-[26px] leading-7 font-[600]">I cannot make that a rule</div>
                {draft.problems.map((p) => <div key={p} className="text-[15px] leading-5.5">{p}</div>)}
                <ByLine by={draft.by} />
              </Card>
              <button type="button" onClick={agent.change} className="w-max py-2.25 px-3.5 rounded-[10px] border border-solid border-porcelain">
                <div className="text-[14px] font-[600] leading-4.5 text-porcelain">Change it</div>
              </button>
            </>
          )}

          {!busy && !error && answer && answer.kind !== 'rule' && (
            <>
              {sentence && <Bubble>{sentence}</Bubble>}
              <Card>
                {answer.kind === 'why' && answer.chain ? (
                  <>
                    <div className="font-serif text-[26px] leading-7 font-[600]">Why, at {answer.chain.time}</div>
                    {answer.by === 'model' && <div className="text-[15px] leading-5.5">{answer.answer}</div>}
                    <ChainRows chain={answer.chain} />
                  </>
                ) : (
                  <div className="text-[15px] leading-5.5">{answer.kind === 'why' ? answer.answer : answer.text}</div>
                )}
                <ByLine by={answer.by} />
              </Card>
            </>
          )}
        </div>

        <div className="flex flex-col gap-2 shrink-0">
          <div className="flex gap-2">
            {QUICK.map((q) => (
              <button key={q} type="button" disabled={busy} onClick={() => agent.ask(q)} className="py-1.5 px-3 rounded-[999px] border border-solid border-[#FFFFFF99]">
                <div className="text-[13px] w-max font-[500] leading-4 text-porcelain">{q}</div>
              </button>
            ))}
          </div>
          <form
            className="flex items-center justify-between pr-1.5 pl-4 rounded-[12px] gap-3 py-1.5 bg-porcelain"
            onSubmit={(e) => { e.preventDefault(); if (input.trim() && !busy) agent.ask(input.trim()); }}
          >
            <input
              value={input}
              onChange={(e) => agent.setInput(e.target.value)}
              placeholder="Tell me a rule, or ask why something happened"
              aria-label="Tell the agent a rule, or ask why something happened"
              className="grow min-w-0 text-[15px] leading-4.5 text-ink placeholder:text-[#555555] bg-transparent outline-none border-0"
            />
            <button type="submit" disabled={busy || !input.trim()} aria-label="Send">
              <div className="flex items-center justify-center w-8.5 h-8.5 shrink-0 rounded-[8px] bg-ink">
                <svg width="15" height="15" viewBox="0 0 16 16"><path d="M8 13V3M3.5 7.5L8 3l4.5 4.5" fill="none" stroke="#FFFFFF" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
              </div>
            </button>
          </form>
        </div>

        {goodDraft && !busy && !error && (
          <div className="absolute left-25 top-0 w-9 h-31 flex flex-col items-center z-20 pointer-events-none">
            <div className="w-5.5 h-26 shrink-0 bg-tag" />
            <div className="w-9 h-5 rounded-[5px] shrink-0 bg-ink" />
          </div>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ what the agent side remembers */

export function useAgent(room: Room) {
  const [input, setInput] = useState('');
  const [sentence, setSentence] = useState('');
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [upload, setUpload] = useState<Upload | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [others, setOthers] = useState(0);              // rules on the board when the draft was made

  const run = async (said: string, job: () => Promise<Answer>) => {
    setSentence(said); setInput(''); setBusy(true); setError(null); setUpload(null);
    setOthers(room.state?.rules_count ?? 0);
    try {
      setAnswer(await job());
    } catch (e) {
      setAnswer(null);
      setError((e as Error).message || 'The laptop program did not answer.');
    }
    setBusy(false);
  };

  const ask = (text: string) => run(text, () => send<Answer>('/api/ask', { text }));
  const draft = (text: string) => run(text, async () => ({ ...(await send<Draft>('/api/rules/draft', { sentence: text })), kind: 'rule' as const }));
  const why = (eventId: number) => run('', async () => {
    const r = await getJSON<{ chain: Decision; answer: string; by: string }>(`/api/why?event_id=${eventId}`);
    return { kind: 'why' as const, answer: r.answer, by: r.by, chain: r.chain, event_ids: r.chain.event_ids };
  });
  const approve = async () => {
    if (answer?.kind !== 'rule' || !answer.rule) return;
    setBusy(false);
    try {
      const res = await send<Upload>('/api/rules/upload', { rule: answer.rule, slot: answer.slot ?? null });
      setUpload(res);
    } catch (e) {
      setUpload({ ok: false, steps: { drafted: true, approved: true, sent: false, board_ok: false }, detail: (e as Error).message });
    }
    room.refreshAll();
  };
  const change = () => { setInput(upload?.ok ? '' : sentence); setAnswer(null); setUpload(null); setError(null); };

  return { input, setInput, sentence, answer, upload, busy, error, others, ask, draft, why, approve, change };
}

export type Agent = ReturnType<typeof useAgent>;
