import React from 'react';
import { Sparkles, Timer } from 'lucide-react';
import { usePipeline } from '../context/contexts';
import { Spinner } from './Feedback';

// "Find New Jobs": disabled while a run is active or the server-side cooldown is counting down, and it
// says why. The live progress is shown by <PipelineProgress />.
const FindJobsButton = ({ label = 'Find New Jobs', className = 'btn btn-primary' }) => {
  const { running, starting, start, cooldownLeft } = usePipeline();
  const busy = running || starting;
  const cooling = !busy && cooldownLeft > 0;
  let text = label;
  let title = 'Search every enabled source for new jobs now';
  if (starting) text = 'Starting...';
  else if (running) { text = 'Searching...'; title = 'A job search is running; see its progress below'; }
  else if (cooling) { text = `Wait ${cooldownLeft}s`; title = 'A search was started recently; this short pause protects your free API quota'; }
  return (
    <button type="button" className={className} onClick={start} disabled={busy || cooling} title={title} aria-busy={busy}>
      {busy ? <Spinner size={15} label="Searching" /> : cooling ? <Timer size={16} /> : <Sparkles size={16} />}
      {text}
    </button>
  );
};

export default FindJobsButton;
