import { useCallback, useEffect, useRef, useState } from 'react';
import { getJSON } from './api';
import type { Decision, Ev, Job, Link, Notice, Reading, RoomState } from './api';

const NO_LINK: Link = { connected: false, port: null, source: 'UNKNOWN', hello: null, silent_for_s: null, error: '' };

/** Everything the screen shows about the room, kept live.
 *  Readings arrive over the WebSocket about twice a second. Jobs, the decision and notices are fetched
 *  again whenever the board reports an event, and on a slow timer as a safety net. */
export function useRoom() {
  const [serverUp, setServerUp] = useState(false);      // is the laptop program answering at all
  const [state, setState] = useState<RoomState | null>(null);
  const [link, setLink] = useState<Link>(NO_LINK);
  const [reading, setReading] = useState<Reading | null>(null);
  const [events, setEvents] = useState<Ev[]>([]);       // oldest first
  const [jobs, setJobs] = useState<Job[]>([]);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [notices, setNotices] = useState<Notice[]>([]);
  const [now, setNow] = useState(() => Date.now() / 1000);
  const checking = useRef(false);

  const refreshState = useCallback(() => {
    getJSON<RoomState>('/api/state').then((s) => {
      setState(s);
      setLink(s.link);
      if (s.reading) setReading(s.reading); else if (!s.link.connected) setReading(null);
    }).catch(() => {});
  }, []);

  const refreshDecision = useCallback(() => {
    getJSON<Decision | null>('/api/decision').then((d) => {
      checking.current = d?.status === 'checking';
      setDecision(d);
    }).catch(() => {});
  }, []);

  const refreshLists = useCallback(() => {
    getJSON<Job[]>('/api/jobs').then(setJobs).catch(() => {});
    getJSON<Notice[]>('/api/notices').then(setNotices).catch(() => {});
    refreshDecision();
  }, [refreshDecision]);

  const refreshEvents = useCallback(() => {
    getJSON<Ev[]>('/api/events?minutes=180&limit=60').then(setEvents).catch(() => {});
  }, []);

  const refreshAll = useCallback(() => {
    refreshState(); refreshLists(); refreshEvents();
  }, [refreshState, refreshLists, refreshEvents]);

  // the live socket, reconnecting by itself
  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let closed = false;
    const connect = () => {
      const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      ws = new WebSocket(`${scheme}//${window.location.host}/ws`);
      ws.onopen = () => { setServerUp(true); refreshAll(); };
      ws.onclose = () => {
        setServerUp(false);
        if (!closed) timer = setTimeout(connect, 1500);
      };
      ws.onmessage = (m) => {
        let d: any;
        try { d = JSON.parse(m.data); } catch { return; }
        if (d.type === 'reading') {
          setReading(d.reading);
        } else if (d.type === 'event') {
          setEvents((prev) => (prev.some((e) => e.id === d.event.id) ? prev : [...prev, d.event].slice(-60)));
          refreshState(); refreshLists();
        } else if (d.type === 'link') {
          setLink(d.link);
          if (!d.link.connected) setReading(null);
          refreshState();
        } else if (d.type === 'hello') {
          setState(d.state); setLink(d.state.link); setReading(d.state.reading);
        } else {                                   // rules, jobs, synced
          refreshAll();
        }
      };
    };
    connect();
    return () => { closed = true; clearTimeout(timer); ws?.close(); };
  }, [refreshAll, refreshLists, refreshState]);

  // a clock for "4 min ago", a fast poll while a fan check counts down, and a slow safety net
  useEffect(() => {
    let n = 0;
    const t = setInterval(() => {
      n += 1;
      setNow(Date.now() / 1000);
      if (checking.current) refreshDecision();
      if (n % 10 === 0) { refreshState(); refreshLists(); }
    }, 1000);
    return () => clearInterval(t);
  }, [refreshDecision, refreshLists, refreshState]);

  const connected = serverUp && link.connected;
  return {
    serverUp, connected, link, state, reading: connected ? reading : null, events, jobs, decision, notices, now,
    refreshAll,
  };
}

export type Room = ReturnType<typeof useRoom>;
