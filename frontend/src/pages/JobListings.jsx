import React, { useEffect, useMemo, useState } from 'react';
import { Search, MapPin, X } from 'lucide-react';
import { fetchJobs, fetchSourcesSummary } from '../api';
import { usePipeline } from '../context/contexts';
import JobCard from '../components/JobCard';
import ExportMenu from '../components/ExportMenu';
import FindJobsButton from '../components/FindJobsButton';
import PipelineProgress from '../components/PipelineProgress';
import { ErrorState, PageLoader } from '../components/Feedback';
import { parseDate, sourceKey, sourceLabel, TRACKER_STATUSES } from '../lib/format';

const DAY_MS = 24 * 60 * 60 * 1000;
const PAGE = 40;
const DEFAULTS = { search: '', score: 'all', status: 'all', exp: 'all', location: '', source: 'all', approval: 'all',
  date: 'all', sort: 'newest', onlyNew: false };

const isFresher = (exp) => {
  const e = (exp || '').toLowerCase();
  return !exp || /fresh|entry|intern|graduate|trainee|0\s*-|0 to|\b1 (year|yr)/.test(e);
};
const isExperienced = (exp) => /\b([2-9]|\d{2})\s*\+|\b([2-9]|\d{2})\s*(-|to)\s*\d+|\b([2-9]|\d{2})\s*(years?|yrs?)/i.test(exp || '');

