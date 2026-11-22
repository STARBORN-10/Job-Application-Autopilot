const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

// Root of the backend (API_URL without the trailing /api) - used for health checks.
export const API_ROOT = API_URL.replace(/\/api\/?$/, '');
export const apiUrl = (path) => `${API_URL}${path}`;

// Free hosts (e.g. Render) can take a minute or more to wake up. Without a timeout a request would
// hang forever and the page would just keep spinning, so every request is capped.
const REQUEST_TIMEOUT_MS = 60000;

// Optional: when the backend sets ADMIN_API_KEY, approve/skip/apply/tailor/pre-fill need it. A value baked
// into the frontend build is visible to anyone who loads the site, so it only keeps out casual callers.
const ADMIN_KEY = import.meta.env.VITE_ADMIN_API_KEY || '';

// ---------------------------------------------------------------------------
// Session token (set at sign-in, sent with every request)
// ---------------------------------------------------------------------------
const TOKEN_KEY = 'autopilot_token';
export const getToken = () => { try { return localStorage.getItem(TOKEN_KEY) || ''; } catch { return ''; } };
export const setToken = (token) => { try { localStorage.setItem(TOKEN_KEY, token); } catch { /* storage blocked: stay signed in for this tab only */ } };
export const clearToken = () => { try { localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ } };
let memoryToken = '';
const currentToken = () => getToken() || memoryToken;
export const rememberToken = (token) => { memoryToken = token; setToken(token); };
export const forgetToken = () => { memoryToken = ''; clearToken(); };
export const SESSION_EXPIRED_EVENT = 'autopilot:session-expired';

// An Error with the HTTP status and, for 429, the seconds to wait.
export class ApiError extends Error {
  constructor(message, { status = 0, kind = 'http', retryAfter = null } = {}) {
    super(message);
    this.status = status;
    this.kind = kind;
    this.retryAfter = retryAfter;
  }
}

const apiFetch = async (url, options = {}, timeoutMs = REQUEST_TIMEOUT_MS) => {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const token = currentToken();
    const headers = { ...(options.headers || {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) };
    const response = await fetch(url, { ...options, headers, signal: controller.signal });
    // The server says "Please sign in." when the session is missing, expired or ended: go back to the sign-in page.
    // (A wrong admin key is also a 401 but with a different message, and must not sign anyone out.)
    if (response.status === 401 && token) {
      const body = await response.clone().json().catch(() => ({}));
      if (body.detail === 'Please sign in.') {
        forgetToken();
        window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
      }
    }
    return response;
  } catch (err) {
    if (err.name === 'AbortError') {
      throw new ApiError('The server is taking too long to respond. It may be waking up - please try again in a minute.', { kind: 'timeout' });
    }
    throw new ApiError('Cannot reach the server. Check that the backend is running and your connection works.', { kind: 'network' });
  } finally {
    clearTimeout(timer);
  }
};

// Plain-language message for an error response.
const describeStatus = (status, detail) => {
  if (detail) return detail;
  if (status === 401) return 'Not allowed: sign in again, or the admin key is missing or wrong (VITE_ADMIN_API_KEY).';
  if (status === 404) return 'Not found.';
  if (status === 422) return 'Some values are not valid.';
  if (status === 429) return 'Too many requests: please wait a moment and try again.';
  if (status === 503) return 'The server cannot reach its database or a required service right now.';
  if (status >= 500) return `The server had a problem (HTTP ${status}). Check the backend log.`;
  return `Request failed (HTTP ${status}).`;
};

const errorFromResponse = async (response, fallback) => {
  const body = await response.json().catch(() => ({}));
  const detail = Array.isArray(body.detail)
    ? body.detail.map((d) => `${(d.loc || []).slice(-1)[0] || 'value'}: ${d.msg}`).join('; ')
    : body.detail;
  const retryAfter = Number(response.headers.get('Retry-After')) || null;
  return new ApiError(describeStatus(response.status, detail || fallback), { status: response.status, retryAfter });
};

const request = async (path, { method = 'GET', body, admin = false, timeout, fallback } = {}) => {
  const headers = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (admin && ADMIN_KEY) headers['X-Admin-Key'] = ADMIN_KEY;
  const response = await apiFetch(apiUrl(path), {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  }, timeout);
  if (!response.ok) throw await errorFromResponse(response, fallback);
  return response.json();
};

// Health check used by the "backend unreachable" banner. Uses /api/health (reports database
// problems) and falls back to the root URL for older backends that do not have it yet.
export const pingBackend = async () => {
  const response = await apiFetch(`${API_URL}/health`, {}, 8000);
  if (response.status === 404) {
    const root = await apiFetch(`${API_ROOT}/`, {}, 8000);
    if (!root.ok) throw new Error('Backend not healthy');
    return true;
  }
  if (response.status === 503) {
    const body = await response.json().catch(() => ({}));
    const err = new Error(body.detail || 'Database unreachable');
    err.kind = 'database';
    throw err;
  }
  if (!response.ok) throw new Error('Backend not healthy');
  return true;
};

