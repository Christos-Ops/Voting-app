import { useEffect, useState } from 'react';
import { api, formatDate, toIsoDate } from './api.js';

function App() {
  const [token, setToken] = useState(() => localStorage.getItem('ballot-token'));
  const [user, setUser] = useState(null);
  const [view, setView] = useState({ page: 'home' });
  const [loading, setLoading] = useState(Boolean(token));

  useEffect(() => {
    if (!token) {
      setLoading(false);
      return;
    }
    api('/auth/me')
      .then(setUser)
      .catch(() => {
        localStorage.removeItem('ballot-token');
        setToken(null);
        setUser(null);
      })
      .finally(() => setLoading(false));
  }, [token]);

  async function signIn(credentials) {
    const result = await api('/auth/login', { method: 'POST', body: JSON.stringify(credentials) });
    localStorage.setItem('ballot-token', result.access_token);
    setToken(result.access_token);
    setUser(await api('/auth/me'));
    setView({ page: 'home' });
  }

  function signOut() {
    localStorage.removeItem('ballot-token');
    setToken(null);
    setUser(null);
    setView({ page: 'home' });
  }

  if (loading) return <LoadingScreen />;

  return (
    <div className="app-shell">
      <header className="topbar">
        <button className="brand" onClick={() => setView({ page: 'home' })} aria-label="Ballot home">
          <span className="brand-mark">B</span><span>ballot<span className="brand-period">.</span></span>
        </button>
        <div className="topbar-right">
          {user ? <>
            <span className="user-chip">{user.email}<span className="role-tag">{user.is_admin ? 'ADMIN' : 'VOTER'}</span></span>
            <button className="button button-quiet button-small" onClick={signOut}>Sign out</button>
          </> : <span className="topbar-note">A considered vote. A stronger community.</span>}
        </div>
      </header>

      {user?.is_admin ? <AdminApp view={view} setView={setView} /> : user ? <VoterApp view={view} setView={setView} /> : <PublicHome onSignIn={signIn} />}
      <footer className="site-footer"><span>Ballot</span><span>Every voice counts.</span></footer>
    </div>
  );
}

function LoadingScreen() {
  return <main className="center-state"><span className="spinner" /><p>Opening your ballot…</p></main>;
}

function PublicHome({ onSignIn }) {
  const [mode, setMode] = useState('login');
  const [form, setForm] = useState({ email: '', password: '' });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');

  async function submit(event) {
    event.preventDefault();
    setError('');
    setNotice('');
    setBusy(true);
    try {
      if (mode === 'register') {
        await api('/auth/register', { method: 'POST', body: JSON.stringify(form) });
        setMode('login');
        setNotice('Your account is ready. Sign in to view elections.');
      } else {
        await onSignIn(form);
      }
    } catch (submitError) {
      setError(submitError.message);
    } finally {
      setBusy(false);
    }
  }

  return <main className="public-layout">
    <section className="welcome-panel">
      <div className="welcome-kicker"><span className="live-dot" /> COMMUNITY ELECTIONS, MADE CLEAR</div>
      <h1>Make your<br /><em>voice count.</em></h1>
      <p className="welcome-copy">A simple, secure place to take part in the decisions that shape your community.</p>
      <div className="welcome-rule"><span>01</span><span>One account. One vote in each election.</span></div>
      <div className="welcome-art" aria-hidden="true"><div className="art-ring ring-one" /><div className="art-ring ring-two" /><div className="art-center">YOUR<br />VOICE</div><span className="art-mark mark-a">✓</span><span className="art-mark mark-b">✳</span></div>
    </section>
    <section className="auth-panel">
      <div className="auth-heading"><span className="eyebrow">{mode === 'login' ? 'WELCOME BACK' : 'GET STARTED'}</span><h2>{mode === 'login' ? 'Sign in to Ballot' : 'Create your account'}</h2><p>{mode === 'login' ? 'Your next vote is waiting.' : 'Join an election with a few simple details.'}</p></div>
      <form onSubmit={submit} className="form-stack">
        <label>Email address<input type="email" autoComplete="email" required value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} placeholder="you@example.com" /></label>
        <label>Password<input type="password" autoComplete={mode === 'login' ? 'current-password' : 'new-password'} required minLength="8" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} placeholder="At least 8 characters" /></label>
        {error && <InlineMessage kind="error">{error}</InlineMessage>}
        {notice && <InlineMessage kind="success">{notice}</InlineMessage>}
        <button className="button button-primary button-wide" disabled={busy}>{busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}<span aria-hidden="true">↗</span></button>
      </form>
      <p className="auth-switch">{mode === 'login' ? 'New to Ballot?' : 'Already have an account?'} <button onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(''); setNotice(''); }}>{mode === 'login' ? 'Create an account' : 'Sign in'}</button></p>
      <p className="auth-footnote">Administrator access is provided by your election organizer.</p>
    </section>
  </main>;
}

