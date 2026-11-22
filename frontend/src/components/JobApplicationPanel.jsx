import React, { useEffect, useRef, useState } from 'react';
import { ClipboardList, Download, ExternalLink, Image, MousePointerClick } from 'lucide-react';
import { downloadTailoredResume, fetchJobTimeline, fetchTask, prefillApplication, screenshotUrl } from '../api';
import { useToast } from '../context/contexts';
import { CopyButton, ErrorState, Spinner } from './Feedback';
import { APPLICATION_STATUS, METHOD_LABEL, atsFromUrl, formatDateTime } from '../lib/format';

export const ApplicationRecord = ({ a, job }) => {
  const { notify } = useToast();
  const [dl, setDl] = useState(false);
  const st = APPLICATION_STATUS[a.status] || { label: a.status, badge: 'badge-neutral' };
  const p = a.payload_summary || {};
  const link = p.form_url || job.url;
  const download = async () => {
    setDl(true);
    try { await downloadTailoredResume(job.id, 'pdf'); } catch (err) {
      notify({ type: 'error', title: 'Download failed', message: err.message });
    } finally { setDl(false); }
  };
  return (
    <div className="app-record">
      <div className="badge-row">
        <span className="badge badge-neutral">{METHOD_LABEL[a.method] || a.method}</span>
        <span className={`badge ${st.badge}`}>{st.label}</span>
        {a.dry_run && a.method === 'email' && <span className="badge badge-primary">dry run</span>}
        <span className="muted small">{formatDateTime(a.created_at)}</span>
      </div>
      <p className="app-outcome">{a.outcome}</p>
      {a.method === 'email' && p.to && (
        <p className="small muted">To {p.to} · Subject "{p.subject}" · Attachment: {p.attachment || 'none'}</p>
      )}
      {a.method === 'autofill' && (p.filled || p.unfilled_required) && (
        <div className="small autofill-report">
          {p.filled?.length > 0 && <div><strong>Filled ({p.filled.length}):</strong> {p.filled.map((x) => x.field).join(', ')}</div>}
          {p.unfilled_required?.length > 0 && (
            <div className="text-warning"><strong>Needs your answer:</strong> {p.unfilled_required.map((x) => `${x.field} (${x.reason})`).join('; ')}</div>
          )}
          {p.needs_your_answer?.length > 0 && (
            <div className="muted">Never answered automatically: {p.needs_your_answer.map((x) => x.field).join(', ')}</div>
          )}
          {p.captcha && <div className="text-warning">CAPTCHA on the page: you must solve it yourself.</div>}
          {p.browser_left_open && <div>A browser window was left open for you to review and submit.</div>}
        </div>
      )}
      {a.resume_kind && <p className="small muted">Resume used: {a.resume_kind === 'tailored' ? 'tailored for this job' : a.resume_kind === 'original' ? 'your original' : 'none found'}{a.resume_file ? ` (${a.resume_file})` : ''}</p>}
      {a.error && a.status === 'failed' && <p className="small text-danger">Reason: {a.error}</p>}
      <div className="btn-group">
        {job.cover_letter && <CopyButton text={job.cover_letter} label="Copy cover letter" />}
        {link && (
          <a href={link} target="_blank" rel="noopener noreferrer" className="btn btn-outline btn-sm">
            <ExternalLink size={14} /> Open application link
          </a>
        )}
        {a.resume_kind === 'tailored' && (
          <button type="button" className="btn btn-outline btn-sm" onClick={download} disabled={dl}>
            {dl ? <Spinner size={13} /> : <Download size={14} />} Tailored resume
          </button>
        )}
        {a.screenshot_url && (
          <a href={screenshotUrl(a.screenshot_url)} target="_blank" rel="noopener noreferrer" className="btn btn-outline btn-sm">
            <Image size={14} /> Screenshot of the filled form
          </a>
        )}
      </div>
    </div>
  );
};

