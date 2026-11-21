import React, { useEffect, useState } from 'react';
import { Scale, Save, RotateCcw, AlertCircle, CheckCircle, Wand2 } from 'lucide-react';
import { fetchScoringWeights, updateScoringWeights, tuneScoringWeights } from '../api';

const HELP = {
  skills: 'Share of the skills the posting asks for that your resume shows (nice-to-have skills count half).',
  role: 'How well the job title fits your active role and the roles your resume targets.',
  experience: 'Required years / seniority compared with your experience.',
  preferences: 'Preferred location (remote handled) and preferred job type.',
  freshness: 'Newer postings score higher; 0 at the maximum job age.',
};

const ScoringSettings = () => {
  const [weights, setWeights] = useState(null);
  const [defaults, setDefaults] = useState(null);
  const [parts, setParts] = useState([]);
  const [message, setMessage] = useState(null);
  const [saving, setSaving] = useState(false);
  const [suggestion, setSuggestion] = useState(null);

  useEffect(() => {
    fetchScoringWeights()
      .then((d) => {
        setWeights(d.weights);
        setDefaults(d.defaults);
        setParts(d.parts);
      })
      .catch((err) => setMessage({ type: 'error', text: err.message }));
  }, []);

  if (!weights) return null;
  const total = parts.reduce((sum, p) => sum + (Number(weights[p]) || 0), 0);

  const save = async () => {
    setSaving(true);
    setMessage(null);
    try {
      const res = await updateScoringWeights(weights);
      setWeights(res.weights);
      setMessage({ type: 'success', text: 'Weights saved. They apply to jobs scored from now on.' });
    } catch (err) {
      setMessage({ type: 'error', text: err.message });
    } finally {
      setSaving(false);
    }
  };

  const suggest = async (apply) => {
    setMessage(null);
    try {
      const res = await tuneScoringWeights(apply);
      setSuggestion(res);
      if (res.applied) {
        setWeights(res.new_weights);
        setMessage({ type: 'success', text: 'Suggested weights applied.' });
      }
    } catch (err) {
      setMessage({ type: 'error', text: err.message });
    }
  };

  const changed = suggestion && parts.some((p) => suggestion.new_weights[p] !== suggestion.old_weights[p]);

  return (
    <div className="card" style={{ maxWidth: '850px', marginBottom: '2rem' }}>
      <h2 className="card-title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        <Scale size={20} color="var(--primary)" /> Score weights
      </h2>
      <p style={{ fontSize: '0.875rem', color: 'var(--text-muted)', marginBottom: '1rem' }}>
        Each job gets a 0-10 score computed in code from five parts. These weights (percent, must add up to 100) decide
        how much each part counts. AI only extracts facts (skills, years, level); it does not pick the score.
      </p>
      {parts.map((p) => (
        <div key={p} style={{ display: 'grid', gridTemplateColumns: '140px 90px 1fr', gap: '0.75rem', alignItems: 'center', marginBottom: '0.6rem' }}>
          <label className="form-label" style={{ margin: 0, textTransform: 'capitalize' }} htmlFor={`w-${p}`}>{p}</label>
          <input id={`w-${p}`} type="number" min="0" max="100" step="1" className="form-control" value={weights[p]}
            onChange={(e) => setWeights({ ...weights, [p]: parseInt(e.target.value, 10) || 0 })} />
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{HELP[p]}</span>
        </div>
      ))}
      <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', marginTop: '0.75rem', flexWrap: 'wrap' }}>
        <span style={{ fontSize: '0.875rem', fontWeight: 600, color: total === 100 ? 'var(--success)' : 'var(--danger)' }}>
          Total: {total}/100
        </span>
        <button type="button" className="btn btn-primary" disabled={saving || total !== 100} onClick={save}
          style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
          <Save size={14} /> Save weights
        </button>
        <button type="button" className="btn btn-outline" onClick={() => setWeights(defaults)}
          style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
          <RotateCcw size={14} /> Defaults
        </button>
        <button type="button" className="btn btn-outline" onClick={() => suggest(false)}
          style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}
          title="Learn from your Approve / Skip decisions (needs 30+). Shows a suggestion; nothing changes until you apply it.">
          <Wand2 size={14} /> Suggest from my decisions
        </button>
        {message && (
          <span style={{ fontSize: '0.85rem', display: 'inline-flex', gap: 4, alignItems: 'center',
            color: message.type === 'error' ? 'var(--danger)' : 'var(--success)' }}>
            {message.type === 'error' ? <AlertCircle size={15} /> : <CheckCircle size={15} />} {message.text}
          </span>
        )}
      </div>
      {suggestion && (
        <div style={{ marginTop: '1rem', padding: '0.75rem 1rem', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', fontSize: '0.85rem' }}>
          <div style={{ marginBottom: '0.5rem' }}>
            {suggestion.reason} ({suggestion.decisions_used} decisions: {suggestion.approved} approved, {suggestion.skipped} skipped)
          </div>
          {changed && (
            <>
              <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginBottom: '0.5rem' }}>
                {parts.map((p) => (
                  <span key={p} style={{ textTransform: 'capitalize' }}>
                    {p}: {suggestion.old_weights[p]} → <strong>{suggestion.new_weights[p]}</strong>
                  </span>
                ))}
              </div>
              {!suggestion.applied && (
                <button type="button" className="btn btn-primary" onClick={() => suggest(true)}>Apply suggestion</button>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
};

export default ScoringSettings;
