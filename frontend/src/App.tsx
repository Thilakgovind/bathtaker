import { useEffect, useState } from 'react';
import { AgentSide, useAgent } from './components/AgentSide';
import { GridBand } from './components/GridBand';
import { Stage } from './components/Stage';
import { useRoom } from './useRoom';

const W = 1440;
const H = 900;

/** The screen is drawn at 1440 x 900 and scaled to fit the window, so it never scrolls sideways. */
function useFit() {
  const [scale, setScale] = useState(1);
  useEffect(() => {
    const fit = () => setScale(Math.min(window.innerWidth / W, window.innerHeight / H));
    fit();
    window.addEventListener('resize', fit);
    return () => window.removeEventListener('resize', fit);
  }, []);
  return scale;
}

export default function App() {
  const room = useRoom();
  const agent = useAgent(room);
  const scale = useFit();
  return (
    <div className="w-screen h-screen overflow-hidden flex items-center justify-center bg-ink">
      <div style={{ width: W * scale, height: H * scale }} className="relative shrink-0">
        <div
          className="[font-synthesis:none] text-[12px] leading-4 flex overflow-clip w-360 h-225 flex-col font-grotesk absolute left-0 top-0 bg-porcelain antialiased origin-top-left"
          style={{ transform: `scale(${scale})` }}
        >
          <GridBand room={room} />
          <Stage room={room} onWhy={agent.why} />
          <AgentSide room={room} agent={agent} />
        </div>
      </div>
    </div>
  );
}