// "Application" section of the job page: what Approve did (outcome, links, cover letter), the Greenhouse /
// Lever / Ashby form pre-fill with live steps, and the full timeline for this job.
const JobApplicationPanel = ({ job, refreshKey = 0, onChanged }) => {
  const { notify } = useToast();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [task, setTask] = useState(null);
  const [starting, setStarting] = useState(false);
  const [reload, setReload] = useState(0);
  const onChangedRef = useRef(onChanged);
  useEffect(() => { onChangedRef.current = onChanged; }, [onChanged]);

  useEffect(() => {
    let cancelled = false;
    fetchJobTimeline(job.id)
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setError(null);
        const runningTask = (d.tasks || []).find((t) => t.kind === 'autofill' && t.status === 'running');
        if (runningTask) setTask(runningTask);
      })
      .catch((err) => { if (!cancelled) setError(err.message); });
    return () => { cancelled = true; };
  }, [job.id, refreshKey, reload]);

  // Poll a running pre-fill task.
  useEffect(() => {
    if (!task || task.status !== 'running') return undefined;
    const t = setTimeout(async () => {
      try {
        const next = await fetchTask(task.id);
        setTask(next);
        if (next.status !== 'running') {
          const msg = next.result?.message || next.error || 'Finished.';
          notify({ type: next.status === 'done' && next.result?.status !== 'failed' ? 'success' : 'error',
            title: 'Application form', message: msg, timeout: 15000 });
          setReload((n) => n + 1);
          onChangedRef.current?.();
        }
      } catch (err) {
        setTask((prev) => ({ ...prev, status: 'failed', error: err.message }));
      }
    }, 1500);
    return () => clearTimeout(t);
  }, [task, notify]);

  const prefill = async () => {
    setStarting(true);
    try {
      setTask(await prefillApplication(job.id));
    } catch (err) {
      notify({ type: 'error', title: 'Cannot pre-fill this form', message: err.message, timeout: 15000 });
    } finally {
      setStarting(false);
    }
  };

  const ats = atsFromUrl(job.url);
  const apps = data?.applications || [];
  const running = task?.status === 'running';

  return (
    <section className="card section-card" aria-labelledby="application-heading">
      <div className="section-head">
        <h2 className="card-title" id="application-heading"><ClipboardList size={19} /> Application</h2>
        {ats && (
          <button type="button" className="btn btn-outline btn-sm" onClick={prefill} disabled={starting || running}
            title={`Open the ${ats} form in a browser, fill your details, upload the resume and paste the cover letter. It stops before submitting.`}>
            {starting || running ? <Spinner size={13} label="Filling" /> : <MousePointerClick size={14} />}
            {running ? 'Filling form...' : 'Pre-fill application form'}
          </button>
        )}
      </div>

      {task && (
        <div className={`task-box task-${task.status}`} aria-live="polite">
          <div className="task-step">{running && <Spinner size={14} />} {task.step}</div>
          {running && (
            <ol className="task-steps small muted">{task.steps.map((s, i) => <li key={i}>{s.message}</li>)}</ol>
          )}
          {task.status === 'failed' && <div className="text-danger small">{task.error}</div>}
        </div>
      )}

      {error && <ErrorState title="Could not load the application history" message={error} compact onRetry={() => setReload((n) => n + 1)} />}
      {!data && !error && <div className="inline-loading"><Spinner size={16} /> Loading...</div>}

      {data && apps.length === 0 && (
        <p className="muted">
          Nothing prepared yet. <strong>Approve &amp; apply</strong> prepares the application (an e-mail to the recruiter when
          the posting has an address, otherwise the link and cover letter for you to submit){ats ? `; this ${ats} form can also be pre-filled for you` : ''}.
        </p>
      )}
      {apps.map((a) => <ApplicationRecord key={a.id} a={a} job={job} />)}

      {data?.events?.length > 0 && (
        <details className="timeline" open={apps.length > 0}>
          <summary>Timeline ({data.events.length})</summary>
          <ol>
            {data.events.map((e, i) => (
              <li key={i}><span className="muted small">{formatDateTime(e.at)}</span> {e.text}</li>
            ))}
          </ol>
        </details>
      )}
    </section>
  );
};

export default JobApplicationPanel;
