'use client';

import { FormEvent, ReactNode, useCallback, useEffect, useRef, useState } from 'react';

const configuredApiUrl = process.env.NEXT_PUBLIC_TRIAGE_API_URL?.trim();
const apiUrl = configuredApiUrl || (
  process.env.NODE_ENV === 'production'
    ? 'https://autoresolvehackerrank.vercel.app'
    : 'http://localhost:8080'
);

type View = 'overview' | 'triage' | 'queue' | 'audit' | 'settings';
type Session = { token: string; tenant_id: string; subject: string; roles: string[] };
type Policy = { tenant_id: string; confidence_threshold: number; allowed_providers: string[]; allowed_regions: string[]; version: number; updated_at: string };
type Provider = { name: string; configured_model: string; reachable: boolean; model_available: boolean; models: string[] };
type Escalation = { id: string; ticket_id: string; subject: string; status: string; attempts: number; review_state: string; escalation_reason: string | null; created_at: string; updated_at: string };
type AuditRecord = { sequence_id: number; ticket_id: string; event_type: string; occurred_at: string; attributes: Record<string, unknown> };
type TriageResult = { ticket_id: string; provider: string | null; decision: { action: string; confidence_score: number; suggested_reply: string | null; escalation_reason: string | null; cited_sources: { chunk_id: string; quote: string }[] }; verification_errors: string[] };

class ApiError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

async function request<T>(path: string, token?: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${apiUrl}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...init?.headers },
      signal: init?.signal ?? AbortSignal.timeout(10_000),
    });
  } catch {
    throw new ApiError('The AutoResolve API is unavailable. Check Docker and try again.', 0);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string | { msg?: string }[] } | null;
    const detail = Array.isArray(body?.detail) ? body.detail.map((item) => item.msg).join(', ') : body?.detail;
    throw new ApiError(detail || `Request failed (${response.status})`, response.status);
  }
  return response.status === 204 ? undefined as T : response.json() as Promise<T>;
}

function Mark() { return <span className="brand-mark" aria-hidden="true"><span /><span /><span /></span>; }
function Modal({ open, labelledBy, onClose, children }: { open: boolean; labelledBy: string; onClose: () => void; children: ReactNode }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (open && !element.open) element.showModal();
    if (!open && element.open) element.close();
  }, [open]);
  return <dialog ref={dialog} className="modal" aria-labelledby={labelledBy} onCancel={onClose} onClose={onClose} onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>{children}</dialog>;
}
function age(value: string) {
  const minutes = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 60_000));
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return hours < 24 ? `${hours}h` : `${Math.floor(hours / 24)}d`;
}

const viewLabels: Record<View, string> = {
  overview: 'Operations overview', triage: 'Test triage', queue: 'Escalation queue', audit: 'Audit activity', settings: 'Policy and providers',
};

