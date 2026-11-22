import React, { useEffect, useState } from 'react';
import { Bell, ExternalLink, KeyRound, LogOut, Save, Trash2, User } from 'lucide-react';
import {
  changePassword, createTelegramLink, deleteAccount, fetchMe, signOutEverywhere, unlinkTelegram, updateMe,
} from '../api';
import { useAuth, useToast } from '../context/contexts';
import ApplicantProfileSettings from '../components/ApplicantProfileSettings';
import Modal from '../components/Modal';
import { CopyButton, Spinner } from '../components/Feedback';
import { formatDate } from '../lib/format';

const MIN_PASSWORD = 8;

// Suggestions for an empty application profile: the account's name and e-mail (nothing is saved until you press Save).
const accountDefaults = (user) => {
  const [first = '', ...rest] = (user.name || '').trim().split(/\s+/);
  return { first_name: first, last_name: rest.join(' '), email: user.email };
};

const AccountCard = ({ user }) => {
  const { setUser } = useAuth();
  const { notify } = useToast();
  const [name, setName] = useState(user.name || '');
  const [saving, setSaving] = useState(false);
  const save = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const res = await updateMe(name);
      setUser(res.user);
      notify({ type: 'success', title: 'Name saved' });
    } catch (err) {
      notify({ type: 'error', title: 'Could not save your name', message: err.message });
    } finally { setSaving(false); }
  };
  return (
    <section className="card settings-card" aria-labelledby="acct-heading">
      <h2 className="card-title" id="acct-heading"><User size={20} color="var(--primary)" /> Your account</h2>
      <form onSubmit={save}>
        <div className="form-grid">
          <div className="form-group">
            <label className="form-label" htmlFor="acct-name">Name</label>
            <input id="acct-name" className="form-control" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} autoComplete="name" />
          </div>
          <div className="form-group">
            <label className="form-label" htmlFor="acct-email">E-mail (used to sign in)</label>
            <input id="acct-email" className="form-control" value={user.email} disabled readOnly />
          </div>
        </div>
        <p className="muted small" style={{ margin: '0 0 0.9rem' }}>
          Member since {user.created_at ? formatDate(user.created_at) : 'today'}
          {user.is_owner && ' · You are the owner of this server (you can send real e-mail applications through its mail account).'}
        </p>
        <button type="submit" className="btn btn-primary" disabled={saving || name === (user.name || '')}>
          {saving ? <Spinner size={14} label="Saving" /> : <Save size={15} />} {saving ? 'Saving...' : 'Save name'}
        </button>
      </form>
    </section>
  );
};

