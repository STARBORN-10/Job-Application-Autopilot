// Shared display helpers: sources, scores, statuses and dates.

// Known sources (lower-case ids from the backend) with a short label and badge colours.
export const SOURCE_META = {
  jsearch: { label: 'JSearch', bg: '#e0e7ff', fg: '#3730a3' },
  adzuna: { label: 'Adzuna', bg: '#dcfce7', fg: '#166534' },
  jooble: { label: 'Jooble', bg: '#fef3c7', fg: '#92400e' },
  ats: { label: 'Career board', bg: '#e0f2fe', fg: '#075985' },
  amazon: { label: 'Amazon Jobs', bg: '#ffedd5', fg: '#9a3412' },
  greenhouse: { label: 'Greenhouse', bg: '#d1fae5', fg: '#065f46' },
  lever: { label: 'Lever', bg: '#ede9fe', fg: '#5b21b6' },
  ashby: { label: 'Ashby', bg: '#fce7f3', fg: '#9d174d' },
  internshala: { label: 'Internshala', bg: '#cffafe', fg: '#155e75' },
  jobspy: { label: 'Indeed/LinkedIn', bg: '#f3e8ff', fg: '#6b21a8' },
  make: { label: 'Imported', bg: '#f1f5f9', fg: '#475569' },
  unknown: { label: 'Unknown', bg: '#f1f5f9', fg: '#475569' },
};

export const sourceKey = (name) => (name || 'unknown').trim().toLowerCase();

// For a career-board job, the board (Greenhouse / Lever / Ashby) is more useful than "career board".
export const atsFromUrl = (url) => {
  if (!url) return null;
  if (/greenhouse\.io/i.test(url)) return 'greenhouse';
  if (/lever\.co/i.test(url)) return 'lever';
  if (/ashbyhq\.com/i.test(url)) return 'ashby';
  return null;
};

export const sourceMeta = (name, url) => {
  const key = sourceKey(name);
  const effective = key === 'ats' ? atsFromUrl(url) || key : key;
  return SOURCE_META[effective] || { label: name || 'Unknown', bg: '#f1f5f9', fg: '#475569' };
};

export const sourceLabel = (name) => (SOURCE_META[sourceKey(name)] || { label: name || 'Unknown' }).label;

// Other sources a merged job was also found on (excluding its own source).
export const alsoFoundOn = (job) => {
  const own = sourceKey(job?.source);
  const seen = new Set();
  return (job?.source_names || [])
    .map(sourceKey)
    .filter((n) => n !== own && !seen.has(n) && seen.add(n));
};

export const scoreClass = (score) => {
  if (score === null || score === undefined) return 'score-none';
  if (score >= 8) return 'score-high';
  if (score >= 6) return 'score-medium';
  return 'score-low';
};

export const formatScore = (score) => (score === null || score === undefined ? '-' : Number(score).toFixed(1));

export const TRACKER_STATUSES = ['To Apply', 'Applied', 'Interview', 'Offer', 'Rejected'];
export const STATUS_BADGE = {
  'To Apply': 'badge-warning',
  Applied: 'badge-primary',
  Interview: 'badge-info',
  Offer: 'badge-success',
  Rejected: 'badge-danger',
};

export const APPLICATION_STATUS = {
  sent: { label: 'Sent', badge: 'badge-success' },
  dry_run: { label: 'Dry run (not sent)', badge: 'badge-primary' },
  ready_to_submit: { label: 'Ready for you to submit', badge: 'badge-warning' },
  in_progress: { label: 'Filling form...', badge: 'badge-info' },
  prefilled: { label: 'Form pre-filled', badge: 'badge-warning' },
  needs_input: { label: 'Needs your answers', badge: 'badge-warning' },
  submitted: { label: 'Submitted', badge: 'badge-success' },
  failed: { label: 'Failed', badge: 'badge-danger' },
  skipped: { label: 'Not sent', badge: 'badge-neutral' },
};

export const METHOD_LABEL = { email: 'E-mail', assisted: 'Assisted apply', autofill: 'Form pre-fill' };

// The backend stores naive UTC timestamps; treat them as UTC.
export const parseDate = (iso) => {
  if (!iso) return null;
  const s = String(iso);
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : `${s}Z`);
  return Number.isNaN(d.getTime()) ? null : d;
};

export const formatDateTime = (iso) => parseDate(iso)?.toLocaleString() || '';
export const formatDate = (iso) => parseDate(iso)?.toLocaleDateString() || '';

export const formatDuration = (seconds) => {
  const s = Math.max(0, Math.round(seconds || 0));
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`;
};
