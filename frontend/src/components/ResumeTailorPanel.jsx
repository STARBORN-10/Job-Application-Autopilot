import React, { useEffect, useState } from 'react';
import { ArrowRight, Download, FileText, RefreshCw, ShieldAlert, Wand2 } from 'lucide-react';
import { downloadTailoredResume, fetchResumeText, fetchTailoredResume, tailorResume } from '../api';
import { useToast } from '../context/contexts';
import { ErrorState, Spinner } from './Feedback';
import { formatDateTime, formatScore, scoreClass } from '../lib/format';

const Coverage = ({ label, c }) => (c ? <span>{label}: <strong>{c.found}/{c.total}</strong></span> : null);

// "Resume" section of the job page: original vs tailored, score before -> after, honest gaps, the items the
// verifier removed, downloads, regenerate and a side-by-side preview.
const ResumeTailorPanel = ({ job, refreshKey = 0, onChanged }) => {
  const { notify } = useToast();
  const [data, setData] = useState(undefined); // undefined = loading, null = none yet
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [downloading, setDownloading] = useState(null);
  const [view, setView] = useState('tailored');
  const [original, setOriginal] = useState(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetchTailoredResume(job.id)
      .then((d) => { if (!cancelled) { setData(d); setError(null); } })
      .catch((err) => { if (!cancelled) { setError(err.message); setData(null); } });
    return () => { cancelled = true; };
  }, [job.id, refreshKey, reload]);

  useEffect(() => {
    if (view !== 'compare' || !data?.resume_id || original) return undefined;
    let cancelled = false;
    fetchResumeText(data.resume_id)
      .then((r) => { if (!cancelled) setOriginal(r.extracted_text || '(no text extracted)'); })
      .catch((err) => { if (!cancelled) setOriginal(`Could not load the original: ${err.message}`); });
    return () => { cancelled = true; };
  }, [view, data, original]);

  const run = async (regenerate) => {
    setBusy(true);
    setError(null);
    try {
      const res = await tailorResume(job.id, regenerate);
      setData(res);
      setOriginal(null);
      notify({ type: res.status === 'failed' ? 'error' : 'success', title: 'Resume', message: res.message });
      onChanged?.();
    } catch (err) {
      setError(err.message);
      notify({ type: 'error', title: 'Tailoring failed', message: err.message });
    } finally {
      setBusy(false);
    }
  };

  const download = async (kind) => {
    setDownloading(kind);
    try {
      await downloadTailoredResume(job.id, kind);
    } catch (err) {
      notify({ type: 'error', title: 'Download failed', message: err.message });
    } finally {
      setDownloading(null);
    }
  };

  const threshold = data?.threshold ?? 9;
  const above = typeof job.score === 'number' && job.score >= threshold;

  return (
    <section className="card section-card" aria-labelledby="resume-heading">
      <div className="section-head">
        <h2 className="card-title" id="resume-heading"><FileText size={19} /> Resume for this job</h2>
        <div className="btn-group">
          {data?.status === 'tailored' && (
            <>
              <button type="button" className="btn btn-outline btn-sm" onClick={() => download('pdf')} disabled={Boolean(downloading)}>
                {downloading === 'pdf' ? <Spinner size={13} /> : <Download size={14} />} PDF
              </button>
              <button type="button" className="btn btn-outline btn-sm" onClick={() => download('docx')} disabled={Boolean(downloading)}>
                {downloading === 'docx' ? <Spinner size={13} /> : <Download size={14} />} Word
              </button>
            </>
          )}
          <button type="button" className={`btn btn-sm ${data ? 'btn-outline' : 'btn-primary'}`} onClick={() => run(Boolean(data))}
            disabled={busy || data === undefined}
            title={above ? `Score is already ${formatScore(job.score)} (≥ ${threshold}): the original is kept` : 'Rewrite your resume for this job using only facts it already contains'}>
            {busy ? <Spinner size={13} label="Tailoring" /> : data ? <RefreshCw size={14} /> : <Wand2 size={14} />}
            {busy ? 'Tailoring...' : data ? 'Regenerate' : 'Tailor resume'}
          </button>
        </div>
      </div>

      {busy && (
        <div className="inline-loading" aria-live="polite"><Spinner size={16} /> The AI is reordering and rewording your resume for this
          job, then every fact is checked against your original. This can take up to a minute.</div>
      )}
      {error && <ErrorState title="Resume problem" message={error} compact onRetry={() => setReload((n) => n + 1)} />}
      {data === undefined && !error && <div className="inline-loading"><Spinner size={16} /> Loading...</div>}

      {data === null && !error && !busy && (
        <p className="muted">
          {above
            ? `This job already scores ${formatScore(job.score)} (at or above ${threshold}), so your original resume is used unchanged.`
            : `No tailored version yet. "Tailor resume" (or Approve) creates one that only reorders and rewords what your resume
               already says, then re-scores this job with it. Below ${threshold} it tries to help; it never invents skills.`}
        </p>
      )}

      {data && data.status === 'not_needed' && (
        <div className="alert alert-success">
          <div className="alert-body">{data.message}</div>
        </div>
      )}
      {data && data.status === 'failed' && (
        <ErrorState title="Could not tailor the resume" message={`${data.message}${data.error ? ` (${data.error})` : ''}`} compact />
      )}

      {data && data.status === 'tailored' && (
        <>
          <div className="score-compare">
            <div className="score-compare-item">
              <div className="stat-label">Score with your original</div>
              <div className={`score-big ${scoreClass(data.score_before)}`}>{formatScore(data.score_before)}</div>
            </div>
            <ArrowRight size={22} aria-hidden="true" className="muted" />
            <div className="score-compare-item">
              <div className="stat-label">With the tailored resume</div>
              <div className={`score-big ${scoreClass(data.score_after)}`}>{formatScore(data.score_after)}</div>
            </div>
            <div className="score-compare-note small muted">
              Same scoring engine, re-scored now. {data.score_after >= threshold ? 'Target reached.' : `Still below ${threshold}: the score measures real fit, so rewording cannot close real skill gaps.`}
              <div className="pill-row">
                <Coverage label="Job keywords in original" c={data.keyword_coverage_before} />
                <Coverage label="in tailored" c={data.keyword_coverage_after} />
              </div>
            </div>
          </div>
          {data.outdated && <p className="small text-warning">Made for an older or different resume. Click Regenerate to update it.</p>}
          <div className="two-col">
            <div>
              <div className="stat-label">Gaps you would genuinely need</div>
              {data.gaps.length ? (
                <div className="chip-row">{data.gaps.map((g) => <span key={g} className="chip chip-bad">{g}</span>)}</div>
              ) : <p className="small muted">None: your resume covers what the posting asks for.</p>}
              <p className="small muted">These were NOT added to your resume, because it does not show them.</p>
            </div>
            <div>
              <div className="stat-label"><ShieldAlert size={14} /> Removed by the fact check: {data.removed_unverified.length}</div>
              {data.removed_unverified.length ? (
                <details>
                  <summary className="small">Show what the AI wrote that is not in your resume</summary>
                  <ul className="small removed-list">
                    {data.removed_unverified.map((r, i) => <li key={i}><em>{r.text}</em> - {r.reason}</li>)}
                  </ul>
                </details>
              ) : <p className="small muted">Nothing: every line traces back to your resume.</p>}
            </div>
          </div>
          <div className="seg" role="tablist" aria-label="Preview">
            <button type="button" role="tab" aria-selected={view === 'tailored'} className={view === 'tailored' ? 'seg-on' : ''}
              onClick={() => setView('tailored')}>Tailored text</button>
            <button type="button" role="tab" aria-selected={view === 'compare'} className={view === 'compare' ? 'seg-on' : ''}
              onClick={() => setView('compare')}>Side by side with the original</button>
          </div>
          <div className={view === 'compare' ? 'compare-grid' : ''}>
            {view === 'compare' && (
              <div>
                <div className="stat-label">Original</div>
                <pre className="text-box">{original ?? 'Loading...'}</pre>
              </div>
            )}
            <div>
              {view === 'compare' && <div className="stat-label">Tailored</div>}
              <pre className="text-box">{data.tailored_text}</pre>
            </div>
          </div>
          <p className="small muted">Made {formatDateTime(data.created_at)} with {data.provider || 'AI'}.{data.error ? ` ${data.error}` : ''}</p>
        </>
      )}
    </section>
  );
};

export default ResumeTailorPanel;
