import React, { useState } from 'react';
import { CheckCircle2, Circle, Clock, MinusCircle, Sparkles, X, XCircle, AlertTriangle } from 'lucide-react';
import { usePipeline } from '../context/contexts';
import { formatDuration, sourceLabel } from '../lib/format';
import { Spinner } from './Feedback';

const STEPS = [
  ['fetching', 'Fetch'],
  ['deduplicating', 'Merge duplicates'],
  ['filtering', 'Filter'],
  ['scoring', 'Score'],
  ['saving', 'Save'],
];
const ORDER = ['starting', ...STEPS.map(([k]) => k), 'done'];

const SourceState = ({ s }) => {
  if (s.state === 'running') return <span className="src-state src-running"><Spinner size={14} label="Running" /> searching...</span>;
  if (s.state === 'done') return <span className="src-state src-done"><CheckCircle2 size={15} /> {s.count} job{s.count === 1 ? '' : 's'}{s.seconds != null ? ` · ${s.seconds}s` : ''}</span>;
  if (s.state === 'failed') return <span className="src-state src-failed"><XCircle size={15} /> failed</span>;
  if (s.state === 'skipped') return <span className="src-state src-skipped"><MinusCircle size={15} /> skipped</span>;
  return <span className="src-state src-waiting"><Clock size={15} /> waiting</span>;
};

const Stepper = ({ stage, failed }) => {
  const current = ORDER.indexOf(stage);
  return (
    <ol className="stepper" aria-label="Run stages">
      {STEPS.map(([key, label]) => {
        const idx = ORDER.indexOf(key);
        const state = stage === 'done' || idx < current ? 'done' : idx === current ? (failed ? 'failed' : 'active') : 'todo';
        return (
          <li key={key} className={`step step-${state}`} aria-current={state === 'active' ? 'step' : undefined}>
            {state === 'done' ? <CheckCircle2 size={16} /> : state === 'active' ? <Spinner size={14} label={label} />
              : state === 'failed' ? <XCircle size={16} /> : <Circle size={16} />}
            <span>{label}</span>
          </li>
        );
      })}
    </ol>
  );
};

const Summary = ({ summary }) => {
  const rows = Object.entries(summary?.per_source || {});
  return (
    <div className="run-summary">
      {rows.length > 0 && (
        <div className="table-scroll">
          <table className="mini-table">
            <thead>
              <tr><th>Source</th><th>Fetched</th><th title="Same job on another source or listed twice">Merged</th>
                <th title="Already in your list">Known</th><th title="Hard filters (experience, location, ...)">Filtered</th>
                <th title="Scored below your minimum">Low score</th><th>New</th></tr>
            </thead>
            <tbody>
              {rows.map(([name, v]) => (
                <tr key={name}>
                  <td>{sourceLabel(name)}</td><td>{v.fetched}</td><td>{v.merged_away}</td><td>{v.duplicates}</td>
                  <td>{v.filtered}</td><td>{v.below_threshold}</td><td><strong>{v.saved}</strong></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {(summary?.errors || []).length > 0 && (
        <ul className="run-errors">
          {summary.errors.map((e) => <li key={e}><AlertTriangle size={14} /> {e}</li>)}
        </ul>
      )}
    </div>
  );
};

// Live panel for the job search: stages, per-source rows, counters, and the final result.
const PipelineProgress = ({ compact = false }) => {
  const { progress: p, running, watchedRunId } = usePipeline() || {};
  const [dismissed, setDismissed] = useState(null);
  if (!p || !p.run_id) return null;
  const finished = !running && (p.stage === 'done' || p.stage === 'failed');
  // A finished run is summarised only in a tab that watched it run (not for an old run after a reload).
  if (!running && !(finished && watchedRunId === p.run_id)) return null;
  if (finished && dismissed === p.run_id) return null;

  const failed = p.stage === 'failed';
  const sources = p.sources || [];
  const doneSources = sources.filter((s) => ['done', 'failed', 'skipped'].includes(s.state)).length;
  let pct = 0;
  if (p.stage === 'fetching') pct = sources.length ? (doneSources / sources.length) * 40 : 5;
  else if (['deduplicating', 'filtering'].includes(p.stage)) pct = 45 + (p.total ? (p.processed / p.total) * 10 : 0);
  else if (p.stage === 'scoring') pct = 55 + (p.total ? (p.processed / p.total) * 40 : 0);
  else if (p.stage === 'saving') pct = 97;
  else if (finished) pct = 100;

  return (
    <section className={`card run-panel${failed ? ' run-failed' : finished ? ' run-finished' : ''}`} aria-live="polite"
      aria-label="Job search progress">
      <div className="run-head">
        <div className="run-title">
          {running ? <Spinner size={18} label="Searching" /> : failed ? <XCircle size={20} /> : <Sparkles size={20} />}
          <strong>{running ? 'Searching for jobs...' : failed ? 'Job search failed' : 'Job search finished'}</strong>
          <span className="muted">· {formatDuration(p.elapsed_seconds)}</span>
        </div>
        <div className="run-new" title="New jobs saved by this run">
          <span className="run-new-count">{p.saved || 0}</span> new job{p.saved === 1 ? '' : 's'}
        </div>
        {finished && (
          <button type="button" className="icon-btn" aria-label="Close the run summary" onClick={() => setDismissed(p.run_id)}>
            <X size={18} />
          </button>
        )}
      </div>

      <div className="progress-track" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)}>
        <div className={`progress-fill${failed ? ' progress-failed' : ''}`} style={{ width: `${Math.max(3, pct)}%` }} />
      </div>
      {!compact && <Stepper stage={p.stage} failed={failed} />}

      <p className={`run-message${failed ? ' text-danger' : ''}`}>
        {failed ? (p.error || p.message) : p.message}
        {running && p.stage === 'scoring' && p.total ? ` (${p.processed}/${p.total})` : ''}
      </p>

      {!compact && sources.length > 0 && (
        <ul className="source-rows">
          {sources.map((s) => (
            <li key={s.name} className={`source-row src-row-${s.state}`}>
              <span className="source-row-name">{sourceLabel(s.name) || s.label}</span>
              <SourceState s={s} />
              {s.reason && <span className="source-row-reason">{s.reason}</span>}
            </li>
          ))}
        </ul>
      )}

      {!compact && (running || finished) && (
        <div className="run-counters">
          <span>Fetched <strong>{p.fetched || 0}</strong></span>
          <span>Unique <strong>{p.unique || 0}</strong></span>
          {p.stage !== 'fetching' && p.total > 0 && <span>Checked <strong>{p.processed}/{p.total}</strong></span>}
          <span>New <strong>{p.saved || 0}</strong></span>
        </div>
      )}

      {finished && !compact && <Summary summary={p.summary} />}
    </section>
  );
};

export default PipelineProgress;