export default function Home() {
  const [session, setSession] = useState<Session | null>(null);
  const [sessionReady, setSessionReady] = useState(false);
  const [view, setView] = useState<View>('overview');
  const [theme, setTheme] = useState<'light' | 'dark'>('light');
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [escalations, setEscalations] = useState<Escalation[]>([]);
  const [activity, setActivity] = useState<AuditRecord[]>([]);
  const [selectedTicket, setSelectedTicket] = useState<Escalation | null>(null);
  const [operatorResponse, setOperatorResponse] = useState('');
  const [policyOpen, setPolicyOpen] = useState(false);
  const [threshold, setThreshold] = useState(0.8);
  const [allowedProviders, setAllowedProviders] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<TriageResult | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const savedSession = window.sessionStorage.getItem('autoresolve.session');
      const savedTheme = window.localStorage.getItem('autoresolve.theme') === 'dark' ? 'dark' : 'light';
      if (savedSession) {
        try { setSession(JSON.parse(savedSession) as Session); } catch { window.sessionStorage.removeItem('autoresolve.session'); }
      }
      setTheme(savedTheme); document.documentElement.dataset.theme = savedTheme; setSessionReady(true);
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  const signOut = useCallback(() => {
    window.sessionStorage.removeItem('autoresolve.session');
    setSession(null); setPolicy(null); setProviders([]);
  }, []);

  const load = useCallback(async (silent = false) => {
    if (!session) return;
    if (!silent) setLoading(true);
    try {
      const [health, nextPolicy, nextProviders, jobs, events] = await Promise.all([
        request<{ status: string }>('/healthz'),
        request<Policy>('/v1/policy', session.token),
        request<Provider[]>('/v1/providers', session.token),
        request<Escalation[]>('/v1/triage/jobs', session.token),
        request<AuditRecord[]>('/v1/audit?limit=50', session.token),
      ]);
      setApiOnline(health.status === 'ok'); setPolicy(nextPolicy);
      setThreshold(nextPolicy.confidence_threshold); setAllowedProviders(new Set(nextPolicy.allowed_providers));
      setProviders(nextProviders); setEscalations(jobs); setActivity(events); setError(null);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) signOut();
      else { setApiOnline(false); setError(cause instanceof Error ? cause.message : 'Could not load operations data'); }
    } finally { if (!silent) setLoading(false); }
  }, [session, signOut]);

  useEffect(() => {
    if (!session) return;
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load, session]);
  useEffect(() => {
    if (!session) return;
    const timer = window.setInterval(() => void load(true), 30_000);
    return () => window.clearInterval(timer);
  }, [load, session]);

  const login = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setSaving(true); setError(null);
    const data = new FormData(event.currentTarget);
    try {
      const next = await request<Session>('/v1/session', undefined, { method: 'POST', body: JSON.stringify({ username: data.get('username'), password: data.get('password') }) });
      window.sessionStorage.setItem('autoresolve.session', JSON.stringify(next)); setSession(next);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Sign in failed'); }
    finally { setSaving(false); }
  };

  const toggleTheme = () => {
    const next = theme === 'light' ? 'dark' : 'light';
    setTheme(next); document.documentElement.dataset.theme = next;
    window.localStorage.setItem('autoresolve.theme', next);
  };

  const submitTicket = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (!session) return;
    setSaving(true); setError(null); setResult(null);
    const data = new FormData(event.currentTarget);
    const evidence = String(data.get('evidence') || '').trim();
    try {
      const next = await request<TriageResult>('/v1/triage', session.token, {
        method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID(), 'X-Correlation-ID': crypto.randomUUID() },
        signal: AbortSignal.timeout(120_000),
        body: JSON.stringify({
          ticket: { id: `ui-${crypto.randomUUID()}`, tenant_id: session.tenant_id, subject: data.get('subject'), body: data.get('body'), region: 'local' },
          knowledge_base: evidence ? [{ id: 'ui-evidence', tenant_id: session.tenant_id, kb_version: 'ui-1', content: evidence, score: 1 }] : [],
        }),
      });
      setResult(next); await load(true);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Ticket could not be processed'); }
    finally { setSaving(false); }
  };

  const savePolicy = async (event: FormEvent) => {
    event.preventDefault(); if (!session || !policy) return;
    setSaving(true); setError(null);
    try {
      const updated = await request<Policy>('/v1/policy', session.token, { method: 'PUT', body: JSON.stringify({ confidence_threshold: threshold, allowed_providers: [...allowedProviders], allowed_regions: allowedProviders.size ? ['local'] : [] }) });
      setPolicy(updated); setPolicyOpen(false); await load(true);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Policy could not be saved'); }
    finally { setSaving(false); }
  };

  const review = async (action: 'approve_response' | 'keep_escalated') => {
    if (!session || !selectedTicket) return;
    setSaving(true); setError(null);
    try {
      await request<void>(`/v1/triage/jobs/${selectedTicket.id}/review`, session.token, { method: 'POST', body: JSON.stringify({ action, operator_response: action === 'approve_response' ? operatorResponse : null }) });
      setSelectedTicket(null); await load(true);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Review could not be saved'); }
    finally { setSaving(false); }
  };

  if (!sessionReady) return <main className="login-shell"><p>Loading AutoResolve...</p></main>;
  if (!session) return <main className="login-shell"><form className="login-card" onSubmit={login}><Mark /><h1>AutoResolve</h1><p>Sign in to the local operations console.</p><label>Username<input name="username" autoComplete="username" defaultValue="admin" required /></label><label>Password<input name="password" type="password" autoComplete="current-password" required /></label>{error && <p className="form-error" role="alert">{error}</p>}<button className="primary-action" disabled={saving}>{saving ? 'Signing in...' : 'Sign in'}</button><small>Local Docker environment</small></form></main>;

  const readyProviders = providers.filter((provider) => provider.reachable && provider.model_available && allowedProviders.has(provider.name));
  const openReview = (ticket: Escalation) => { setOperatorResponse('A support specialist reviewed your request and will follow up shortly.'); setSelectedTicket(ticket); setError(null); };

  return <main className="shell">
    <a className="skip-link" href="#content">Skip to content</a>
    <aside className="sidebar">
      <button className="brand" onClick={() => setView('overview')}><Mark /><span>AutoResolve</span></button>
      <nav aria-label="Primary navigation"><p className="nav-label">Workspace</p>{(['overview', 'triage', 'queue', 'audit'] as View[]).map((item) => <button key={item} className={`nav-item ${view === item ? 'active' : ''}`} aria-current={view === item ? 'page' : undefined} onClick={() => setView(item)}>{viewLabels[item]}{item === 'queue' && <span className="nav-count">{escalations.length}</span>}</button>)}<p className="nav-label nav-section">Configure</p><button className={`nav-item ${view === 'settings' ? 'active' : ''}`} aria-current={view === 'settings' ? 'page' : undefined} onClick={() => setView('settings')}>Policy and providers</button></nav>
      <div className="tenant-card"><span className="tenant-avatar">{session.subject.slice(0, 1).toUpperCase()}</span><span><strong>{session.subject}</strong><small>{session.tenant_id}</small></span><button onClick={signOut}>Sign out</button></div>
    </aside>

    <section className="workspace" id="content"><header className="topbar"><h1>{viewLabels[view]}</h1><div className="top-actions"><button className="icon-button" onClick={toggleTheme} aria-label={`Use ${theme === 'light' ? 'dark' : 'light'} theme`}>{theme === 'light' ? 'Dark' : 'Light'}</button><button className="refresh-button" onClick={() => void load()} disabled={loading}>{loading ? 'Refreshing...' : 'Refresh'}</button></div></header><div className="content">
      <section className="hero-row" aria-labelledby="system-status"><div><div className="status-line"><span className={`pulse ${apiOnline === false ? 'offline' : ''}`} /><span id="system-status">{apiOnline ? 'AutoResolve API operational' : 'AutoResolve API unavailable'}</span></div><p>{readyProviders.length} model provider{readyProviders.length === 1 ? '' : 's'} ready for this tenant.</p></div></section>
      {error && <div className="api-banner" role="alert"><span>{error}</span><button onClick={() => { setError(null); void load(); }}>Retry</button></div>}

      {view === 'overview' && <><section className="metric-grid" aria-label="Operations metrics" aria-busy={loading}><article className="metric-card featured"><p>Open escalations</p><div className="metric-value">{escalations.length}</div><div className="metric-foot">Awaiting an operator decision</div></article><article className="metric-card"><p>Audit events</p><div className="metric-value">{activity.length}</div><div className="metric-foot">Latest tenant records</div></article><article className="metric-card"><p>Providers ready</p><div className="metric-value">{readyProviders.length}/{providers.length}</div><div className="metric-foot">Reachable, available, and allowed</div></article><article className="metric-card"><p>Policy version</p><div className="metric-value">v{policy?.version ?? '-'}</div><div className="metric-foot">Threshold {policy?.confidence_threshold.toFixed(2) ?? '-'}</div></article></section><section className="overview-actions"><button onClick={() => setView('triage')}><strong>Test a ticket</strong><span>Run the complete triage pipeline</span></button><button onClick={() => setView('settings')}><strong>Check providers</strong><span>Inspect live models and policy</span></button><button onClick={() => setView('queue')}><strong>Review escalations</strong><span>{escalations.length} currently open</span></button></section></>}

      {view === 'triage' && <section className="task-grid"><form className="panel ticket-form" onSubmit={submitTicket}><header className="panel-head"><div><h2>Submit a support ticket</h2><p>Test the real API and configured model fallback chain.</p></div></header><label>Subject<input name="subject" maxLength={500} required placeholder="Unable to access my account" /></label><label>Customer message<textarea name="body" maxLength={50000} required placeholder="Describe the request..." /></label><label>Trusted knowledge-base evidence<textarea name="evidence" placeholder="Optional exact text the model may cite..." /></label><button className="primary-action" disabled={saving || readyProviders.length === 0}>{saving ? 'Processing...' : readyProviders.length ? 'Run triage' : 'No provider ready'}</button></form><article className="panel result-panel" aria-live="polite"><header className="panel-head"><div><h2>Pipeline result</h2><p>Validated decision returned by AutoResolve.</p></div></header>{result ? <div className="result-content"><span className={`decision ${result.decision.action}`}>{result.decision.action}</span><dl><div><dt>Provider</dt><dd>{result.provider ?? 'Fail-safe'}</dd></div><div><dt>Confidence</dt><dd>{result.decision.confidence_score.toFixed(2)}</dd></div></dl><h3>{result.decision.action === 'respond' ? 'Suggested reply' : 'Escalation reason'}</h3><p>{result.decision.suggested_reply ?? result.decision.escalation_reason}</p>{result.verification_errors.length > 0 && <p className="form-error">{result.verification_errors.join(', ')}</p>}</div> : <div className="empty-state"><strong>No test run yet</strong><span>Submit a ticket to see the validated result.</span></div>}</article></section>}

      {view === 'queue' && <article className="panel"><header className="panel-head"><div><h2>Needs human review</h2><p>Open fail-safe escalations, ordered by arrival time.</p></div></header><div className="table-wrap"><table><thead><tr><th>Ticket</th><th>Reason</th><th>Attempts</th><th>Age</th><th><span className="sr-only">Action</span></th></tr></thead><tbody>{escalations.map((item) => <tr key={item.id}><td><strong>{item.subject || 'Untitled ticket'}</strong><small>{item.ticket_id}</small></td><td><span className="risk high">{item.escalation_reason ?? 'Manual review required'}</span></td><td>{item.attempts}</td><td>{age(item.created_at)}</td><td><button className="review-button" onClick={() => openReview(item)}>Review</button></td></tr>)}</tbody></table>{!loading && escalations.length === 0 && <div className="empty-state"><strong>No open escalations</strong><button className="text-action" onClick={() => setView('triage')}>Test the triage pipeline</button></div>}</div></article>}

      {view === 'audit' && <article className="panel"><header className="panel-head"><div><h2>Audit activity</h2><p>Latest append-only tenant pipeline records.</p></div><span className="live-label"><i />Current</span></header><div className="activity-list">{activity.map((item) => <div className="activity-item" key={item.sequence_id}><time dateTime={item.occurred_at}>{new Intl.DateTimeFormat(undefined, { dateStyle: 'short', timeStyle: 'medium' }).format(new Date(item.occurred_at))}</time><span className={`event-dot ${String(item.attributes.action) === 'escalate' ? 'escalated' : ''}`} /><strong>{item.ticket_id}</strong><span>{item.event_type}</span><small>{typeof item.attributes.provider === 'string' ? item.attributes.provider : 'system'}</small></div>)}</div></article>}

      {view === 'settings' && <section className="task-grid"><article className="panel"><header className="panel-head"><div><h2>Model providers</h2><p>Live endpoint and configured-model checks.</p></div></header><div className="provider-list">{providers.map((provider) => { const allowed = allowedProviders.has(provider.name); const statusText = !allowed ? 'Blocked' : !provider.reachable ? 'Offline' : !provider.model_available ? 'Model missing' : 'Ready'; return <div className="provider-primary" key={provider.name}><span className="provider-logo">{provider.name === 'ollama' ? 'OL' : 'LM'}</span><span><strong>{provider.name === 'ollama' ? 'Ollama' : 'LM Studio'}</strong><small>{provider.configured_model} / {provider.models.length} discovered</small></span><i className={`online ${statusText === 'Ready' ? '' : 'offline-label'}`}>{statusText}</i></div>; })}</div></article><article className="panel"><header className="panel-head"><div><h2>Active policy</h2><p>Tenant {session.tenant_id}</p></div><span className="version">v{policy?.version ?? '-'}</span></header><div className="policy-score"><span>Response threshold</span><strong>{policy?.confidence_threshold.toFixed(2) ?? '-'}</strong></div><div className="policy-track"><span style={{ width: `${(policy?.confidence_threshold ?? 0) * 100}%` }} /></div><div className="policy-tags">{[...allowedProviders].map((item) => <span key={item}>{item}</span>)}</div><button className="policy-button" onClick={() => setPolicyOpen(true)} disabled={!policy}>Manage policy</button></article></section>}
    </div></section>

    <Modal open={selectedTicket !== null} labelledBy="review-title" onClose={() => setSelectedTicket(null)}>{selectedTicket && <form onSubmit={(event) => event.preventDefault()}><header><div><p className="dialog-meta">Human review / {selectedTicket.ticket_id}</p><h2 id="review-title">{selectedTicket.subject || 'Untitled ticket'}</h2></div><button type="button" aria-label="Close review" onClick={() => setSelectedTicket(null)}>Close</button></header><label>Operator response<textarea autoFocus value={operatorResponse} maxLength={10000} onChange={(event) => setOperatorResponse(event.target.value)} /></label>{error && <p className="dialog-error" role="alert">{error}</p>}<footer><button type="button" className="secondary" disabled={saving} onClick={() => void review('keep_escalated')}>Keep escalated</button><button type="button" className="primary" disabled={saving || !operatorResponse.trim()} onClick={() => void review('approve_response')}>Approve response</button></footer></form>}</Modal>
    <Modal open={policyOpen && policy !== null} labelledBy="policy-title" onClose={() => setPolicyOpen(false)}>{policy && <form onSubmit={savePolicy}><header><div><p className="dialog-meta">Tenant {session.tenant_id} / v{policy.version}</p><h2 id="policy-title">Response policy</h2></div><button type="button" onClick={() => setPolicyOpen(false)}>Close</button></header><label>Minimum confidence<div className="range-value"><input autoFocus type="range" min="0" max="1" step="0.05" value={threshold} onChange={(event) => setThreshold(Number(event.target.value))} /><output>{threshold.toFixed(2)}</output></div></label><fieldset><legend>Allowed providers</legend>{providers.map((provider) => <label className="check-row" key={provider.name}><input type="checkbox" checked={allowedProviders.has(provider.name)} onChange={(event) => { const next = new Set(allowedProviders); if (event.target.checked) next.add(provider.name); else next.delete(provider.name); setAllowedProviders(next); }} />{provider.name === 'ollama' ? 'Ollama' : 'LM Studio'} / local</label>)}</fieldset>{error && <p className="dialog-error" role="alert">{error}</p>}<footer><button type="button" className="secondary" onClick={() => setPolicyOpen(false)}>Cancel</button><button className="primary" disabled={saving}>{saving ? 'Saving...' : 'Save policy'}</button></footer></form>}</Modal>
  </main>;
}