// ---------------------------------------------------------------------------
// Jobs
// ---------------------------------------------------------------------------
export const fetchJobs = (sort = 'newest') => request(`/jobs?limit=5000&sort=${sort}`, { fallback: 'Could not load jobs.' });
export const fetchTopJobs = (limit = 5) => request(`/jobs/top?limit=${limit}`, { fallback: 'Could not load top matches.' });
export const fetchJob = (id) => request(`/jobs/${id}`, { fallback: 'Could not load this job.' });
export const updateJob = (id, data) => request(`/jobs/${id}`, { method: 'PUT', body: data, fallback: 'Could not update the job.' });
export const deleteJob = (id) => request(`/jobs/${id}`, { method: 'DELETE', fallback: 'Could not delete the job.' });
export const analyzeJob = (id) =>
  request(`/jobs/${id}/analyze`, { method: 'POST', timeout: 90000, fallback: 'Analysis failed.' });
export const fetchAnalytics = (days = 30, source = '') =>
  request(`/analytics?days=${days}${source ? `&source=${encodeURIComponent(source)}` : ''}`, { fallback: 'Could not load analytics.' });

// ---------------------------------------------------------------------------
// Export (CSV / Excel / PDF): downloaded with fetch so the UI can show a spinner and errors.
// ---------------------------------------------------------------------------
export const exportUrl = (format, filters = {}) => {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '' && v !== 'all') params.set(k, v);
  });
  const qs = params.toString();
  return `${API_URL}/export/jobs.${format}${qs ? `?${qs}` : ''}`;
};
export const EXPORT_CSV_URL = exportUrl('csv');

const saveBlob = (blob, filename) => {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
};

const filenameFrom = (response, fallback) => {
  const cd = response.headers.get('Content-Disposition') || '';
  const m = cd.match(/filename="?([^";]+)"?/i);
  return m ? m[1] : fallback;
};

export const downloadFile = async (url, fallbackName) => {
  const response = await apiFetch(url, {}, 120000);
  if (!response.ok) throw await errorFromResponse(response, 'Download failed.');
  const blob = await response.blob();
  const name = filenameFrom(response, fallbackName);
  saveBlob(blob, name);
  return name;
};

// Open a protected file (e.g. a screenshot) in a new tab. A plain link cannot send the sign-in token.
export const openFile = async (url) => {
  const response = await apiFetch(url, {}, 120000);
  if (!response.ok) throw await errorFromResponse(response, 'Could not open the file.');
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const tab = window.open(objectUrl, '_blank', 'noopener');
  if (!tab) saveBlob(blob, 'file');   // pop-up blocked: download instead
  setTimeout(() => URL.revokeObjectURL(objectUrl), 60000);
};

export const downloadExport = (format, filters) => downloadFile(exportUrl(format, filters), `jobs.${format}`);

// ---------------------------------------------------------------------------
// Resumes
// ---------------------------------------------------------------------------
export const fetchResumes = () => request('/resumes', { fallback: 'Could not load resumes.' });

const uploadForm = async (path, method, form) => {
  const response = await apiFetch(apiUrl(path), { method, body: form }, 120000);
  if (!response.ok) throw await errorFromResponse(response, 'Upload failed.');
  return response.json();
};

export const uploadResume = (file, targetRole) => {
  const form = new FormData();
  form.append('file', file);
  form.append('target_role', targetRole);
  return uploadForm('/resumes', 'POST', form);
};

export const replaceResumeFile = (id, file) => {
  const form = new FormData();
  form.append('file', file);
  return uploadForm(`/resumes/${id}/replace`, 'PUT', form);
};

export const updateResumeRole = (id, targetRole) =>
  request(`/resumes/${id}/role`, { method: 'PUT', body: { target_role: targetRole }, fallback: 'Role update failed.' });
export const deleteResume = (id) => request(`/resumes/${id}`, { method: 'DELETE', fallback: 'Delete failed.' });
export const activateResume = (id) => request(`/resumes/${id}/activate`, { method: 'PUT', fallback: 'Activation failed.' });
export const fetchResumeText = (id) => request(`/resumes/${id}/text`, { fallback: 'Could not load the resume text.' });

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------
export const fetchExperienceFilter = () => request('/settings/experience-filter', { fallback: 'Could not load settings.' });
export const updateExperienceFilter = (data) =>
  request('/settings/experience-filter', { method: 'PUT', body: data, fallback: 'Could not save settings.' });
export const fetchGeneralSettings = () => request('/settings', { fallback: 'Could not load settings.' });
export const updateGeneralSettings = (data) =>
  request('/settings', { method: 'PUT', body: data, fallback: 'Could not save settings.' });
export const fetchApplicantProfile = () => request('/settings/applicant-profile', { fallback: 'Could not load your profile.' });
export const updateApplicantProfile = (data) =>
  request('/settings/applicant-profile', { method: 'PUT', body: data, fallback: 'Could not save your profile.' });
