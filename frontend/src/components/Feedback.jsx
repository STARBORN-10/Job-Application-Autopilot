import React, { useState } from 'react';
import { AlertCircle, Check, Copy, RefreshCw } from 'lucide-react';

export const Spinner = ({ size = 16, label }) => (
  <span className="spinner" style={{ width: size, height: size, borderWidth: Math.max(2, Math.round(size / 8)) }}
    role="status" aria-label={label || 'Loading'} />
);

export const PageLoader = ({ label = 'Loading...' }) => (
  <div className="loader-container" aria-busy="true"><Spinner size={36} label={label} /></div>
);

// A plain-language error with an optional retry button (never a blank screen).
export const ErrorState = ({ title = 'Something went wrong', message, onRetry, compact = false }) => (
  <div className={`alert alert-error${compact ? ' alert-compact' : ''}`} role="alert">
    <AlertCircle size={18} className="alert-icon" aria-hidden="true" />
    <div className="alert-body">
      <div className="alert-title">{title}</div>
      {message && <div>{message}</div>}
    </div>
    {onRetry && (
      <button type="button" className="btn btn-outline btn-sm" onClick={onRetry}>
        <RefreshCw size={14} /> Try again
      </button>
    )}
  </div>
);

export const CopyButton = ({ text, label = 'Copy', copiedLabel = 'Copied', className = 'btn btn-outline btn-sm' }) => {
  const [state, setState] = useState('idle');
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text || '');
      setState('copied');
    } catch {
      setState('failed');
    }
    setTimeout(() => setState('idle'), 1800);
  };
  return (
    <button type="button" className={className} onClick={copy} disabled={!text}>
      {state === 'copied' ? <Check size={14} /> : <Copy size={14} />}
      {state === 'copied' ? copiedLabel : state === 'failed' ? 'Copy failed: select and copy by hand' : label}
    </button>
  );
};
