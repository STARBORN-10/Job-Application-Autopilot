import React from 'react';
import { Info } from 'lucide-react';

const PART_LABELS = {
  skills: 'Skills',
  role: 'Role / title fit',
  experience: 'Experience level',
  preferences: 'Location & job type',
  freshness: 'Freshness',
};
const PART_ORDER = ['skills', 'role', 'experience', 'preferences', 'freshness'];

const barColor = (v) => (v >= 0.75 ? 'var(--success)' : v >= 0.45 ? 'var(--warning)' : 'var(--danger)');

const Chip = ({ children, tone }) => (
  <span
    style={{
      display: 'inline-block',
      padding: '0.15rem 0.55rem',
      margin: '0 0.35rem 0.35rem 0',
      borderRadius: 'var(--radius-full)',
      fontSize: '0.75rem',
      fontWeight: 500,
      background: tone === 'good' ? 'rgba(16,185,129,0.12)' : tone === 'bad' ? 'rgba(239,68,68,0.1)' : 'var(--bg-main)',
      color: tone === 'good' ? 'var(--success)' : tone === 'bad' ? 'var(--danger)' : 'var(--text-muted)',
      border: '1px solid var(--border)',
    }}
  >
    {children}
  </span>
);

// Compact version for the listing: five thin bars and the skill count.
export const ScoreBreakdownCompact = ({ breakdown }) => {
  if (!breakdown || !breakdown.parts) return null;
  const matched = breakdown.matched_skills || [];
  const total = matched.length + (breakdown.missing_skills || []).length;
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '0.35rem 0.75rem', fontSize: '0.75rem', color: 'var(--text-muted)', margin: '0.35rem 0' }}>
      <div style={{ display: 'flex', gap: 3 }} aria-label="Score parts">
        {PART_ORDER.map((p) => {
          const v = breakdown.parts[p]?.value ?? 0;
          return (
            <div key={p} title={`${PART_LABELS[p]}: ${Math.round(v * 100)}%`}
              style={{ width: 22, height: 6, borderRadius: 3, background: 'var(--border)', overflow: 'hidden' }}>
              <div style={{ width: `${Math.round(v * 100)}%`, height: '100%', background: barColor(v) }} />
            </div>
          );
        })}
      </div>
      {total > 0 && <span>{matched.length}/{total} skills</span>}
      {breakdown.description_quality === 'snippet' && <span>snippet</span>}
      {breakdown.cap && <span title={breakdown.cap.reason}>capped</span>}
    </div>
  );
};

const ScoreBreakdown = ({ breakdown }) => {
  if (!breakdown || !breakdown.parts) {
    return (
      <div style={{ fontSize: '0.875rem', color: 'var(--text-muted)' }}>
        No score breakdown for this job (it was scored before explainable scoring was added).
      </div>
    );
  }
  const matched = breakdown.matched_skills || [];
  const missing = breakdown.missing_skills || [];
  const niceMatched = breakdown.nice_to_have_matched || [];
  const niceMissing = breakdown.nice_to_have_missing || [];
  return (
    <div>
      {breakdown.description_quality === 'snippet' && (
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'flex-start', padding: '0.6rem 0.8rem', marginBottom: '1rem',
          borderRadius: 'var(--radius-md)', background: 'rgba(245,158,11,0.1)', color: '#92400e', fontSize: '0.8rem' }}>
          <Info size={15} style={{ flexShrink: 0, marginTop: 2 }} />
          Only a short snippet of this posting was available, so the skills part counts for less
          (confidence {Math.round((breakdown.confidence || 0) * 100)}%). Open the original posting for the full requirements.
        </div>
      )}
      {breakdown.cap && (
        <div style={{ fontSize: '0.8rem', color: 'var(--danger)', marginBottom: '0.75rem' }}>
          Capped at {breakdown.cap.limit} (would be {breakdown.cap.uncapped}): {breakdown.cap.reason}.
        </div>
      )}
      <div style={{ display: 'grid', gap: '0.6rem' }}>
        {PART_ORDER.map((p) => {
          const part = breakdown.parts[p];
          if (!part) return null;
          const pct = Math.round(part.value * 100);
          return (
            <div key={p}>
              <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: '0 0.5rem', fontSize: '0.8rem', marginBottom: 3 }}>
                <span style={{ fontWeight: 600 }}>{PART_LABELS[p]} <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>· weight {part.weight}%</span></span>
                <span style={{ color: 'var(--text-muted)' }}>{pct}% → {part.points} pts</span>
              </div>
              <div style={{ height: 8, background: 'var(--border)', borderRadius: 4, overflow: 'hidden' }}>
                <div style={{ width: `${pct}%`, height: '100%', background: barColor(part.value) }} />
              </div>
              {part.detail && <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: 2 }}>{part.detail}</div>}
            </div>
          );
        })}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(220px, 100%), 1fr))', gap: '1rem', marginTop: '1.25rem' }}>
        <div>
          <div className="stat-label" style={{ color: 'var(--success)', marginBottom: 6 }}>Skills you have</div>
          {matched.length || niceMatched.length ? (
            <>
              {matched.map((s) => <Chip key={s} tone="good">{s}</Chip>)}
              {niceMatched.map((s) => <Chip key={s} tone="good">{s} (bonus)</Chip>)}
            </>
          ) : <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>None found</span>}
        </div>
        <div>
          <div className="stat-label" style={{ color: 'var(--danger)', marginBottom: 6 }}>Missing</div>
          {missing.length || niceMissing.length ? (
            <>
              {missing.map((s) => <Chip key={s} tone="bad">{s}</Chip>)}
              {niceMissing.map((s) => <Chip key={s}>{s} (nice to have)</Chip>)}
            </>
          ) : <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Nothing missing</span>}
        </div>
      </div>
      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.75rem' }}>
        Facts from {breakdown.facts_source === 'llm' ? `AI (${breakdown.llm_provider || 'provider'})` : 'keyword scan'}
        {breakdown.job_facts?.level && breakdown.job_facts.level !== 'unknown' ? ` · level ${breakdown.job_facts.level}` : ''}
        {breakdown.job_facts?.work_mode && breakdown.job_facts.work_mode !== 'unknown' ? ` · ${breakdown.job_facts.work_mode}` : ''}
        {(breakdown.dropped_unverified_skills || []).length > 0 &&
          ` · ignored skills not in the posting text: ${breakdown.dropped_unverified_skills.join(', ')}`}
      </div>
    </div>
  );
};

export default ScoreBreakdown;
