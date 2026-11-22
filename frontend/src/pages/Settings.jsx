import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { fetchGeneralSettings, updateGeneralSettings } from '../api';
import { useToast } from '../context/contexts';
import SourcesSettings from '../components/SourcesSettings';
import ScoringSettings from '../components/ScoringSettings';
import FindJobsButton from '../components/FindJobsButton';
import PipelineProgress from '../components/PipelineProgress';
import { ErrorState, PageLoader, Spinner } from '../components/Feedback';
import { Save, SlidersHorizontal, Briefcase, MapPin, Star, PlayCircle } from 'lucide-react';

const TARGET_ROLES = ['AI/ML Engineer', 'Data Analyst', 'Backend Developer', 'Python Developer', 'Automation Engineer'];

const Hint = ({ children }) => <div className="field-hint">{children}</div>;

const Settings = () => {
  const { notify } = useToast();
  const [settings, setSettings] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetchGeneralSettings()
      .then((data) => { if (!cancelled) { setSettings(data); setError(null); } })
      .catch((err) => { if (!cancelled) setError(err.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [reload]);

  const set = (key, parse = (v) => v) => (e) =>
    setSettings((s) => ({ ...s, [key]: parse(e.target.type === 'checkbox' ? e.target.checked : e.target.value) }));

  const handleSave = async (e) => {
    e?.preventDefault();
    setSaving(true);
    try {
      setSettings(await updateGeneralSettings(settings));
      notify({ type: 'success', title: 'Settings saved', message: 'They apply from the next job search.' });
    } catch (err) {
      notify({ type: 'error', title: 'Could not save settings', message: err.message, timeout: 15000 });
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <PageLoader label="Loading settings" />;

  return (
    <div>
      <div className="page-head">
        <div className="page-head-text">
          <h1 className="page-title">Settings</h1>
          <p className="page-description">What to search for, how jobs are filtered and scored, which sources run, and the details used to fill application forms.</p>
        </div>
      </div>

      <section className="card settings-card" aria-labelledby="run-heading">
        <h2 className="card-title" id="run-heading"><PlayCircle size={20} color="var(--primary)" /> Run job search now</h2>
        <p className="muted small">Searches every enabled source with the saved settings below (save first if you changed them). Progress appears here and on the Dashboard.</p>
        <FindJobsButton label="Run job search now" />
        <div style={{ marginTop: '1rem' }}><PipelineProgress /></div>
      </section>

      {error && <ErrorState title="Could not load settings" message={error} onRetry={() => setReload((n) => n + 1)} />}

      {settings && (
        <form onSubmit={handleSave}>
          <section className="card settings-card">
            <h2 className="card-title"><Briefcase size={20} color="var(--primary)" /> Search &amp; matching</h2>
            <div className="form-grid">
              <div className="form-group">
                <label className="form-label" htmlFor="active-role">Active target role</label>
                <select id="active-role" className="form-control" value={settings.active_role} onChange={set('active_role')}>
                  {TARGET_ROLES.map((role) => <option key={role} value={role}>{role}</option>)}
                </select>
                <Hint>Jobs are searched for this role and scored against its active resume.</Hint>
              </div>
              <div className="form-group">
                <label className="form-label" htmlFor="min-score"><Star size={14} color="var(--warning)" /> Minimum match score (0 - 10)</label>
                <input id="min-score" type="number" className="form-control" min="1" max="10" step="0.5" value={settings.min_match_score}
                  onChange={set('min_match_score', (v) => parseFloat(v) || 7.0)} />
                <Hint>Only jobs scoring at or above this are saved.</Hint>
              </div>
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="locations"><MapPin size={14} /> Preferred locations</label>
              <input id="locations" type="text" className="form-control" value={settings.preferred_locations}
                onChange={set('preferred_locations')} placeholder="e.g. Remote, India, Bangalore, Pune" />
              <Hint>Comma-separated. Used to search and to score location fit; jobs clearly elsewhere are dropped.</Hint>
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="roles">All tracked roles</label>
              <input id="roles" type="text" className="form-control" value={settings.target_roles} onChange={set('target_roles')} />
              <Hint>Comma-separated. A job title close to any of these counts as a role fit.</Hint>
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="age">Ignore postings older than (days)</label>
              <input id="age" type="number" className="form-control narrow" min="1" max="365" value={settings.max_job_age_days ?? 30}
                onChange={set('max_job_age_days', (v) => parseInt(v, 10) || 30)} />
              <Hint>Company career boards list only open roles, so they are not age-filtered.</Hint>
            </div>
          </section>

          <section className="card settings-card">
            <h2 className="card-title"><SlidersHorizontal size={20} color="var(--primary)" /> Experience &amp; hard filters</h2>
            <p className="muted small">Jobs failing any of these are dropped before scoring (no AI cost). Leave a field empty for no restriction.</p>
            <div className="form-grid">
              <div className="form-group">
                <label className="form-label" htmlFor="max-years">Maximum required experience (years)</label>
                <input id="max-years" type="number" className="form-control" min="0" max="10" value={settings.max_years_experience}
                  onChange={set('max_years_experience', (v) => parseInt(v, 10) || 0)} />
                <Hint>Jobs explicitly asking for more years than this are skipped.</Hint>
              </div>
              <label className="check-label form-group">
                <input type="checkbox" checked={settings.filter_enabled} onChange={set('filter_enabled')} />
                Apply the experience filter
              </label>
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="job-types">Preferred job types</label>
              <input id="job-types" type="text" className="form-control" placeholder="e.g. Full-time, Internship"
                value={settings.preferred_job_types || ''} onChange={set('preferred_job_types')} />
              <Hint>Full-time, Part-time, Internship, Contract, Temporary. A job whose type is not stated is kept.</Hint>
            </div>
            <div className="form-grid">
              <div className="form-group">
                <label className="form-label" htmlFor="blocked-companies">Blocked companies</label>
                <input id="blocked-companies" type="text" className="form-control" placeholder="e.g. Some Staffing Agency"
                  value={settings.blocked_companies || ''} onChange={set('blocked_companies')} />
              </div>
              <div className="form-group">
                <label className="form-label" htmlFor="blocked-keywords">Blocked keywords</label>
                <input id="blocked-keywords" type="text" className="form-control" placeholder="e.g. unpaid, night shift"
                  value={settings.blocked_keywords || ''} onChange={set('blocked_keywords')} />
              </div>
            </div>
            <Hint>Comma-separated, case-insensitive, whole words. Keywords are matched in the title and description.</Hint>
          </section>

          <div className="save-bar">
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? <Spinner size={15} label="Saving" /> : <Save size={16} />}
              {saving ? 'Saving...' : 'Save search settings'}
            </button>
          </div>
        </form>
      )}

      <section className="card settings-card">
        <p className="muted small">Your contact details for application forms, Telegram alerts and password now live on <Link to="/profile">your Profile</Link>.</p>
      </section>
      <ScoringSettings />
      <SourcesSettings />
    </div>
  );
};

export default Settings;