function VoterApp({ view, setView }) {
  if (view.page === 'election') return <ElectionPage electionId={view.id} setView={setView} />;
  return <VoterDashboard setView={setView} />;
}

function VoterDashboard({ setView }) {
  const [elections, setElections] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    api('/elections').then((result) => setElections(result.elections)).catch((loadError) => setError(loadError.message)).finally(() => setLoading(false));
  }, []);

  const openCount = elections.filter((election) => election.voting_open && !election.has_voted).length;
  return <main className="page-content voter-page">
    <div className="page-heading-row"><div><span className="eyebrow">YOUR ELECTIONS</span><h1>Welcome to your <em>ballot.</em></h1><p>Take part in an open election or see what’s coming up.</p></div><div className="heading-stat"><strong>{openCount.toString().padStart(2, '0')}</strong><span>OPEN FOR<br />YOUR VOTE</span></div></div>
    {error && <InlineMessage kind="error">{error}</InlineMessage>}
    {loading ? <LoadingInline label="Finding your elections…" /> : elections.length ? <div className="election-list">{elections.map((election, index) => <ElectionCard key={election.id} election={election} index={index} onOpen={() => setView({ page: 'election', id: election.id })} />)}</div> : <EmptyState title="No elections just yet" copy="When an organizer publishes an election, it will appear here." />}
  </main>;
}

function ElectionCard({ election, index, onOpen }) {
  const open = election.voting_open && !election.has_voted;
  const status = election.has_voted ? 'VOTE RECEIVED' : election.voting_open ? 'VOTING OPEN' : election.status === 'CLOSED' ? 'CLOSED' : election.status === 'DRAFT' ? 'DRAFT' : 'UPCOMING';
  const action = election.status === 'CLOSED' ? 'View results' : election.has_voted ? 'View vote status' : open ? 'Cast your vote' : 'View details';
  return <article className={`election-card ${open ? 'election-card-open' : ''}`} style={{ '--delay': `${index * 70}ms` }}>
    <div className="card-index">{String(index + 1).padStart(2, '0')}</div>
    <div className="election-card-main"><div className="status-line"><span className={`status-dot ${open ? 'status-dot-open' : ''}`} />{status}</div><h2>{election.name}</h2><p>{election.description || 'Community election'}</p><div className="card-meta"><span>{election.candidate_count} candidates</span><span>{formatDate(election.start_at)}{election.end_at ? ` – ${formatDate(election.end_at)}` : ''}</span></div></div>
    <button className={`button ${open ? 'button-primary' : 'button-outline'} card-action`} onClick={onOpen}>{action}<span aria-hidden="true">↗</span></button>
  </article>;
}

