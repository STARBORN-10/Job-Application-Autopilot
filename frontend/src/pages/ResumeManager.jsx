import React, { useEffect, useRef, useState } from 'react';
import {
  fetchResumes,
  uploadResume,
  replaceResumeFile,
  updateResumeRole,
  deleteResume,
  activateResume,
  fetchResumeText,
  fetchExperienceFilter,
  updateExperienceFilter,
} from '../api';
import {
  Upload,
  FileText,
  Trash2,
  RefreshCw,
  CheckCircle,
  AlertCircle,
  ChevronDown,
  SlidersHorizontal,
  X,
  Eye,
  Star,
} from 'lucide-react';

const TARGET_ROLES = [
  'AI/ML Engineer',
  'Data Analyst',
  'Backend Developer',
  'Python Developer',
  'Automation Engineer',
];

const formatBytes = (bytes) => {
  if (!bytes) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
};

const formatDate = (iso) => {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
  });
};

// ---------------------------------------------------------------------------
// Upload Card
// ---------------------------------------------------------------------------
const UploadCard = ({ onUploaded }) => {
  const [role, setRole] = useState(TARGET_ROLES[0]);
  const [file, setFile] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const inputRef = useRef();

  const handleFileSelect = (f) => {
    setError('');
    if (!f) return;
    if (!f.name.toLowerCase().endsWith('.pdf')) {
      setError('Only PDF files are accepted.');
      return;
    }
    if (f.size > 10 * 1024 * 1024) {
      setError('File must be under 10 MB.');
      return;
    }
    setFile(f);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    handleFileSelect(e.dataTransfer.files?.[0]);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!file) { setError('Please select a PDF file.'); return; }
    setUploading(true);
    setError('');
    try {
      const result = await uploadResume(file, role);
      setFile(null);
      if (inputRef.current) inputRef.current.value = '';
      onUploaded(result);
    } catch (err) {
      setError(err.message || 'Upload failed. Please try again.');
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="card" style={{ marginBottom: '2rem' }}>
      <h2 className="card-title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        <Upload size={20} color="var(--primary)" />
        Upload New Resume
      </h2>

      <form onSubmit={handleSubmit}>
        <div className="form-group">
          <label className="form-label">Target Role</label>
          <div style={{ position: 'relative' }}>
            <select
              className="form-control"
              value={role}
              onChange={(e) => setRole(e.target.value)}
              style={{ appearance: 'none', paddingRight: '2.5rem' }}
            >
              {TARGET_ROLES.map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
            <ChevronDown
              size={16}
              style={{ position: 'absolute', right: '0.75rem', top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none', color: 'var(--text-muted)' }}
            />
          </div>
        </div>

        {/* Drop zone */}
        <div
          className="form-group"
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          onClick={() => inputRef.current?.click()}
          style={{
            border: `2px dashed ${dragging ? 'var(--primary)' : file ? 'var(--success)' : 'var(--border)'}`,
            borderRadius: 'var(--radius-md)',
            padding: '2rem',
            textAlign: 'center',
            cursor: 'pointer',
            transition: 'border-color 0.2s ease, background-color 0.2s ease',
            backgroundColor: dragging ? 'rgba(79,70,229,0.04)' : file ? 'rgba(16,185,129,0.04)' : 'transparent',
          }}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".pdf"
            style={{ display: 'none' }}
            onChange={(e) => handleFileSelect(e.target.files?.[0])}
          />
          {file ? (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.5rem' }}>
              <CheckCircle size={32} color="var(--success)" />
              <span style={{ fontWeight: 600 }}>{file.name}</span>
              <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>{formatBytes(file.size)}</span>
              <button
                type="button"
                className="btn btn-outline"
                style={{ marginTop: '0.5rem', fontSize: '0.75rem', padding: '0.25rem 0.75rem' }}
                onClick={(e) => { e.stopPropagation(); setFile(null); if (inputRef.current) inputRef.current.value = ''; }}
              >
                <X size={12} /> Remove
              </button>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.5rem' }}>
              <FileText size={36} color="var(--text-muted)" />
              <span style={{ fontWeight: 600, color: 'var(--text-main)' }}>Drop your PDF here or click to browse</span>
              <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Max 10 MB · PDF only</span>
            </div>
          )}
        </div>

        {error && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--danger)', fontSize: '0.875rem', marginBottom: '1rem' }}>
            <AlertCircle size={16} /> {error}
          </div>
        )}

        <button
          type="submit"
          className="btn btn-primary"
          disabled={uploading}
          style={{ minWidth: '140px' }}
        >
          {uploading ? (
            <>
              <span className="spinner" style={{ width: 16, height: 16, borderWidth: 2 }} />
              Uploading…
            </>
          ) : (
            <><Upload size={16} /> Upload Resume</>
          )}
        </button>
      </form>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Experience Filter Card
// ---------------------------------------------------------------------------
const ExperienceFilterCard = () => {
  const [settings, setSettings] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    fetchExperienceFilter()
      .then(setSettings)
      .catch(() => setError('Failed to load filter settings.'));
  }, []);

  const handleSave = async () => {
    setSaving(true); setError(''); setSaved(false);
    try {
      const result = await updateExperienceFilter(settings);
      setSettings(result);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch {
      setError('Failed to save settings.');
    } finally {
      setSaving(false);
    }
  };

  if (!settings) {
    return (
      <div className="card" style={{ marginBottom: '2rem' }}>
        <div className="loader-container" style={{ minHeight: 80 }}><div className="spinner" /></div>
      </div>
    );
  }

  return (
    <div className="card" style={{ marginBottom: '2rem' }}>
      <h2 className="card-title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        <SlidersHorizontal size={20} color="var(--primary)" />
        Experience Filter
      </h2>
      <p style={{ fontSize: '0.875rem', color: 'var(--text-muted)', marginBottom: '1.5rem' }}>
        Make.com will use the active role's resume and apply this filter when evaluating jobs.
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
        <div className="form-group" style={{ margin: 0 }}>
          <label className="form-label">Active Role for Matching</label>
          <div style={{ position: 'relative' }}>
            <select
              className="form-control"
              value={settings.active_role}
              onChange={(e) => setSettings({ ...settings, active_role: e.target.value })}
              style={{ appearance: 'none', paddingRight: '2.5rem' }}
            >
              {TARGET_ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
            <ChevronDown size={16} style={{ position: 'absolute', right: '0.75rem', top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none', color: 'var(--text-muted)' }} />
          </div>
          <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.35rem' }}>
            Resume for this role is sent to Make.com for AI matching.
          </p>
        </div>

        <div className="form-group" style={{ margin: 0 }}>
          <label className="form-label">Max Required Experience (years)</label>
          <input
            type="number"
            className="form-control"
            min={0}
            max={10}
            value={settings.max_years_experience}
            onChange={(e) => setSettings({ ...settings, max_years_experience: parseInt(e.target.value, 10) || 0 })}
          />
          <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.35rem' }}>
            Jobs requiring more years will be rejected. Default: 1 (fresher/entry-level).
          </p>
        </div>
      </div>

      <div style={{ marginTop: '1.25rem', display: 'flex', alignItems: 'center', gap: '1rem' }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontSize: '0.875rem', fontWeight: 500 }}>
          <input
            type="checkbox"
            checked={settings.filter_enabled}
            onChange={(e) => setSettings({ ...settings, filter_enabled: e.target.checked })}
            style={{ width: 16, height: 16, accentColor: 'var(--primary)' }}
          />
          Enable experience filter
        </label>
      </div>

      {error && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--danger)', fontSize: '0.875rem', marginTop: '1rem' }}>
          <AlertCircle size={16} /> {error}
        </div>
      )}

      <div style={{ marginTop: '1.25rem', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        <button className="btn btn-primary" onClick={handleSave} disabled={saving} style={{ minWidth: 120 }}>
          {saving ? 'Saving…' : 'Save Filter'}
        </button>
        {saved && (
          <span style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', color: 'var(--success)', fontSize: '0.875rem' }}>
            <CheckCircle size={16} /> Saved!
          </span>
        )}
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Resume Row
// ---------------------------------------------------------------------------
const ResumeRow = ({ resume, onDelete, onReplace, onRoleChange, onActivate, onViewText }) => {
  const replaceRef = useRef();
  const [roleSaving, setRoleSaving] = useState(false);
  const [replacing, setReplacing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [activating, setActivating] = useState(false);
  const [editRole, setEditRole] = useState(resume.target_role);
  const [rowError, setRowError] = useState('');

  const handleRoleChange = async (newRole) => {
    setEditRole(newRole);
    setRoleSaving(true);
    setRowError('');
    try {
      const updated = await updateResumeRole(resume.id, newRole);
      onRoleChange(updated);
    } catch (err) {
      setRowError(err.message);
    } finally {
      setRoleSaving(false);
    }
  };

  const handleActivate = async () => {
    setActivating(true);
    setRowError('');
    try {
      const updated = await activateResume(resume.id);
      onActivate(updated);
    } catch (err) {
      setRowError(err.message);
    } finally {
      setActivating(false);
    }
  };

  const handleReplace = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (!f.name.toLowerCase().endsWith('.pdf')) { setRowError('Only PDF files accepted.'); return; }
    setReplacing(true); setRowError('');
    try {
      const updated = await replaceResumeFile(resume.id, f);
      onReplace(updated);
    } catch (err) {
      setRowError(err.message);
    } finally {
      setReplacing(false);
      e.target.value = '';
    }
  };

  const handleDelete = async () => {
    if (!window.confirm(`Delete "${resume.filename}"? This cannot be undone.`)) return;
    setDeleting(true);
    try {
      await deleteResume(resume.id);
      onDelete(resume.id);
    } catch (err) {
      setRowError(err.message);
      setDeleting(false);
    }
  };

  return (
    <div
      className="job-item"
      style={{
        flexDirection: 'column',
        alignItems: 'flex-start',
        gap: '0.75rem',
        padding: '1.25rem',
        borderLeft: resume.is_active ? '4px solid var(--success)' : '1px solid var(--border)',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', width: '100%', flexWrap: 'wrap', gap: '0.75rem' }}>
        {/* Left: file info */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flex: 1, minWidth: 240 }}>
          <div style={{
            width: 44, height: 44, flexShrink: 0,
            background: resume.is_active ? 'rgba(16,185,129,0.1)' : 'rgba(79,70,229,0.08)',
            borderRadius: 'var(--radius-md)',
            display: 'flex', alignItems: 'center', justifyContent: 'center'
          }}>
            <FileText size={22} color={resume.is_active ? 'var(--success)' : 'var(--primary)'} />
          </div>
          <div style={{ minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
              <span style={{ fontWeight: 600, fontSize: '0.95rem' }}>
                {resume.filename}
              </span>
              {resume.is_active ? (
                <span className="badge badge-success" style={{ fontSize: '0.7rem', display: 'inline-flex', alignItems: 'center', gap: '0.25rem', padding: '0.2rem 0.5rem' }}>
                  <CheckCircle size={12} /> Active for {resume.target_role}
                </span>
              ) : (
                <span className="badge badge-neutral" style={{ fontSize: '0.7rem' }}>
                  Inactive
                </span>
              )}
            </div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
              {formatBytes(resume.file_size)} · Uploaded {formatDate(resume.uploaded_at)}
            </div>
          </div>
        </div>

        {/* Right: role selector + actions */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
          {/* Active selection toggle */}
          {!resume.is_active && (
            <button
              className="btn btn-outline"
              onClick={handleActivate}
              disabled={activating}
              title="Set as active resume for matching"
              style={{ padding: '0.4rem 0.65rem', fontSize: '0.8rem', color: 'var(--success)', borderColor: 'rgba(16,185,129,0.3)', display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}
            >
              {activating ? <span className="spinner" style={{ width: 13, height: 13, borderWidth: 2 }} /> : <Star size={13} />}
              {activating ? 'Activating…' : 'Set Active'}
            </button>
          )}

          {/* View text preview */}
          <button
            className="btn btn-outline"
            onClick={() => onViewText(resume)}
            title="Inspect extracted text that AI receives"
            style={{ padding: '0.4rem 0.65rem', fontSize: '0.8rem', display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}
          >
            <Eye size={13} /> View Text
          </button>

          {/* Role selector */}
          <div style={{ position: 'relative' }}>
            <select
              className="form-control"
              value={editRole}
              onChange={(e) => handleRoleChange(e.target.value)}
              disabled={roleSaving}
              style={{ appearance: 'none', paddingRight: '2rem', fontSize: '0.8rem', padding: '0.4rem 1.8rem 0.4rem 0.6rem' }}
            >
              {TARGET_ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
            <ChevronDown size={13} style={{ position: 'absolute', right: '0.4rem', top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none', color: 'var(--text-muted)' }} />
          </div>

          {/* Replace */}
          <input ref={replaceRef} type="file" accept=".pdf" style={{ display: 'none' }} onChange={handleReplace} />
          <button
            className="btn btn-outline"
            onClick={() => replaceRef.current?.click()}
            disabled={replacing}
            title="Replace PDF file"
            style={{ padding: '0.4rem 0.65rem', fontSize: '0.8rem', display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}
          >
            {replacing ? <span className="spinner" style={{ width: 13, height: 13, borderWidth: 2 }} /> : <RefreshCw size={13} />}
            {replacing ? 'Replacing…' : 'Replace'}
          </button>

          {/* Delete */}
          <button
            className="btn"
            onClick={handleDelete}
            disabled={deleting}
            title="Delete resume"
            style={{ padding: '0.4rem 0.65rem', fontSize: '0.8rem', backgroundColor: 'rgba(239,68,68,0.08)', color: 'var(--danger)', border: '1px solid rgba(239,68,68,0.2)', display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}
          >
            {deleting ? <span className="spinner" style={{ width: 13, height: 13, borderWidth: 2 }} /> : <Trash2 size={13} />}
            {deleting ? 'Deleting…' : 'Delete'}
          </button>
        </div>
      </div>

      {rowError && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', color: 'var(--danger)', fontSize: '0.8rem', width: '100%' }}>
          <AlertCircle size={14} /> {rowError}
        </div>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------
const ResumeManager = () => {
  const [resumes, setResumes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState('');
  const [statusToast, setStatusToast] = useState('');

  // Modal preview
  const [previewResume, setPreviewResume] = useState(null);
  const [previewText, setPreviewText] = useState('');
  const [loadingPreview, setLoadingPreview] = useState(false);

  const showToast = (msg) => {
    setStatusToast(msg);
    setTimeout(() => setStatusToast(''), 3000);
  };

  const load = async () => {
    setLoading(true);
    try {
      const data = await fetchResumes();
      setResumes(data);
    } catch {
      setFetchError('Could not load resumes. Make sure the backend is running.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const handleUploaded = (newResume) => {
    // When a new resume is uploaded, mark any previous ones for that role as inactive
    setResumes((prev) => [
      newResume,
      ...prev.map((r) => r.target_role === newResume.target_role ? { ...r, is_active: false } : r),
    ]);
    showToast(`Uploaded "${newResume.filename}" and set as active for ${newResume.target_role}!`);
  };

  const handleDelete = (id) => {
    setResumes((prev) => {
      const deleted = prev.find((r) => r.id === id);
      const remaining = prev.filter((r) => r.id !== id);
      // If deleted was active, ensure the latest remaining for that role is active
      if (deleted?.is_active) {
        const nextForRole = remaining.find((r) => r.target_role === deleted.target_role);
        if (nextForRole) {
          return remaining.map((r) => r.id === nextForRole.id ? { ...r, is_active: true } : r);
        }
      }
      return remaining;
    });
    showToast('Resume deleted successfully.');
  };

  const handleReplace = (updated) => {
    setResumes((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
    showToast(`Replaced PDF for "${updated.filename}". Text re-extracted.`);
  };

  const handleRoleChange = (updated) => {
    setResumes((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
    showToast(`Role updated to ${updated.target_role}.`);
  };

  const handleActivate = (activated) => {
    setResumes((prev) =>
      prev.map((r) => {
        if (r.target_role === activated.target_role) {
          return { ...r, is_active: r.id === activated.id };
        }
        return r;
      })
    );
    showToast(`"${activated.filename}" is now the active resume for ${activated.target_role}.`);
  };

  const handleViewText = async (resume) => {
    setPreviewResume(resume);
    setLoadingPreview(true);
    setPreviewText('');
    try {
      const data = await fetchResumeText(resume.id);
      setPreviewText(data.extracted_text || 'No text extracted from this PDF.');
    } catch {
      setPreviewText('Failed to load extracted text.');
    } finally {
      setLoadingPreview(false);
    }
  };

  // Group by role for display
  const groupedByRole = TARGET_ROLES.reduce((acc, role) => {
    acc[role] = resumes.filter((r) => r.target_role === role);
    return acc;
  }, {});

  return (
    <div>
      <header className="page-header">
        <h1 className="page-title">Resume Manager</h1>
        <p className="page-description">
          Upload and manage tailored resumes for each target role. The active resume for your chosen role is automatically sent to Make.com and Google Gemini for AI job matching and cover letter generation.
        </p>
      </header>

      {statusToast && (
        <div style={{
          backgroundColor: 'var(--success)',
          color: 'white',
          padding: '0.75rem 1.25rem',
          borderRadius: 'var(--radius-md)',
          marginBottom: '1.5rem',
          display: 'flex',
          alignItems: 'center',
          gap: '0.5rem',
          fontWeight: 500,
          animation: 'fadeIn 0.2s ease',
        }}>
          <CheckCircle size={18} /> {statusToast}
        </div>
      )}

      <UploadCard onUploaded={handleUploaded} />

      <ExperienceFilterCard />

      {/* Resume list */}
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
          <h2 className="card-title" style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <FileText size={20} color="var(--primary)" />
            Uploaded Resumes ({resumes.length})
          </h2>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
            Each target role has one active resume for AI matching
          </span>
        </div>

        {fetchError && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--danger)', fontSize: '0.875rem', marginBottom: '1rem' }}>
            <AlertCircle size={16} /> {fetchError}
          </div>
        )}

        {loading ? (
          <div className="loader-container" style={{ minHeight: 120 }}>
            <div className="spinner" />
          </div>
        ) : resumes.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '3rem 1rem', color: 'var(--text-muted)' }}>
            <FileText size={48} style={{ marginBottom: '1rem', opacity: 0.3 }} />
            <p style={{ fontWeight: 600, marginBottom: '0.35rem' }}>No resumes uploaded yet</p>
            <p style={{ fontSize: '0.875rem' }}>Use the upload card above to upload your first resume PDF.</p>
          </div>
        ) : (
          <>
            {TARGET_ROLES.map((role) => {
              const group = groupedByRole[role];
              if (group.length === 0) return null;
              const activeCount = group.filter((r) => r.is_active).length;
              return (
                <div key={role} style={{ marginBottom: '1.75rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem' }}>
                    <span
                      className="badge badge-primary"
                      style={{ fontSize: '0.8rem', padding: '0.3rem 0.8rem' }}
                    >
                      {role}
                    </span>
                    <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                      {group.length} resume{group.length !== 1 ? 's' : ''} ({activeCount} active)
                    </span>
                  </div>
                  <div className="job-list">
                    {group.map((resume) => (
                      <ResumeRow
                        key={resume.id}
                        resume={resume}
                        onDelete={handleDelete}
                        onReplace={handleReplace}
                        onRoleChange={handleRoleChange}
                        onActivate={handleActivate}
                        onViewText={handleViewText}
                      />
                    ))}
                  </div>
                </div>
              );
            })}
          </>
        )}
      </div>

      {/* Extracted Text Preview Modal */}
      {previewResume && (
        <div style={{
          position: 'fixed',
          inset: 0,
          backgroundColor: 'rgba(0,0,0,0.5)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1000,
          padding: '1rem',
        }}>
          <div className="card" style={{ maxWidth: '750px', width: '100%', maxHeight: '85vh', display: 'flex', flexDirection: 'column' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', borderBottom: '1px solid var(--border)', paddingBottom: '0.75rem' }}>
              <div>
                <h3 style={{ margin: 0, fontSize: '1.1rem' }}>Extracted Resume Text</h3>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
                  {previewResume.filename} · Role: <strong>{previewResume.target_role}</strong>
                </div>
              </div>
              <button
                className="btn btn-outline"
                onClick={() => setPreviewResume(null)}
                style={{ padding: '0.3rem 0.5rem' }}
              >
                <X size={18} />
              </button>
            </div>

            <div style={{ flex: 1, overflowY: 'auto', backgroundColor: 'var(--bg-main)', padding: '1rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border)' }}>
              {loadingPreview ? (
                <div className="loader-container" style={{ minHeight: 150 }}><div className="spinner" /></div>
              ) : (
                <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: '0.82rem', margin: 0, color: 'var(--text-main)', lineHeight: 1.6 }}>
                  {previewText}
                </pre>
              )}
            </div>

            <div style={{ marginTop: '1rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                This is the exact plain text sent to Google Gemini for candidate-job matching and personalized cover letters.
              </span>
              <button className="btn btn-primary" onClick={() => setPreviewResume(null)}>
                Close Preview
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Make.com integration info */}
      <div className="card" style={{ marginTop: '2rem', borderLeft: '4px solid var(--primary)', background: 'rgba(79,70,229,0.03)' }}>
        <h2 className="card-title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '1rem' }}>
          Make.com Integration Endpoints
        </h2>
        <p style={{ fontSize: '0.875rem', color: 'var(--text-muted)', marginBottom: '1rem' }}>
          Make.com securely queries your active target role, extracted resume text, and experience filter rules in a single call:
        </p>
        <div style={{ background: 'var(--sidebar-bg)', color: '#e2e8f0', borderRadius: 'var(--radius-md)', padding: '1rem', fontFamily: 'monospace', fontSize: '0.82rem', overflowX: 'auto' }}>
          <div style={{ color: '#94a3b8', marginBottom: '0.5rem' }}>// 1. Unified Context Endpoint (Role, Resume Text & Experience Settings)</div>
          <div><span style={{ color: '#7dd3fc' }}>GET</span> <span style={{ color: '#6ee7b7' }}>http://YOUR_SERVER:8000/api/make/context</span></div>
          <div style={{ marginTop: '0.75rem', color: '#94a3b8' }}>// 2. Specific Role Resume Endpoint</div>
          <div><span style={{ color: '#7dd3fc' }}>GET</span> <span style={{ color: '#6ee7b7' }}>http://YOUR_SERVER:8000/api/make/resume?role=AI%2FML+Engineer</span></div>
          <div style={{ marginTop: '0.75rem', color: '#94a3b8' }}>// Required Header for all Make.com endpoints:</div>
          <div><span style={{ color: '#fca5a5' }}>X-API-Key</span>: <span style={{ color: '#fde68a' }}>your-secret-key-from-MAKE_API_KEY-env-var</span></div>
        </div>
      </div>
    </div>
  );
};

export default ResumeManager;