const TelegramCard = ({ user }) => {
  const { setUser } = useAuth();
  const { notify } = useToast();
  const [link, setLink] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  // While a code is open, watch for the moment the bot confirms the link.
  useEffect(() => {
    if (!link) return undefined;
    const timer = setInterval(async () => {
      try {
        const me = await fetchMe();
        if (me.user.telegram_linked) {
          setUser(me.user);
          setLink(null);
          notify({ type: 'success', title: 'Telegram connected', message: 'Job alerts will arrive in that chat.' });
        } else if (Date.now() > link.expiresAt) {
          setLink(null);
          notify({ type: 'info', title: 'The code expired', message: 'Press Connect Telegram for a new one.' });
        }
      } catch { /* a temporary network problem: keep waiting */ }
    }, 3000);
    return () => clearInterval(timer);
  }, [link, notify, setUser]);

  const start = async () => {
    setBusy(true);
    setError('');
    try {
      const res = await createTelegramLink();
      setLink({ ...res, expiresAt: Date.now() + res.expires_in * 1000 });
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  };
  const disconnect = async () => {
    setBusy(true);
    try {
      const res = await unlinkTelegram();
      setUser(res.user);
      notify({ type: 'success', title: 'Telegram disconnected' });
    } catch (err) { notify({ type: 'error', title: 'Could not disconnect', message: err.message }); } finally { setBusy(false); }
  };

  return (
    <section className="card settings-card" aria-labelledby="tg-heading">
      <h2 className="card-title" id="tg-heading"><Bell size={20} color="var(--primary)" /> Telegram alerts</h2>
      <p className="muted small">
        Get each good match in your own Telegram chat, with Approve and Skip buttons. Only you can act on your jobs from that chat.
      </p>
      {user.telegram_linked ? (
        <div className="badge-row">
          <span className="badge badge-success">Connected</span>
          <button type="button" className="btn btn-outline btn-sm" onClick={disconnect} disabled={busy}>Disconnect</button>
        </div>
      ) : link ? (
        <div className="tg-link">
          <ol className="tg-steps">
            <li>Open the bot{link.bot_username ? <> <strong>@{link.bot_username}</strong></> : ''} in Telegram.</li>
            <li>Send it this message: <code className="tg-code">/start {link.code}</code> <CopyButton text={`/start ${link.code}`} label="Copy" /></li>
            <li>Come back here: this page connects by itself within a few seconds.</li>
          </ol>
          <div className="badge-row">
            {link.deep_link && (
              <a className="btn btn-primary btn-sm" href={link.deep_link} target="_blank" rel="noopener noreferrer">
                <ExternalLink size={14} /> Open Telegram
              </a>
            )}
            <span className="inline-loading"><Spinner size={14} /> Waiting for your message... (the code works for {Math.round(link.expires_in / 60)} minutes)</span>
            <button type="button" className="btn btn-outline btn-sm" onClick={() => setLink(null)}>Cancel</button>
          </div>
        </div>
      ) : (
        <button type="button" className="btn btn-primary" onClick={start} disabled={busy}>
          {busy ? <Spinner size={14} label="Working" /> : <Bell size={15} />} Connect Telegram
        </button>
      )}
      {error && <p className="small text-danger" role="alert" style={{ marginTop: 8 }}>{error}</p>}
    </section>
  );
};

const PasswordCard = () => {
  const { adoptSession } = useAuth();
  const { notify } = useToast();
  const [form, setForm] = useState({ current: '', next: '', again: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    if (form.next.length < MIN_PASSWORD) return setError(`The new password must be at least ${MIN_PASSWORD} characters.`);
    if (form.next !== form.again) return setError('The two new passwords do not match.');
    setBusy(true);
    try {
      const res = await changePassword(form.current, form.next);
      adoptSession(res);   // this device keeps working; every other device is signed out
      setForm({ current: '', next: '', again: '' });
      notify({ type: 'success', title: 'Password changed', message: 'Your other devices were signed out.' });
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  };

  return (
    <section className="card settings-card" aria-labelledby="pw-heading">
      <h2 className="card-title" id="pw-heading"><KeyRound size={20} color="var(--primary)" /> Password</h2>
      <form onSubmit={submit}>
        <div className="form-grid">
          <div className="form-group">
            <label className="form-label" htmlFor="pw-current">Current password</label>
            <input id="pw-current" className="form-control" type="password" autoComplete="current-password" value={form.current} onChange={set('current')} required />
          </div>
          <div className="form-group">
            <label className="form-label" htmlFor="pw-new">New password</label>
            <input id="pw-new" className="form-control" type="password" autoComplete="new-password" value={form.next} onChange={set('next')} required maxLength={128} />
          </div>
          <div className="form-group">
            <label className="form-label" htmlFor="pw-again">Repeat the new password</label>
            <input id="pw-again" className="form-control" type="password" autoComplete="new-password" value={form.again} onChange={set('again')} required maxLength={128} />
          </div>
        </div>
        {error && <p className="small text-danger" role="alert">{error}</p>}
        <button type="submit" className="btn btn-primary" disabled={busy || !form.current || !form.next}>
          {busy ? <Spinner size={14} label="Saving" /> : <Save size={15} />} {busy ? 'Saving...' : 'Change password'}
        </button>
      </form>
    </section>
  );
};

const DangerZone = () => {
  const { adoptSession, logout } = useAuth();
  const { notify } = useToast();
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  const others = async () => {
    setBusy(true);
    try {
      adoptSession(await signOutEverywhere());
      notify({ type: 'success', title: 'Signed out everywhere else' });
    } catch (err) { notify({ type: 'error', title: 'Could not sign out other devices', message: err.message }); } finally { setBusy(false); }
  };
  const remove = async () => {
    setBusy(true);
    setError('');
    try {
      await deleteAccount(password);
      logout();
      notify({ type: 'success', title: 'Your account was deleted', message: 'Your jobs, resumes and settings are gone.' });
    } catch (err) { setError(err.message); setBusy(false); }
  };

  return (
    <section className="card settings-card" aria-labelledby="danger-heading">
      <h2 className="card-title" id="danger-heading"><LogOut size={20} color="var(--danger)" /> Sessions and account</h2>
      <div className="badge-row">
        <button type="button" className="btn btn-outline" onClick={others} disabled={busy}>Sign out on all other devices</button>
        <button type="button" className="btn btn-danger" onClick={() => { setConfirming(true); setPassword(''); setError(''); }} disabled={busy}>
          <Trash2 size={15} /> Delete my account
        </button>
      </div>
      <p className="muted small">Deleting your account permanently removes your jobs, resumes (including the uploaded PDFs), settings, decisions and applications. It cannot be undone.</p>
      {confirming && (
        <Modal title="Delete your account?" onClose={() => setConfirming(false)} busy={busy}
          footer={(
            <>
              <button type="button" className="btn btn-outline" onClick={() => setConfirming(false)} disabled={busy}>Keep my account</button>
              <button type="button" className="btn btn-danger" onClick={remove} disabled={busy || !password}>
                {busy ? <Spinner size={14} label="Deleting" /> : <Trash2 size={15} />} Delete everything
              </button>
            </>
          )}>
          <p>All your data will be deleted for good. Type your password to confirm.</p>
          <div className="form-group" style={{ marginTop: 12 }}>
            <label className="form-label" htmlFor="del-password">Password</label>
            <input id="del-password" className="form-control" type="password" autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.target.value)} autoFocus />
          </div>
          {error && <p className="small text-danger" role="alert">{error}</p>}
        </Modal>
      )}
    </section>
  );
};

const Profile = () => {
  const { user, accountsOn } = useAuth();
  return (
    <div>
      <header className="page-header">
        <h1 className="page-title">Profile</h1>
        <p className="page-description">
          {accountsOn ? 'Your account, contact details, alerts and security.' : 'Your contact details for application forms.'}
        </p>
      </header>
      {accountsOn && user ? (
        <>
          <AccountCard user={user} />
          <ApplicantProfileSettings defaults={accountDefaults(user)} />
          <TelegramCard user={user} />
          <PasswordCard />
          <DangerZone />
        </>
      ) : (
        <>
          <p className="muted small">Accounts are turned off on this server, so there is a single shared profile. Turn accounts on (AUTH_ENABLED) to give every person their own.</p>
          <ApplicantProfileSettings />
        </>
      )}
    </div>
  );
};

export default Profile;
