import React, { useState } from 'react';
import { AlertCircle, Eye, EyeOff, LogIn, Send, UserPlus } from 'lucide-react';
import { useAuth } from '../context/contexts';
import { Spinner } from '../components/Feedback';

const EMAIL_RE = /^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$/;
const MIN_PASSWORD = 8;

// Sign in / create account. Shown instead of the app until the visitor is signed in.
const AuthPage = () => {
  const { config, login, register } = useAuth();
  const canRegister = Boolean(config?.signup_open);
  const [mode, setMode] = useState('login');
  const [form, setForm] = useState({ name: '', email: '', password: '', confirm: '', code: '' });
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const registering = mode === 'register';

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const switchTo = (next) => { setMode(next); setError(''); };

  const validate = () => {
    if (!EMAIL_RE.test(form.email.trim())) return 'Enter a valid e-mail address.';
    if (registering && form.password.length < MIN_PASSWORD) return `The password must be at least ${MIN_PASSWORD} characters.`;
    if (!form.password) return 'Enter your password.';
    if (registering && form.password !== form.confirm) return 'The two passwords do not match.';
    if (registering && config?.signup_code_required && !form.code.trim()) return 'Enter the invite code you were given.';
    return '';
  };

  const submit = async (e) => {
    e.preventDefault();
    const problem = validate();
    if (problem) { setError(problem); return; }
    setBusy(true);
    setError('');
    try {
      if (registering) {
        await register({ email: form.email.trim(), password: form.password, name: form.name.trim() || null,
          signup_code: form.code.trim() || null });
      } else {
        await login(form.email.trim(), form.password);
      }
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card card">
        <div className="auth-brand"><Send size={22} color="var(--primary)" aria-hidden="true" /> <span>Autopilot</span></div>
        <h1 className="auth-title">{registering ? 'Create your account' : 'Welcome back'}</h1>
        <p className="muted auth-sub">
          {registering
            ? 'Your jobs, resumes and settings are private to your account.'
            : 'Sign in to see your jobs, resumes and applications.'}
        </p>

        {registering && config?.first_account && (
          <div className="alert alert-success alert-compact" role="note">
            <div className="alert-body">This is the first account on this server. It keeps the jobs, resume and settings that
              already exist.</div>
          </div>
        )}

        <form onSubmit={submit} noValidate>
          {registering && (
            <div className="form-group">
              <label className="form-label" htmlFor="auth-name">Your name</label>
              <input id="auth-name" className="form-control" type="text" autoComplete="name" value={form.name} onChange={set('name')} maxLength={120} />
            </div>
          )}
          <div className="form-group">
            <label className="form-label" htmlFor="auth-email">E-mail</label>
            <input id="auth-email" className="form-control" type="email" autoComplete="username" value={form.email}
              onChange={set('email')} required autoFocus />
          </div>
          <div className="form-group">
            <label className="form-label" htmlFor="auth-password">Password</label>
            <div className="password-field">
              <input id="auth-password" className="form-control" type={show ? 'text' : 'password'}
                autoComplete={registering ? 'new-password' : 'current-password'} value={form.password} onChange={set('password')}
                required maxLength={128} aria-describedby={registering ? 'auth-pw-hint' : undefined} />
              <button type="button" className="icon-btn" onClick={() => setShow((v) => !v)} aria-label={show ? 'Hide password' : 'Show password'}>
                {show ? <EyeOff size={17} /> : <Eye size={17} />}
              </button>
            </div>
            {registering && <div className="muted small" id="auth-pw-hint">At least {MIN_PASSWORD} characters.</div>}
          </div>
          {registering && (
            <div className="form-group">
              <label className="form-label" htmlFor="auth-confirm">Repeat the password</label>
              <input id="auth-confirm" className="form-control" type={show ? 'text' : 'password'} autoComplete="new-password"
                value={form.confirm} onChange={set('confirm')} required maxLength={128} />
            </div>
          )}
          {registering && config?.signup_code_required && (
            <div className="form-group">
              <label className="form-label" htmlFor="auth-code">Invite code</label>
              <input id="auth-code" className="form-control" type="text" autoComplete="off" value={form.code} onChange={set('code')} />
              <div className="muted small">This server only accepts people who have the invite code.</div>
            </div>
          )}

          {error && (
            <div className="alert alert-error alert-compact" role="alert">
              <AlertCircle size={18} className="alert-icon" aria-hidden="true" />
              <div className="alert-body">{error}</div>
            </div>
          )}

          <button type="submit" className="btn btn-primary auth-submit" disabled={busy}>
            {busy ? <Spinner size={15} label="Working" /> : registering ? <UserPlus size={16} /> : <LogIn size={16} />}
            {busy ? 'Please wait...' : registering ? 'Create account' : 'Sign in'}
          </button>
        </form>

        <p className="auth-switch muted small">
          {registering ? (
            <>Already have an account? <button type="button" className="link-btn" onClick={() => switchTo('login')}>Sign in</button></>
          ) : canRegister ? (
            <>New here? <button type="button" className="link-btn" onClick={() => switchTo('register')}>Create an account</button></>
          ) : (
            <>New accounts are closed on this server. Ask its owner for an invite.</>
          )}
        </p>
        <p className="auth-foot muted small"><a href="/workflow.html" target="_blank" rel="noopener">See how the system works</a></p>
      </div>
    </div>
  );
};

export default AuthPage;
