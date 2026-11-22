import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { fetchAutomationStatus, triggerAutomation } from '../api';
import { PipelineContext, useToast } from './contexts';

const FAST_POLL_MS = 1000;   // while a run is active
const IDLE_POLL_MS = 10000;  // otherwise (also picks up runs started in another tab or by the scheduler)

// Polls GET /api/automation/status and shares the live run state with every page:
// - running / progress (stage, per-source rows, counters, jobs saved so far),
// - start() with double-click protection and the cooldown countdown from the server,
// - jobsVersion: bumps whenever new jobs were saved, so lists refresh by themselves,
// - newJobIds: jobs found by the current / last run (shown with a "NEW" tag).
const PipelineProvider = ({ children }) => {
  const { notify } = useToast();
  const [status, setStatus] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [starting, setStarting] = useState(false);
  const [cooldownUntil, setCooldownUntil] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const [jobsVersion, setJobsVersion] = useState(0);
  const [watchedRunId, setWatchedRunId] = useState(null);  // a run this tab saw while it was running
  const prev = useRef({ running: null, saved: 0, runId: null });
  const timer = useRef(null);
  const pollRef = useRef(null);

  const handleStatus = useCallback((s) => {
    setStatus(s);
    setLoadError(null);
    const p = s.progress || {};
    const before = prev.current;
    const running = Boolean(s.running);
    if (running && p.run_id) setWatchedRunId(p.run_id);
    const firstLoad = before.running === null;
    if (!firstLoad && (p.saved || 0) > 0 && ((p.saved || 0) !== before.saved || p.run_id !== before.runId)) {
      setJobsVersion((v) => v + 1);  // new jobs were committed: lists refresh while the run continues
    }
    if (before.running === true && !running) {
      setJobsVersion((v) => v + 1);
      const extra = (p.summary?.errors || []).slice(0, 2).join(' ');
      if (p.stage === 'failed') {
        notify({ type: 'error', title: 'Job search failed', message: p.error || p.message || 'The run stopped. Check the backend log.' });
      } else {
        notify({ type: (p.saved || 0) > 0 ? 'success' : 'info', title: 'Job search finished',
          message: `${p.message || 'Done.'}${extra ? ` Note: ${extra}` : ''}`, timeout: 12000 });
      }
    }
    prev.current = { running, saved: p.saved || 0, runId: p.run_id || null };
    if (s.cooldown_remaining > 0) setCooldownUntil(Date.now() + s.cooldown_remaining * 1000);
    return running;
  }, [notify]);

  const poll = useCallback(async () => {
    clearTimeout(timer.current);
    let running = false;
    try {
      running = handleStatus(await fetchAutomationStatus());
    } catch (err) {
      setLoadError(err.message);
      running = prev.current.running === true;
    }
    timer.current = setTimeout(() => pollRef.current?.(), running ? FAST_POLL_MS : IDLE_POLL_MS);
  }, [handleStatus]);

  useEffect(() => {
    pollRef.current = poll;
  }, [poll]);

  useEffect(() => {
    const first = setTimeout(() => pollRef.current?.(), 0);
    const onFocus = () => pollRef.current?.();
    window.addEventListener('focus', onFocus);
    return () => {
      clearTimeout(first);
      clearTimeout(timer.current);
      window.removeEventListener('focus', onFocus);
    };
  }, []);

  // A one-second clock only while a cooldown is counting down.
  useEffect(() => {
    if (cooldownUntil <= Date.now()) return undefined;
    const t = setInterval(() => {
      setNow(Date.now());
      if (Date.now() >= cooldownUntil) clearInterval(t);
    }, 1000);
    return () => clearInterval(t);
  }, [cooldownUntil]);

  const running = Boolean(status?.running);

  const start = useCallback(async () => {
    if (running || starting) {
      notify({ type: 'info', title: 'Already searching', message: 'A job search is already running; its progress is shown below.' });
      return;
    }
    setStarting(true);
    try {
      const res = await triggerAutomation();
      if (res.status === 'already_running') {
        notify({ type: 'info', title: 'Already searching', message: 'A job search was already running; showing its progress.' });
      }
      prev.current = { ...prev.current, running: true };
      await poll();
    } catch (err) {
      if (err.status === 429) {
        const wait = err.retryAfter || 60;
        setCooldownUntil(Date.now() + wait * 1000);
        setNow(Date.now());
        notify({ type: 'info', title: 'Please wait a little', message: `A search was started recently. You can start another in ${wait} s (this protects your free API quota).` });
      } else {
        notify({ type: 'error', title: 'Could not start the job search', message: err.message });
      }
    } finally {
      setStarting(false);
    }
  }, [running, starting, notify, poll]);

  const cooldownLeft = Math.max(0, Math.ceil((cooldownUntil - now) / 1000));
  const progress = status?.progress || null;
  const newJobIds = useMemo(() => new Set(progress?.new_job_ids || []), [progress?.new_job_ids]);

  const value = useMemo(() => ({
    status, progress, running, starting, start, cooldownLeft, jobsVersion, newJobIds, loadError, refresh: poll, watchedRunId,
  }), [status, progress, running, starting, start, cooldownLeft, jobsVersion, newJobIds, loadError, poll, watchedRunId]);

  return <PipelineContext.Provider value={value}>{children}</PipelineContext.Provider>;
};

export default PipelineProvider;