function ElectionPage({ electionId, setView }) {
  const [election, setElection] = useState(null);
  const [results, setResults] = useState(null);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  async function load() {
    setLoading(true);
    setError('');
    try {
      const response = await api(`/elections/${electionId}`);
      setElection(response.election);
      if (response.election.status === 'CLOSED') {
        setResults(await api(`/elections/${electionId}/results`));
      }
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [electionId]);

  async function submitVote() {
    setBusy(true);
    setError('');
    try {
      await api(`/elections/${electionId}/votes`, { method: 'POST', body: JSON.stringify({ candidate_id: Number(selected) }) });
      setNotice('Your vote is securely queued. Your choice is recorded for this election.');
      await load();
    } catch (voteError) {
      setError(voteError.message);
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <main className="page-content"><LoadingInline label="Loading election details…" /></main>;
  if (error && !election) return <main className="page-content"><button className="text-button" onClick={() => setView({ page: 'home' })}>← All elections</button><InlineMessage kind="error">{error}</InlineMessage></main>;
  if (!election) return null;
  const canVote = election.voting_open && !election.has_voted;
  return <main className="page-content detail-page">
    <button className="text-button back-link" onClick={() => setView({ page: 'home' })}>← All elections</button>
    <section className="detail-heading"><div><div className="status-line"><span className={`status-dot ${canVote ? 'status-dot-open' : ''}`} />{election.has_voted ? 'VOTE RECEIVED' : canVote ? 'VOTING OPEN' : election.status}</div><h1>{election.name}</h1><p>{election.description}</p></div><aside className="date-panel"><span>VOTING WINDOW</span><strong>{formatDate(election.start_at)}</strong><span className="date-arrow">to</span><strong>{formatDate(election.end_at)}</strong></aside></section>
    {error && <InlineMessage kind="error">{error}</InlineMessage>}{notice && <InlineMessage kind="success">{notice}</InlineMessage>}
    {election.status === 'CLOSED' ? <ResultsPanel results={results} /> : election.has_voted ? <section className="closed-panel"><span className="eyebrow">VOTE RECEIVED</span><h2>Your choice is recorded.</h2><p>Election results will be available once the organizer closes this ballot.</p></section> : canVote ? <section className="candidate-section"><div className="section-title"><div><span className="eyebrow">MAKE YOUR CHOICE</span><h2>Select one candidate</h2></div><span className="selection-note">Your selection is private.</span></div>{election.candidates.length ? <div className="candidate-list">{election.candidates.map((candidate, index) => <label key={candidate.id} className={`candidate-option ${String(candidate.id) === selected ? 'candidate-selected' : ''}`}><input type="radio" name="candidate" value={candidate.id} checked={String(candidate.id) === selected} onChange={(event) => setSelected(event.target.value)} /><span className="candidate-number">{String(index + 1).padStart(2, '0')}</span><span className="candidate-copy"><strong>{candidate.name}</strong><small>{candidate.description || 'Candidate'}</small></span><span className="radio-mark" /></label>)}</div> : <EmptyState title="Candidates are not available" copy="Please check back with the election organizer." />}{selected && <div className="confirm-row"><p>You are selecting <strong>{election.candidates.find((candidate) => String(candidate.id) === selected)?.name}</strong>. Your vote cannot be changed.</p><button className="button button-primary" disabled={busy} onClick={submitVote}>{busy ? 'Submitting…' : 'Confirm vote'}<span aria-hidden="true">↗</span></button></div>}</section> : <section className="closed-panel"><span className="eyebrow">{election.status === 'SCHEDULED' ? 'COMING UP' : 'NOT OPEN'}</span><h2>This ballot isn’t open yet.</h2><p>Voting is available only during the published election window.</p></section>}
  </main>;
}

function ResultsPanel({ results }) {
  if (!results) return <LoadingInline label="Loading results…" />;
  const total = results.results.reduce((sum, item) => sum + item.votes, 0);
  return <section className="results-panel"><div className="section-title"><div><span className="eyebrow">ELECTION RESULTS</span><h2>Every vote, counted.</h2></div><span className="result-total">{total} {total === 1 ? 'vote' : 'votes'}</span></div>{results.results.length ? <div className="result-list">{results.results.map((row, index) => <div className="result-row" key={row.candidate_id}><div className="result-name"><span>{String(index + 1).padStart(2, '0')}</span><strong>{row.candidate}</strong><b>{row.votes}</b></div><div className="result-track"><span style={{ width: `${total ? Math.max(4, row.votes / total * 100) : 0}%` }} /></div></div>)}</div> : <EmptyState title="No candidates to show" copy="Results will appear here when the election has candidates." />}</section>;
}

function AdminApp({ view, setView }) {
  if (view.page === 'manage' || view.page === 'edit') return <ManageElection electionId={view.id} view={view} setView={setView} />;
  if (view.page === 'admin-results') return <AdminResults electionId={view.id} setView={setView} />;
  return <AdminDashboard view={view} setView={setView} />;
}

function AdminDashboard({ view, setView }) {
  const [stats, setStats] = useState(null);
  const [elections, setElections] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  async function refresh() {
    setLoading(true);
    try {
      const [summary, listing] = await Promise.all([api('/admin/stats'), api('/admin/elections')]);
      setStats(summary);
      setElections(listing.elections);
      setError('');
    } catch (loadError) { setError(loadError.message); }
    finally { setLoading(false); }
  }
  useEffect(() => { refresh(); }, []);

  return <main className="page-content admin-page">
    <div className="admin-intro"><div><span className="eyebrow">ELECTION OFFICE</span><h1>Good work starts<br /><em>with a fair vote.</em></h1><p>Shape the next decision for your community.</p></div><div className="admin-seal"><span>✳</span><small>YOUR<br />OFFICE</small></div></div>
    <section className="admin-overview"><div className="overview-heading"><div><span className="eyebrow">AT A GLANCE</span><h2>Election overview</h2></div><button className="button button-primary" onClick={() => setView({ page: 'create' })}>＋ Create election</button></div>
      {error && <InlineMessage kind="error">{error}</InlineMessage>}
      {loading ? <LoadingInline label="Loading election office…" /> : <div className="metric-strip"><Metric label="Registered voters" value={stats?.total_users ?? 0} /><Metric label="Elections" value={stats?.total_elections ?? 0} /><Metric label="Active now" value={stats?.active_elections ?? 0} /><Metric label="Votes cast" value={stats?.total_votes ?? 0} /></div>}
    </section>
    {view.page === 'create' && <ElectionForm onCancel={() => setView({ page: 'home' })} onSaved={(id) => setView({ page: 'manage', id })} />}
    <section className="admin-elections"><div className="section-title"><div><span className="eyebrow">YOUR PROGRAMME</span><h2>Elections</h2></div><span className="subtle-count">{elections.length} total</span></div>
      {loading ? null : elections.length ? <div className="admin-election-list">{elections.map((election) => <AdminElectionCard key={election.id} election={election} setView={setView} onRefresh={refresh} />)}</div> : <EmptyState title="Your first election starts here" copy="Create an election, add candidates, then publish it when it’s ready." />}
    </section>
  </main>;
}

function Metric({ label, value }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong></div>;
}

function AdminElectionCard({ election, setView, onRefresh }) {
  const [error, setError] = useState('');
  async function transition(action) {
    setError('');
    try { await api(`/admin/elections/${election.id}/${action}`, { method: 'POST' }); await onRefresh(); }
    catch (actionError) { setError(actionError.message); }
  }
  async function schedule() {
    setError('');
    try { await api(`/admin/elections/${election.id}`, { method: 'PATCH', body: JSON.stringify({ status: 'SCHEDULED' }) }); await onRefresh(); }
    catch (actionError) { setError(actionError.message); }
  }
  return <article className="admin-election-row"><div className="admin-election-main"><span className={`status-pill status-${election.status.toLowerCase()}`}>{election.status}</span><h3>{election.name}</h3><p>{election.candidate_count} candidates <span>·</span> {election.vote_count} votes</p>{error && <span className="inline-error">{error}</span>}</div><div className="admin-row-actions"><button className="button button-outline button-small" onClick={() => setView({ page: 'manage', id: election.id })}>{election.status === 'DRAFT' || election.status === 'SCHEDULED' ? 'Manage' : 'View election'}</button><button className="button button-quiet button-small" onClick={() => setView({ page: 'admin-results', id: election.id })}>Results</button>{election.status === 'DRAFT' && <button className="button button-quiet button-small" onClick={schedule}>Schedule</button>}{election.status === 'SCHEDULED' && <button className="button button-primary button-small" onClick={() => transition('activate')}>Open voting</button>}{election.status === 'ACTIVE' && <button className="button button-danger button-small" onClick={() => transition('close')}>Close</button>}</div></article>;
}

function ElectionForm({ initial, electionId, onCancel, onSaved }) {
  const [form, setForm] = useState({ name: initial?.name || '', description: initial?.description || '', start_at: initial?.start_at ? new Date(initial.start_at).toISOString().slice(0, 16) : '', end_at: initial?.end_at ? new Date(initial.end_at).toISOString().slice(0, 16) : '', status: initial?.status || 'DRAFT' });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault();
    setBusy(true); setError('');
    const payload = { ...form, start_at: toIsoDate(form.start_at), end_at: toIsoDate(form.end_at) };
    try {
      const response = electionId
        ? await api(`/admin/elections/${electionId}`, { method: 'PATCH', body: JSON.stringify(payload) })
        : await api('/admin/elections', { method: 'POST', body: JSON.stringify(payload) });
      onSaved(response.election.id);
    } catch (saveError) { setError(saveError.message); }
    finally { setBusy(false); }
  }
  return <section className="form-section"><div className="section-title"><div><span className="eyebrow">{electionId ? 'EDIT DETAILS' : 'NEW BALLOT'}</span><h2>{electionId ? 'Election details' : 'Create an election'}</h2></div></div><form className="election-form" onSubmit={submit}><label>Election name<input required maxLength="160" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="e.g. 2026 Student Union Election" /></label><label className="full-field">Description<textarea rows="3" maxLength="2000" value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} placeholder="What is this election for?" /></label><label>Voting opens<input type="datetime-local" required value={form.start_at} onChange={(event) => setForm({ ...form, start_at: event.target.value })} /></label><label>Voting closes<input type="datetime-local" required value={form.end_at} onChange={(event) => setForm({ ...form, end_at: event.target.value })} /></label><label>Status<select value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value })}><option value="DRAFT">Draft</option><option value="SCHEDULED">Scheduled</option></select></label>{error && <div className="full-field"><InlineMessage kind="error">{error}</InlineMessage></div>}<div className="form-actions full-field"><button type="button" className="button button-quiet" onClick={onCancel}>Cancel</button><button className="button button-primary" disabled={busy}>{busy ? 'Saving…' : electionId ? 'Save changes' : 'Create election'}<span aria-hidden="true">↗</span></button></div></form></section>;
}

