const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

// Root of the backend (API_URL without the trailing /api) - used for health checks.
export const API_ROOT = API_URL.replace(/\/api\/?$/, '');

// Free hosts (e.g. Render) can take a minute or more to wake up. Without a timeout a request would
// hang forever and the page would just keep spinning, so every request is capped.
const REQUEST_TIMEOUT_MS = 60000;

const apiFetch = async (url, options = {}, timeoutMs = REQUEST_TIMEOUT_MS) => {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } catch (err) {
    if (err.name === 'AbortError') {
      throw new Error('The server is taking too long to respond. It may be waking up - please try again in a minute.');
    }
    throw new Error('Cannot reach the server. Check your connection or try again shortly.');
  } finally {
    clearTimeout(timer);
  }
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

export const fetchJobs = async () => {
  const response = await apiFetch(`${API_URL}/jobs?limit=2000`);
  if (!response.ok) throw new Error('Failed to fetch jobs');
  return response.json();
};

export const fetchAnalytics = async (days = 30) => {
  const response = await apiFetch(`${API_URL}/analytics?days=${days}`);
  if (!response.ok) throw new Error('Failed to fetch analytics');
  return response.json();
};

export const analyzeJob = async (id) => {
  const response = await apiFetch(`${API_URL}/jobs/${id}/analyze`, { method: 'POST' });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Analysis failed' }));
    throw new Error(err.detail || 'Analysis failed');
  }
  return response.json();
};

export const EXPORT_CSV_URL = `${API_URL}/export/jobs.csv`;

export const fetchJob = async (id) => {
  const response = await apiFetch(`${API_URL}/jobs/${id}`);
  if (!response.ok) throw new Error('Failed to fetch job');
  return response.json();
};

export const updateJob = async (id, data) => {
  const response = await apiFetch(`${API_URL}/jobs/${id}`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(data),
  });
  if (!response.ok) throw new Error('Failed to update job');
  return response.json();
};

export const deleteJob = async (id) => {
  const response = await apiFetch(`${API_URL}/jobs/${id}`, {
    method: 'DELETE',
  });
  if (!response.ok) throw new Error('Failed to delete job');
  return response.json();
};

// ---------------------------------------------------------------------------
// Resumes
// ---------------------------------------------------------------------------

export const fetchResumes = async () => {
  const response = await apiFetch(`${API_URL}/resumes`);
  if (!response.ok) throw new Error('Failed to fetch resumes');
  return response.json();
};

export const uploadResume = async (file, targetRole) => {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('target_role', targetRole);
  const response = await apiFetch(`${API_URL}/resumes`, {
    method: 'POST',
    body: formData,
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Upload failed' }));
    throw new Error(err.detail || 'Upload failed');
  }
  return response.json();
};

export const replaceResumeFile = async (id, file) => {
  const formData = new FormData();
  formData.append('file', file);
  const response = await apiFetch(`${API_URL}/resumes/${id}/replace`, {
    method: 'PUT',
    body: formData,
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Replace failed' }));
    throw new Error(err.detail || 'Replace failed');
  }
  return response.json();
};

export const updateResumeRole = async (id, targetRole) => {
  const response = await apiFetch(`${API_URL}/resumes/${id}/role`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target_role: targetRole }),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Update failed' }));
    throw new Error(err.detail || 'Update failed');
  }
  return response.json();
};

export const deleteResume = async (id) => {
  const response = await apiFetch(`${API_URL}/resumes/${id}`, { method: 'DELETE' });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Delete failed' }));
    throw new Error(err.detail || 'Delete failed');
  }
  return response.json();
};

export const activateResume = async (id) => {
  const response = await apiFetch(`${API_URL}/resumes/${id}/activate`, {
    method: 'PUT',
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Activation failed' }));
    throw new Error(err.detail || 'Activation failed');
  }
  return response.json();
};

export const fetchResumeText = async (id) => {
  const response = await apiFetch(`${API_URL}/resumes/${id}/text`);
  if (!response.ok) throw new Error('Failed to fetch resume text');
  return response.json();
};

// ---------------------------------------------------------------------------
// Settings – Experience Filter & General Preferences
// ---------------------------------------------------------------------------

export const fetchExperienceFilter = async () => {
  const response = await apiFetch(`${API_URL}/settings/experience-filter`);
  if (!response.ok) throw new Error('Failed to fetch settings');
  return response.json();
};

export const updateExperienceFilter = async (data) => {
  const response = await apiFetch(`${API_URL}/settings/experience-filter`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!response.ok) throw new Error('Failed to update settings');
  return response.json();
};

export const fetchGeneralSettings = async () => {
  const response = await apiFetch(`${API_URL}/settings`);
  if (!response.ok) throw new Error('Failed to load settings');
  return response.json();
};

export const updateGeneralSettings = async (data) => {
  const response = await apiFetch(`${API_URL}/settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Failed to save settings' }));
    throw new Error(err.detail || 'Failed to save settings');
  }
  return response.json();
};

// ---------------------------------------------------------------------------
// Automation Webhook Trigger
// ---------------------------------------------------------------------------

export const fetchAutomationStatus = async () => {
  const response = await apiFetch(`${API_URL}/automation/status`);
  if (!response.ok) throw new Error('Failed to fetch automation status');
  return response.json();
};

export const triggerAutomation = async () => {
  const response = await apiFetch(`${API_URL}/automation/trigger`, {
    method: 'POST',
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Failed to trigger automation' }));
    throw new Error(err.detail || 'Failed to trigger automation');
  }
  return response.json();
};
