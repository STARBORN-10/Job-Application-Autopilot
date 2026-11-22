import React, { useEffect, useState } from 'react';
import { formatDistanceToNow } from 'date-fns';
import { Database, Plus, Trash2, Save, AlertCircle, CheckCircle, FlaskConical, Cpu } from 'lucide-react';
import { fetchSources, toggleSource, fetchAtsCompanies, updateAtsCompanies, fetchAiProviders } from '../api';

const muted = { fontSize: '0.75rem', color: 'var(--text-muted)' };

const ago = (iso) => {
  if (!iso) return null;
  try {
    return formatDistanceToNow(new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`), { addSuffix: true });
  } catch {
    return iso;
  }
};

const SourceRow = ({ source, onToggle, busy }) => {
  const h = source.health || {};
  const lastOk = ago(h.last_success_at);
  const lastErr = ago(h.last_error_at);
  const errorIsNewer = h.last_error_at && (!h.last_success_at || h.last_error_at > h.last_success_at);
  return (
    <div style={{ padding: '0.9rem 0', borderBottom: '1px solid var(--border)', display: 'flex', gap: '1rem' }}>
      <label style={{ paddingTop: 2, cursor: source.configured ? 'pointer' : 'not-allowed' }}>
        <input
          type="checkbox"
          checked={source.enabled}
          disabled={busy}
          onChange={(e) => onToggle(source.name, e.target.checked)}
          style={{ width: 18, height: 18, accentColor: 'var(--primary)' }}
          aria-label={`Enable ${source.label}`}
        />
      </label>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
          <strong style={{ fontSize: '0.9rem' }}>{source.label}</strong>
          {source.experimental && (
            <span className="badge badge-warning" style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
              <FlaskConical size={12} /> Experimental
            </span>
          )}
          {source.description_quality === 'snippet' && <span className="badge badge-neutral">Snippets only</span>}
          {!source.configured && (
            <span className="badge badge-danger" title={(source.missing_config || []).join(', ')}>
              Not configured: {(source.missing_config || []).join(', ')}
            </span>
          )}
        </div>
        <div style={{ ...muted, marginTop: '0.25rem' }}>{source.description}</div>
        <div style={{ ...muted, marginTop: '0.35rem', display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
          <span>Runs: {h.total_runs || 0}</span>
          {lastOk && <span style={{ color: 'var(--success)' }}>Last success {lastOk} ({h.last_count ?? 0} jobs)</span>}
          {lastErr && (
            <span style={{ color: errorIsNewer ? 'var(--danger)' : 'var(--text-muted)' }} title={h.last_error || ''}>
              Last error {lastErr}: {(h.last_error || '').slice(0, 120)}
            </span>
          )}
          {source.monthly_budget != null && <span>Monthly budget: {source.monthly_budget} requests</span>}
        </div>
      </div>
    </div>
  );
};

const SourcesSettings = () => {
  const [sources, setSources] = useState([]);
  const [companies, setCompanies] = useState([]);
  const [providers, setProviders] = useState([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);

  useEffect(() => {
    Promise.all([fetchSources(), fetchAtsCompanies(), fetchAiProviders()])
      .then(([s, c, p]) => {
        setSources(s);
        setCompanies(c.companies);
        setProviders(p);
      })
      .catch((err) => setMessage({ type: 'error', text: `Could not load sources: ${err.message}` }));
  }, []);

  const handleToggle = async (name, enabled) => {
    setBusy(true);
    try {
      const updated = await toggleSource(name, enabled);
      setSources((prev) => prev.map((s) => (s.name === name ? updated : s)));
    } catch (err) {
      setMessage({ type: 'error', text: err.message });
    } finally {
      setBusy(false);
    }
  };

  const updateCompany = (i, field, value) =>
    setCompanies((prev) => prev.map((c, idx) => (idx === i ? { ...c, [field]: value } : c)));

  const saveCompanies = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const cleaned = companies.filter((c) => c.token && c.token.trim());
      const res = await updateAtsCompanies(cleaned);
      setCompanies(res.companies);
      setMessage({ type: 'success', text: 'Company list saved.' });
    } catch (err) {
      setMessage({ type: 'error', text: err.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="card settings-card">
        <h2 className="card-title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Database size={20} color="var(--primary)" /> Job Sources
        </h2>
        <p style={{ fontSize: '0.875rem', color: 'var(--text-muted)' }}>
          Each run asks every enabled source for jobs matching your active role and locations. A failing source never
          stops the others; its last error is shown here. Experimental sources scrape public pages, may break, and are
          off by default. Changes apply from the next run.
        </p>
        {message && (
          <div style={{ marginTop: '0.75rem', color: message.type === 'error' ? 'var(--danger)' : 'var(--success)',
            display: 'flex', gap: '0.4rem', alignItems: 'center', fontSize: '0.875rem' }}>
            {message.type === 'error' ? <AlertCircle size={16} /> : <CheckCircle size={16} />} {message.text}
          </div>
        )}
        <div style={{ marginTop: '0.5rem' }}>
          {sources.map((s) => (
            <SourceRow key={s.name} source={s} onToggle={handleToggle} busy={busy} />
          ))}
        </div>
      </div>

      <div className="card settings-card">
        <h2 className="card-title">Company career boards</h2>
        <p style={{ fontSize: '0.875rem', color: 'var(--text-muted)', marginBottom: '1rem' }}>
          Companies whose public Greenhouse, Lever or Ashby board is checked each run (one request per company). The
          board name is the last part of the careers URL, e.g. <code>boards.greenhouse.io/<b>groww</b></code> or{' '}
          <code>jobs.lever.co/<b>cred</b></code>. Only postings in your preferred locations that fit your role are kept.
        </p>
        {companies.map((c, i) => (
          <div key={i} className="ats-row">
            <select className="form-control" value={c.provider} onChange={(e) => updateCompany(i, 'provider', e.target.value)}>
              <option value="greenhouse">Greenhouse</option>
              <option value="lever">Lever</option>
              <option value="ashby">Ashby</option>
            </select>
            <input className="form-control" placeholder="Board name (e.g. groww)" value={c.token}
              onChange={(e) => updateCompany(i, 'token', e.target.value)} />
            <input className="form-control" placeholder="Display name" value={c.name || ''}
              onChange={(e) => updateCompany(i, 'name', e.target.value)} />
            <button type="button" className="btn btn-outline" title="Remove" aria-label="Remove company"
              onClick={() => setCompanies((prev) => prev.filter((_, idx) => idx !== i))}>
              <Trash2 size={14} />
            </button>
          </div>
        ))}
        <div style={{ display: 'flex', gap: '0.75rem', marginTop: '0.75rem' }}>
          <button type="button" className="btn btn-outline" style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}
            onClick={() => setCompanies((prev) => [...prev, { provider: 'greenhouse', token: '', name: '' }])}>
            <Plus size={14} /> Add company
          </button>
          <button type="button" className="btn btn-primary" disabled={busy} onClick={saveCompanies}
            style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
            <Save size={14} /> Save company list
          </button>
        </div>
      </div>

      <div className="card settings-card">
        <h2 className="card-title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Cpu size={20} color="var(--primary)" /> AI providers
        </h2>
        <p style={{ fontSize: '0.875rem', color: 'var(--text-muted)', marginBottom: '0.75rem' }}>
          Tried in this order. When one is rate limited, down or returns bad output, the next one is used. Keys and
          order are set in the backend environment (<code>LLM_PROVIDER_ORDER</code>).
        </p>
        {providers.map((p) => (
          <div key={p.name} style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', fontSize: '0.875rem', marginBottom: '0.4rem' }}>
            <span className={`badge ${p.configured ? 'badge-success' : 'badge-neutral'}`}>
              {p.configured ? 'configured' : 'no key'}
            </span>
            <strong style={{ minWidth: 90 }}>{p.name}</strong>
            <span style={muted}>extract: {p.extract_model} | write: {p.write_model}</span>
          </div>
        ))}
      </div>
    </>
  );
};

export default SourcesSettings;