function ManageElection({ electionId, view, setView }) {
  const [election, setElection] = useState(null);
  const [candidates, setCandidates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [candidateForm, setCandidateForm] = useState({ name: '', description: '' });
  const [editing, setEditing] = useState(null);

  async function refresh() {
    const [details, list] = await Promise.all([api(`/elections/${electionId}`), api(`/admin/elections/${electionId}/candidates`)]);
    setElection(details.election);
    setCandidates(list.candidates);
  }
  useEffect(() => { refresh().catch((loadError) => setError(loadError.message)).finally(() => setLoading(false)); }, [electionId]);

  async function saveCandidate(event) {
    event.preventDefault(); setError('');
    try {
      if (editing) await api(`/admin/elections/${electionId}/candidates/${editing}`, { method: 'PATCH', body: JSON.stringify(candidateForm) });
      else await api(`/admin/elections/${electionId}/candidates`, { method: 'POST', body: JSON.stringify(candidateForm) });
      setCandidateForm({ name: '', description: '' }); setEditing(null); await refresh();
    } catch (saveError) { setError(saveError.message); }
  }

  async function removeCandidate(candidate) {
    if (!window.confirm(`Remove ${candidate.name} from this election?`)) return;
    try { await api(`/admin/elections/${electionId}/candidates/${candidate.id}`, { method: 'DELETE' }); await refresh(); }
    catch (removeError) { setError(removeError.message); }
  }

  if (loading) return <main className="page-content"><LoadingInline label="Opening election management…" /></main>;
  if (!election) return <main className="page-content"><InlineMessage kind="error">{error || 'Election not found.'}</InlineMessage></main>;
  const editable = ['DRAFT', 'SCHEDULED'].includes(election.status);
  return <main className="page-content manage-page"><button className="text-button back-link" onClick={() => setView({ page: 'home' })}>← Election office</button><div className="manage-heading"><div><span className={`status-pill status-${election.status.toLowerCase()}`}>{election.status}</span><h1>{election.name}</h1><p>{election.description}</p></div><div className="manage-heading-actions"><button className="button button-outline" onClick={() => setView({ page: 'edit', id: election.id })}>Edit details</button><button className="button button-quiet" onClick={() => setView({ page: 'admin-results', id: election.id })}>View results</button></div></div>
    {error && <InlineMessage kind="error">{error}</InlineMessage>}
    {view.page === 'edit' && <ElectionForm initial={election} electionId={election.id} onCancel={() => setView({ page: 'manage', id: election.id })} onSaved={() => { setView({ page: 'manage', id: election.id }); refresh(); }} />}
    <div className="manage-grid"><section className="candidate-admin"><div className="section-title"><div><span className="eyebrow">THE BALLOT</span><h2>Candidates <small>{candidates.length}</small></h2></div></div>{candidates.length ? <div className="candidate-admin-list">{candidates.map((candidate, index) => <article key={candidate.id} className="candidate-admin-row"><span className="candidate-number">{String(index + 1).padStart(2, '0')}</span><div><strong>{candidate.name}</strong><small>{candidate.description || 'No profile yet'}</small></div>{editable && <div className="candidate-actions"><button className="text-button" onClick={() => { setEditing(candidate.id); setCandidateForm({ name: candidate.name, description: candidate.description }); }}>Edit</button><button className="text-button text-danger" onClick={() => removeCandidate(candidate)}>Remove</button></div>}</article>)}</div> : <EmptyState title="No candidates added" copy="Add candidates before opening voting." />}{editable && <form className="candidate-add-form" onSubmit={saveCandidate}><h3>{editing ? 'Update candidate' : 'Add a candidate'}</h3><label>Candidate name<input required maxLength="120" value={candidateForm.name} onChange={(event) => setCandidateForm({ ...candidateForm, name: event.target.value })} placeholder="Full name" /></label><label>Profile<textarea rows="2" maxLength="500" value={candidateForm.description} onChange={(event) => setCandidateForm({ ...candidateForm, description: event.target.value })} placeholder="A short introduction" /></label><div className="form-actions"><button type="button" className="button button-quiet button-small" onClick={() => { setEditing(null); setCandidateForm({ name: '', description: '' }); }}>Clear</button><button className="button button-primary button-small">{editing ? 'Save candidate' : 'Add candidate'}</button></div></form>}</section><aside className="lifecycle-panel"><span className="eyebrow">NEXT STEP</span><h2>{election.status === 'DRAFT' ? 'Prepare the ballot' : election.status === 'SCHEDULED' ? 'Ready to open?' : election.status === 'ACTIVE' ? 'Voting is live' : 'Election complete'}</h2><p>{election.status === 'DRAFT' ? 'Add candidates and set the election to scheduled when the ballot is ready.' : election.status === 'SCHEDULED' ? 'Open voting when your election window begins. The scheduled dates still control vote eligibility.' : election.status === 'ACTIVE' ? 'Voters can cast one vote during the election window.' : 'This election is closed to new votes.'}</p>{election.status === 'DRAFT' && <button className="button button-primary button-wide" onClick={async () => { try { await api(`/admin/elections/${election.id}`, { method: 'PATCH', body: JSON.stringify({ status: 'SCHEDULED' }) }); await refresh(); } catch (e) { setError(e.message); } }}>Schedule election</button>}{election.status === 'SCHEDULED' && <button className="button button-primary button-wide" disabled={!candidates.length} onClick={async () => { try { await api(`/admin/elections/${election.id}/activate`, { method: 'POST' }); await refresh(); } catch (e) { setError(e.message); } }}>Open voting</button>}{election.status === 'ACTIVE' && <button className="button button-danger button-wide" onClick={async () => { try { await api(`/admin/elections/${election.id}/close`, { method: 'POST' }); await refresh(); } catch (e) { setError(e.message); } }}>Close election</button>}<div className="lifecycle-dates"><div><span>Opens</span><strong>{formatDate(election.start_at)}</strong></div><div><span>Closes</span><strong>{formatDate(election.end_at)}</strong></div></div></aside></div>
  </main>;
}

function AdminResults({ electionId, setView }) {
  const [election, setElection] = useState(null);
  const [results, setResults] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => { Promise.all([api(`/elections/${electionId}`), api(`/elections/${electionId}/results`)]).then(([details, result]) => { setElection(details.election); setResults(result); }).catch((loadError) => setError(loadError.message)); }, [electionId]);
  return <main className="page-content results-page"><button className="text-button back-link" onClick={() => setView({ page: 'home' })}>← Election office</button>{error && <InlineMessage kind="error">{error}</InlineMessage>}{election && <><span className="eyebrow">OFFICIAL TALLY</span><h1>{election.name}</h1><ResultsPanel results={results} /></>}</main>;
}

function InlineMessage({ kind, children }) {
  return <div className={`inline-message message-${kind}`} role={kind === 'error' ? 'alert' : 'status'}>{children}</div>;
}

function LoadingInline({ label }) {
  return <div className="loading-inline"><span className="spinner" />{label}</div>;
}

function EmptyState({ title, copy }) {
  return <div className="empty-state"><span className="empty-symbol">○</span><h3>{title}</h3><p>{copy}</p></div>;
}

export default App;