const JobListings = () => {
  const { jobsVersion, newJobIds } = usePipeline();
  const [jobs, setJobs] = useState([]);
  const [sources, setSources] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [f, setF] = useState(DEFAULTS);
  const [shown, setShown] = useState(PAGE);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchJobs(), fetchSourcesSummary().catch(() => [])])
      .then(([data, srcs]) => {
        if (cancelled) return;
        setJobs(data);
        setSources(srcs);
        setError(null);
        setNow(Date.now());
      })
      .catch((err) => { if (!cancelled) setError(err.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [reloadKey, jobsVersion]);

  const set = (key) => (e) => { setF((prev) => ({ ...prev, [key]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })); setShown(PAGE); };
  const replaceJob = (updated) => setJobs((prev) => prev.map((j) => (j.id === updated.id ? updated : j)));

  // Every source that exists (registered or found in the data), with job counts.
  const sourceOptions = useMemo(() => {
    const byKey = new Map();
    sources.forEach((s) => byKey.set(sourceKey(s.name), { key: sourceKey(s.name), seen: s.seen ?? s.jobs ?? 0 }));
    jobs.forEach((j) => { const k = sourceKey(j.source); if (!byKey.has(k)) byKey.set(k, { key: k, seen: 0 }); });
    return [...byKey.values()].sort((a, b) => b.seen - a.seen || sourceLabel(a.key).localeCompare(sourceLabel(b.key)));
  }, [sources, jobs]);

  const filtered = useMemo(() => {
    const term = f.search.trim().toLowerCase();
    const loc = f.location.trim().toLowerCase();
    return jobs.filter((job) => {
      if (term && !`${job.title} ${job.company}`.toLowerCase().includes(term)) return false;
      const s = job.score;
      if (f.score === 'high' && !(s >= 8)) return false;
      if (f.score === 'medium' && !(s >= 6 && s < 8)) return false;
      if (f.score === 'low' && !(s < 6)) return false;
      if (f.status !== 'all' && (job.status || 'To Apply') !== f.status) return false;
      if (f.exp === 'fresher' && !isFresher(job.experience)) return false;
      if (f.exp === 'experienced' && !isExperienced(job.experience)) return false;
      if (loc && !(job.location || '').toLowerCase().includes(loc)) return false;
      if (f.source !== 'all') {
        const names = new Set([sourceKey(job.source), ...(job.source_names || []).map(sourceKey)]);
        if (!names.has(f.source)) return false;
      }
      if (f.approval !== 'all' && (job.approval_status || 'pending') !== f.approval) return false;
      if (f.date !== 'all') {
        const found = parseDate(job.date_found);
        if (!found || now - found.getTime() > Number(f.date) * DAY_MS) return false;
      }
      if (f.onlyNew && !newJobIds.has(job.id)) return false;
      return true;
    }).sort((a, b) => {
      if (f.sort === 'score') return (b.score ?? -1) - (a.score ?? -1) || b.id - a.id;
      if (f.sort === 'company') return (a.company || '').localeCompare(b.company || '');
      return b.id - a.id;
    });
  }, [jobs, f, newJobIds, now]);

  if (loading) return <PageLoader label="Loading jobs" />;

  const exportFilters = {
    status: f.status, source: f.source, approval_status: f.approval,
    min_score: f.score === 'high' ? 8 : undefined,
  };
  const active = Object.keys(DEFAULTS).filter((k) => k !== 'sort' && f[k] !== DEFAULTS[k]).length;

  return (
    <div>
      <div className="page-head">
        <div className="page-head-text">
          <h1 className="page-title">Job Listings</h1>
          <p className="page-description">Every job found for you. Open one to see its score breakdown, cover letter and resume.</p>
        </div>
        <FindJobsButton />
      </div>

      <PipelineProgress compact />
      {error && <ErrorState title="Could not load jobs" message={error} onRetry={() => setReloadKey((k) => k + 1)} />}

      <div className="card filters" role="search">
        <div className="filter-search">
          <Search size={17} aria-hidden="true" />
          <input type="search" className="form-control" placeholder="Search title or company..." value={f.search}
            onChange={set('search')} aria-label="Search title or company" />
        </div>
        <select className="form-control" value={f.score} onChange={set('score')} aria-label="Score">
          <option value="all">All scores</option>
          <option value="high">High (8 and up)</option>
          <option value="medium">Medium (6 - 7.9)</option>
          <option value="low">Low (under 6)</option>
        </select>
        <select className="form-control" value={f.source} onChange={set('source')} aria-label="Source">
          <option value="all">All sources</option>
          {sourceOptions.map((s) => <option key={s.key} value={s.key}>{sourceLabel(s.key)} ({s.seen})</option>)}
        </select>
        <select className="form-control" value={f.approval} onChange={set('approval')} aria-label="Decision">
          <option value="all">Any decision</option>
          <option value="pending">Awaiting decision</option>
          <option value="approved">Approved</option>
          <option value="skipped">Not interested</option>
        </select>
        <select className="form-control" value={f.status} onChange={set('status')} aria-label="Tracker status">
          <option value="all">Any tracker status</option>
          {TRACKER_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select className="form-control" value={f.exp} onChange={set('exp')} aria-label="Experience">
          <option value="all">Any experience</option>
          <option value="fresher">Fresher / entry (0-1 yrs)</option>
          <option value="experienced">Experienced (2+ yrs)</option>
        </select>
        <div className="filter-search">
          <MapPin size={16} aria-hidden="true" />
          <input type="text" className="form-control" placeholder="Location..." value={f.location} onChange={set('location')}
            aria-label="Location" />
        </div>
        <select className="form-control" value={f.date} onChange={set('date')} aria-label="Found">
          <option value="all">Any date</option>
          <option value="1">Found in the last 24 hours</option>
          <option value="7">Last 7 days</option>
          <option value="30">Last 30 days</option>
        </select>
        <select className="form-control" value={f.sort} onChange={set('sort')} aria-label="Sort">
          <option value="newest">Sort: newest</option>
          <option value="score">Sort: best match</option>
          <option value="company">Sort: company A-Z</option>
        </select>
        <label className="check-label">
          <input type="checkbox" checked={f.onlyNew} onChange={set('onlyNew')} /> Only new from the latest search
        </label>
      </div>

      <div className="list-toolbar">
        <span className="muted small">
          Showing {Math.min(shown, filtered.length)} of {filtered.length} matching ({jobs.length} total)
          {active > 0 && (
            <button type="button" className="link-btn" onClick={() => { setF(DEFAULTS); setShown(PAGE); }}>
              <X size={13} /> Clear {active} filter{active === 1 ? '' : 's'}
            </button>
          )}
        </span>
        <ExportMenu filters={exportFilters} />
      </div>

      <div className="job-list">
        {filtered.length === 0 ? (
          <div className="card empty-state">
            <p><strong>No jobs match these filters.</strong></p>
            <p className="muted small">{jobs.length ? 'Try clearing a filter.' : 'Click Find New Jobs to start a search.'}</p>
          </div>
        ) : filtered.slice(0, shown).map((job) => (
          <JobCard key={job.id} job={job} isNew={newJobIds.has(job.id)} onChange={replaceJob} />
        ))}
      </div>
      {shown < filtered.length && (
        <div className="center-row">
          <button type="button" className="btn btn-outline" onClick={() => setShown((n) => n + PAGE)}>
            Show {Math.min(PAGE, filtered.length - shown)} more
          </button>
        </div>
      )}
    </div>
  );
};

export default JobListings;
