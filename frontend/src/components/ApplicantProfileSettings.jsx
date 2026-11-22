import React, { useEffect, useState } from 'react';
import { CheckCircle, MousePointerClick, Save } from 'lucide-react';
import { fetchApplicantProfile, fetchAutofillConfig, updateApplicantProfile } from '../api';
import { useToast } from '../context/contexts';
import { ErrorState, Spinner } from './Feedback';

const FIELDS = [
  ['first_name', 'First name', 'text', 'given-name'],
  ['last_name', 'Last name', 'text', 'family-name'],
  ['email', 'E-mail', 'email', 'email'],
  ['phone', 'Phone', 'tel', 'tel'],
  ['location', 'City, country', 'text', 'address-level2'],
  ['linkedin', 'LinkedIn URL', 'url', 'url'],
  ['github', 'GitHub URL', 'url', 'url'],
  ['portfolio', 'Portfolio / website', 'url', 'url'],
  ['current_company', 'Current company (optional)', 'text', 'organization'],
  ['notice_period', 'Notice period / availability (optional)', 'text', 'off'],
];

// Contact details used to pre-fill Greenhouse / Lever / Ashby forms. Visa, salary, EEO and other personal or
// legal questions are deliberately not stored: the form filler leaves them for you.
const ApplicantProfileSettings = ({ defaults = null }) => {
  const { notify } = useToast();
  const [profile, setProfile] = useState(null);
  const [config, setConfig] = useState(null);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchApplicantProfile(), fetchAutofillConfig().catch(() => null)])
      .then(([p, c]) => {
        if (cancelled) return;
        // Empty fields start with the suggestions (the account's name and e-mail); they are saved only on Save.
        const filled = { ...p };
        Object.entries(defaults || {}).forEach(([k, v]) => { if (!filled[k] && v) filled[k] = v; });
        setProfile(filled); setConfig(c); setError(null);
      })
      .catch((err) => { if (!cancelled) setError(err.message); });
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reload]);

  const save = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      setProfile(await updateApplicantProfile(profile));
      notify({ type: 'success', title: 'Profile saved', message: 'Used the next time a form is pre-filled.' });
    } catch (err) {
      notify({ type: 'error', title: 'Could not save your profile', message: err.message, timeout: 15000 });
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="card settings-card" aria-labelledby="profile-heading">
      <h2 className="card-title" id="profile-heading"><MousePointerClick size={20} color="var(--primary)" /> Application form profile</h2>
      <p className="muted small">
        Used to pre-fill Greenhouse, Lever and Ashby application forms. Questions about work authorisation, visa, salary,
        diversity (EEO) or anything custom are never answered for you; they are listed for you to fill in.
      </p>
      {config && (
        <div className="pill-row">
          <span className={`badge ${config.playwright_installed ? 'badge-success' : 'badge-warning'}`}>
            {config.playwright_installed ? 'Browser automation installed' : 'Playwright not installed'}
          </span>
          <span className={`badge ${config.submit_enabled && !config.dry_run ? 'badge-danger' : 'badge-neutral'}`}>
            {config.submit_enabled && !config.dry_run ? 'Auto-submit ON (only when every check passes)' : 'Never submits: stops before Submit'}
          </span>
          <span className="badge badge-neutral">Pre-fill on approve: {config.on_approve ? 'on' : 'off'}</span>
          <span className="badge badge-neutral">Tailor resume below score {config.tailor_threshold}{config.auto_tailor_on_approve ? ' (on approve)' : ''}</span>
        </div>
      )}
      {config && !config.playwright_installed && <p className="small text-warning">{config.install_hint}</p>}
      {error && <ErrorState title="Could not load your profile" message={error} compact onRetry={() => setReload((n) => n + 1)} />}
      {!profile && !error && <div className="inline-loading"><Spinner size={16} /> Loading...</div>}
      {profile && (
        <form onSubmit={save}>
          <div className="form-grid">
            {FIELDS.map(([key, label, type, ac]) => (
              <div className="form-group" key={key}>
                <label className="form-label" htmlFor={`profile-${key}`}>{label}</label>
                <input id={`profile-${key}`} className="form-control" type={type} autoComplete={ac} value={profile[key] || ''}
                  onChange={(e) => setProfile({ ...profile, [key]: e.target.value })} />
              </div>
            ))}
          </div>
          <button type="submit" className="btn btn-primary" disabled={saving}>
            {saving ? <Spinner size={14} label="Saving" /> : <Save size={15} />} {saving ? 'Saving...' : 'Save profile'}
          </button>
          {config?.profile_missing?.length === 0 && <span className="small text-success" style={{ marginLeft: 12 }}><CheckCircle size={14} /> Basics complete</span>}
        </form>
      )}
    </section>
  );
};

export default ApplicantProfileSettings;
