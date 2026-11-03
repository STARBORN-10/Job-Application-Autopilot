import React, { useEffect, useState } from 'react';
import { fetchGeneralSettings, updateGeneralSettings, triggerAutomation } from '../api';
import {
  Save,
  CheckCircle,
  AlertCircle,
  Send,
  SlidersHorizontal,
  Briefcase,
  MapPin,
  Star,
  Link as LinkIcon,
  HelpCircle,
} from 'lucide-react';

const TARGET_ROLES = [
  'AI/ML Engineer',
  'Data Analyst',
  'Backend Developer',
  'Python Developer',
  'Automation Engineer',
];

const Settings = () => {
  const [settings, setSettings] = useState({
    target_roles: 'AI/ML Engineer, Data Analyst, Backend Developer, Python Developer, Automation Engineer',
    preferred_locations: 'Remote, India, Hybrid',
    min_match_score: 7.0,
    make_webhook_url: '',
    active_role: 'AI/ML Engineer',
    max_years_experience: 1,
    filter_enabled: true,
  });

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testingTrigger, setTestingTrigger] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [triggerMessage, setTriggerMessage] = useState(null);

  useEffect(() => {
    const loadSettings = async () => {
      try {
        const data = await fetchGeneralSettings();
        setSettings(data);
      } catch (err) {
        setErrorMessage('Failed to load settings from backend. Is the server running?');
      } finally {
        setLoading(false);
      }
    };
    loadSettings();
  }, []);

  const handleSave = async (e) => {
    e?.preventDefault();
    setSaving(true);
    setErrorMessage('');
    setSaveSuccess(false);
    try {
      const updated = await updateGeneralSettings(settings);
      setSettings(updated);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err) {
      setErrorMessage(err.message || 'Failed to save settings.');
    } finally {
      setSaving(false);
    }
  };

  const handleTestTrigger = async () => {
    if (!settings.make_webhook_url || !settings.make_webhook_url.trim()) {
      setErrorMessage('Please enter a Make.com Webhook URL before testing.');
      return;
    }
    setTestingTrigger(true);
    setErrorMessage('');
    setTriggerMessage(null);
    try {
      // Save settings first so the backend has the latest webhook URL
      await updateGeneralSettings(settings);
      const res = await triggerAutomation();
      setTriggerMessage({ type: 'success', text: res.message });
    } catch (err) {
      setTriggerMessage({ type: 'error', text: err.message || 'Trigger failed.' });
    } finally {
      setTestingTrigger(false);
    }
  };

  if (loading) {
    return (
      <div className="loader-container">
        <div className="spinner"></div>
      </div>
    );
  }

  return (
    <div>
      <header className="page-header">
        <h1 className="page-title">Settings</h1>
        <p className="page-description">Configure your AI Job Application Autopilot preferences and Make.com integrations.</p>
      </header>

      {saveSuccess && (
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
        }}>
          <CheckCircle size={18} /> Settings saved successfully!
        </div>
      )}

      {errorMessage && (
        <div style={{
          backgroundColor: 'rgba(239, 68, 68, 0.1)',
          color: 'var(--danger)',
          border: '1px solid rgba(239, 68, 68, 0.2)',
          padding: '0.75rem 1.25rem',
          borderRadius: 'var(--radius-md)',
          marginBottom: '1.5rem',
          display: 'flex',
          alignItems: 'center',
          gap: '0.5rem',
          fontWeight: 500,
        }}>
          <AlertCircle size={18} /> {errorMessage}
        </div>
      )}

      <form onSubmit={handleSave}>
        {/* Section 1: Job Search Preferences */}
        <div className="card" style={{ maxWidth: '850px', marginBottom: '2rem' }}>
          <h2 className="card-title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Briefcase size={20} color="var(--primary)" />
            Job Search & Matching Preferences
          </h2>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
            <div className="form-group" style={{ margin: 0 }}>
              <label className="form-label">Active Target Role for AI Matching</label>
              <select
                className="form-control"
                value={settings.active_role}
                onChange={(e) => setSettings({ ...settings, active_role: e.target.value })}
              >
                {TARGET_ROLES.map((role) => (
                  <option key={role} value={role}>{role}</option>
                ))}
              </select>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
                Make.com evaluates jobs using the active resume for this role.
              </div>
            </div>

            <div className="form-group" style={{ margin: 0 }}>
              <label className="form-label" style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                <Star size={14} color="var(--warning)" /> Minimum Match Score (0 - 10)
              </label>
              <input
                type="number"
                className="form-control"
                min="1"
                max="10"
                step="0.5"
                value={settings.min_match_score}
                onChange={(e) => setSettings({ ...settings, min_match_score: parseFloat(e.target.value) || 7.0 })}
              />
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
                Only jobs scoring at or above this threshold pass to the dashboard.
              </div>
            </div>
          </div>

          <div className="form-group" style={{ marginTop: '1.5rem' }}>
            <label className="form-label" style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
              <MapPin size={14} /> Preferred Locations
            </label>
            <input
              type="text"
              className="form-control"
              value={settings.preferred_locations}
              onChange={(e) => setSettings({ ...settings, preferred_locations: e.target.value })}
              placeholder="e.g. Remote, India, Bangalore, Pune"
            />
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
              Comma-separated locations favored in AI evaluation.
            </div>
          </div>

          <div className="form-group">
            <label className="form-label">All Tracked Target Roles</label>
            <input
              type="text"
              className="form-control"
              value={settings.target_roles}
              onChange={(e) => setSettings({ ...settings, target_roles: e.target.value })}
            />
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
              Comma-separated list of target role profiles configured in your system.
            </div>
          </div>
        </div>

        {/* Section 2: Experience Filter */}
        <div className="card" style={{ maxWidth: '850px', marginBottom: '2rem' }}>
          <h2 className="card-title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <SlidersHorizontal size={20} color="var(--primary)" />
            Experience Filter (Fresher / Entry-Level Guard)
          </h2>
          <p style={{ fontSize: '0.875rem', color: 'var(--text-muted)', marginBottom: '1.25rem' }}>
            Incoming jobs requiring more than your configured maximum experience will be automatically rejected.
          </p>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
            <div className="form-group" style={{ margin: 0 }}>
              <label className="form-label">Maximum Required Experience (years)</label>
              <input
                type="number"
                className="form-control"
                min="0"
                max="10"
                value={settings.max_years_experience}
                onChange={(e) => setSettings({ ...settings, max_years_experience: parseInt(e.target.value, 10) || 0 })}
              />
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
                Default: 1. Jobs requiring 2+ or 3+ years will be rejected with HTTP 422.
              </div>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', paddingTop: '1.25rem' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', cursor: 'pointer', fontSize: '0.9rem', fontWeight: 500 }}>
                <input
                  type="checkbox"
                  checked={settings.filter_enabled}
                  onChange={(e) => setSettings({ ...settings, filter_enabled: e.target.checked })}
                  style={{ width: 18, height: 18, accentColor: 'var(--primary)' }}
                />
                Enforce Experience Filter on Incoming Jobs
              </label>
            </div>
          </div>
        </div>

        {/* Section 3: Make.com Automation Integration */}
        <div className="card" style={{ maxWidth: '850px', marginBottom: '2rem' }}>
          <h2 className="card-title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <LinkIcon size={20} color="var(--primary)" />
            Make.com Automation Webhook
          </h2>
          <p style={{ fontSize: '0.875rem', color: 'var(--text-muted)', marginBottom: '1.25rem' }}>
            Configure your Make.com Webhook URL to enable one-click <strong>"Find New Jobs"</strong> directly from your dashboard.
          </p>

          <div className="form-group">
            <label className="form-label">Make.com Webhook URL</label>
            <input
              type="url"
              className="form-control"
              placeholder="https://hook.eu2.make.com/your-custom-webhook-token"
              value={settings.make_webhook_url || ''}
              onChange={(e) => setSettings({ ...settings, make_webhook_url: e.target.value })}
            />
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.35rem' }}>
              Create a <strong>Custom Webhook</strong> module in your Make.com scenario and paste the URL here.
            </div>
          </div>

          <div style={{ marginTop: '1rem', display: 'flex', gap: '1rem', alignItems: 'center', flexWrap: 'wrap' }}>
            <button
              type="button"
              className="btn btn-outline"
              onClick={handleTestTrigger}
              disabled={testingTrigger || !settings.make_webhook_url}
              style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem' }}
            >
              {testingTrigger ? <span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} /> : <Send size={15} />}
              {testingTrigger ? 'Testing Trigger…' : 'Test Webhook Trigger'}
            </button>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              Triggers a test dispatch with your active role context.
            </span>
          </div>

          {triggerMessage && (
            <div style={{
              marginTop: '1rem',
              padding: '0.75rem 1rem',
              borderRadius: 'var(--radius-md)',
              fontSize: '0.875rem',
              backgroundColor: triggerMessage.type === 'success' ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
              color: triggerMessage.type === 'success' ? 'var(--success)' : 'var(--danger)',
              border: `1px solid ${triggerMessage.type === 'success' ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)'}`,
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
            }}>
              {triggerMessage.type === 'success' ? <CheckCircle size={16} /> : <AlertCircle size={16} />}
              {triggerMessage.text}
            </div>
          )}
        </div>

        {/* Save button */}
        <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={saving}
            style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem', padding: '0.6rem 1.5rem' }}
          >
            {saving ? <span className="spinner" style={{ width: 16, height: 16, borderWidth: 2 }} /> : <Save size={16} />}
            {saving ? 'Saving Preferences…' : 'Save All Preferences'}
          </button>
          {saveSuccess && (
            <span style={{ color: 'var(--success)', fontSize: '0.875rem', display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
              <CheckCircle size={16} /> All preferences saved to database
            </span>
          )}
        </div>
      </form>
    </div>
  );
};

export default Settings;