export const fetchAutofillConfig = () => request('/autofill/config', { fallback: 'Could not load form-filling settings.' });

// ---------------------------------------------------------------------------
// Job search runs (live progress)
// ---------------------------------------------------------------------------
export const fetchAutomationStatus = () => request('/automation/status', { timeout: 15000, fallback: 'Could not read the run status.' });
export const triggerAutomation = () => request('/automation/trigger', { method: 'POST', fallback: 'Could not start the job search.' });

// ---------------------------------------------------------------------------
// V2: sources, scoring, approvals, applications, tailored resumes, form pre-fill
// ---------------------------------------------------------------------------
export const fetchSources = () => request('/sources');
export const fetchSourcesSummary = () => request('/sources/summary', { fallback: 'Could not load the source list.' });
export const toggleSource = (name, enabled) => request(`/sources/${name}`, { method: 'PUT', body: { enabled } });
export const fetchAtsCompanies = () => request('/settings/ats-companies');
export const updateAtsCompanies = (companies) => request('/settings/ats-companies', { method: 'PUT', body: { companies } });
export const fetchAiProviders = () => request('/ai/providers');
export const fetchScoringWeights = () => request('/scoring/weights');
export const updateScoringWeights = (weights) => request('/scoring/weights', { method: 'PUT', body: { weights } });
export const tuneScoringWeights = (apply = false) =>
  request(`/scoring/tune?apply=${apply ? 'true' : 'false'}`, { method: 'POST', admin: true });

// Approve can take a while: it may tailor the resume (AI) and prepare the application first.
export const approveJob = (id) => request(`/jobs/${id}/approve`, { method: 'POST', admin: true, timeout: 150000, fallback: 'Approve failed.' });
export const skipJob = (id) => request(`/jobs/${id}/skip`, { method: 'POST', admin: true, fallback: 'Skip failed.' });
export const fetchApprovePreview = (id) => request(`/jobs/${id}/approve-preview`, { fallback: 'Could not load what Approve will do.' });
export const fetchJobTimeline = (id) => request(`/jobs/${id}/timeline`, { fallback: 'Could not load the application history.' });
export const fetchApplications = () => request('/applications', { fallback: 'Could not load applications.' });
export const fetchApplicationsConfig = () => request('/applications/config');
export const retryApplication = (jobId) => request(`/jobs/${jobId}/apply`, { method: 'POST', admin: true, timeout: 120000 });

export const tailorResume = (jobId, regenerate = false) =>
  request(`/jobs/${jobId}/tailor-resume?regenerate=${regenerate ? 'true' : 'false'}`,
    { method: 'POST', admin: true, timeout: 150000, fallback: 'Tailoring failed.' });
export const fetchTailoredResume = async (jobId) => {
  try {
    return await request(`/jobs/${jobId}/tailored-resume`);
  } catch (err) {
    if (err.status === 404) return null;
    throw err;
  }
};
export const tailoredResumeUrl = (jobId, kind) => `${API_URL}/jobs/${jobId}/tailored-resume.${kind}`;
export const downloadTailoredResume = (jobId, kind) => downloadFile(tailoredResumeUrl(jobId, kind), `resume.${kind}`);

export const prefillApplication = (jobId) =>
  request(`/jobs/${jobId}/prefill`, { method: 'POST', admin: true, fallback: 'Could not start the form pre-fill.' });
export const fetchTask = (taskId) => request(`/tasks/${taskId}`, { timeout: 15000 });
export const screenshotUrl = (path) => `${API_ROOT}${path}`;

// ---------------------------------------------------------------------------
// Accounts
// ---------------------------------------------------------------------------
export const fetchAuthConfig = () => request('/auth/config', { timeout: 20000, fallback: 'Could not reach the server.' });
export const registerUser = (data) => request('/auth/register', { method: 'POST', body: data, fallback: 'Could not create the account.' });
export const loginUser = (data) => request('/auth/login', { method: 'POST', body: data, fallback: 'Could not sign in.' });
export const fetchMe = () => request('/auth/me', { fallback: 'Could not load your account.' });
export const updateMe = (name) => request('/auth/me', { method: 'PUT', body: { name }, fallback: 'Could not save your name.' });
export const changePassword = (current_password, new_password) =>
  request('/auth/change-password', { method: 'POST', body: { current_password, new_password }, fallback: 'Could not change the password.' });
export const signOutEverywhere = () => request('/auth/logout-all', { method: 'POST', fallback: 'Could not sign out other devices.' });
export const deleteAccount = (password) =>
  request('/auth/account', { method: 'DELETE', body: { password }, fallback: 'Could not delete the account.' });
export const createTelegramLink = () => request('/auth/telegram/link', { method: 'POST', fallback: 'Could not start linking Telegram.' });
export const unlinkTelegram = () => request('/auth/telegram', { method: 'DELETE', fallback: 'Could not disconnect Telegram.' });
