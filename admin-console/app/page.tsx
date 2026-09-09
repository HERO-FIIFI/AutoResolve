'use client';

import { FormEvent, useCallback, useEffect, useState } from 'react';

const apiUrl = process.env.NEXT_PUBLIC_TRIAGE_API_URL ?? 'http://localhost:8080';
const tenantId = 'example';
const apiHeaders = {
  'Content-Type': 'application/json',
  'X-Tenant-ID': tenantId,
  'X-Roles': 'triage:read,triage:write,policy:read,policy:write,audit:read',
  'X-Subject': 'operations-console',
};

type Policy = {
  tenant_id: string;
  confidence_threshold: number;
  allowed_providers: string[];
  allowed_regions: string[];
  version: number;
  updated_at: string;
};

type Escalation = {
  id: string;
  ticket_id: string;
  subject: string;
  status: string;
  attempts: number;
  review_state: string;
  escalation_reason: string | null;
  created_at: string;
  updated_at: string;
};

type AuditRecord = {
  sequence_id: number;
  ticket_id: string;
  event_type: string;
  occurred_at: string;
  attributes: Record<string, unknown>;
};

function Mark() {
  return <span className="brand-mark" aria-hidden="true"><span /><span /><span /></span>;
}

function age(value: string) {
  const minutes = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 60_000));
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return hours < 24 ? `${hours}h` : `${Math.floor(hours / 24)}d`;
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${apiUrl}${path}`, {
      ...init,
      headers: apiHeaders,
      signal: init?.signal ?? AbortSignal.timeout(8_000),
    });
  } catch {
    throw new Error('Local API is unavailable. Docker is reconnecting; retrying automatically.');
  }
  if (!response.ok) {
    const detail = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(detail?.detail ?? `Request failed (${response.status})`);
  }
  return response.status === 204 ? undefined as T : response.json() as Promise<T>;
}

export default function Home() {
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [escalations, setEscalations] = useState<Escalation[]>([]);
  const [activity, setActivity] = useState<AuditRecord[]>([]);
  const [selectedTicket, setSelectedTicket] = useState<Escalation | null>(null);
  const [operatorResponse, setOperatorResponse] = useState('');
  const [policyOpen, setPolicyOpen] = useState(false);
  const [threshold, setThreshold] = useState(0.8);
  const [lmStudioAllowed, setLmStudioAllowed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const [health, currentPolicy, jobs, events] = await Promise.all([
        api<{ status: string }>('/healthz'),
        api<Policy>('/v1/policy'),
        api<Escalation[]>('/v1/triage/jobs'),
        api<AuditRecord[]>('/v1/audit?limit=20'),
      ]);
      setApiOnline(health.status === 'ok');
      setPolicy(currentPolicy);
      setThreshold(currentPolicy.confidence_threshold);
      setLmStudioAllowed(currentPolicy.allowed_providers.includes('lmstudio'));
      setEscalations(jobs);
      setActivity(events);
      setError(null);
    } catch (cause) {
      setApiOnline(false);
      setError(cause instanceof Error ? cause.message : 'Could not load operations data');
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);
  useEffect(() => {
    if (apiOnline !== false) return;
    const timer = window.setInterval(() => void load(true), 10_000);
    return () => window.clearInterval(timer);
  }, [apiOnline, load]);
  useEffect(() => {
    if (!selectedTicket && !policyOpen) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !saving) {
        setSelectedTicket(null);
        setPolicyOpen(false);
      }
    };
    window.addEventListener('keydown', close);
    return () => window.removeEventListener('keydown', close);
  }, [policyOpen, saving, selectedTicket]);

  const openReview = (ticket: Escalation) => {
    setOperatorResponse('Thanks for flagging this. A support specialist reviewed your request and will follow up shortly.');
    setSelectedTicket(ticket);
    setError(null);
  };

  const openPolicy = () => {
    if (!policy) return;
    setThreshold(policy.confidence_threshold);
    setLmStudioAllowed(policy.allowed_providers.includes('lmstudio'));
    setError(null);
    setPolicyOpen(true);
  };

  const review = async (action: 'approve_response' | 'keep_escalated') => {
    if (!selectedTicket) return;
    setSaving(true);
    setError(null);
    try {
      await api<void>(`/v1/triage/jobs/${selectedTicket.id}/review`, {
        method: 'POST',
        body: JSON.stringify({ action, operator_response: action === 'approve_response' ? operatorResponse : null }),
      });
      setEscalations((items) => items.filter((item) => item.id !== selectedTicket.id));
      setSelectedTicket(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Review could not be saved');
    } finally {
      setSaving(false);
    }
  };

  const savePolicy = async (event: FormEvent) => {
    event.preventDefault();
    if (!policy) return;
    setSaving(true);
    setError(null);
    const providers = new Set(policy.allowed_providers);
    const regions = new Set(policy.allowed_regions);
    if (lmStudioAllowed) {
      providers.add('lmstudio');
      regions.add('local');
    } else {
      providers.delete('lmstudio');
      regions.delete('local');
    }
    try {
      const updated = await api<Policy>('/v1/policy', {
        method: 'PUT',
        body: JSON.stringify({
          confidence_threshold: threshold,
          allowed_providers: [...providers],
          allowed_regions: [...regions],
        }),
      });
      setPolicy(updated);
      setPolicyOpen(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Policy could not be saved');
    } finally {
      setSaving(false);
    }
  };

  return (
    <main className="shell">
      <a className="skip-link" href="#dashboard">Skip to dashboard</a>
      <aside className="sidebar">
        <a className="brand" href="#dashboard" aria-label="AgenticTriage home"><Mark /><span>AgenticTriage</span></a>
        <nav aria-label="Primary navigation">
          <p className="nav-label">Workspace</p>
          <a className="nav-item active" href="#dashboard">Overview</a>
          <a className="nav-item" href="#queue">Escalation queue<span className="nav-count">{escalations.length}</span></a>
          <a className="nav-item" href="#activity">Audit activity</a>
          <p className="nav-label nav-section">Configure</p>
          <a className="nav-item" href="#policies">Tenant policy</a>
          <a className="nav-item" href="#providers">Model providers</a>
        </nav>
        <div className="tenant-card">
          <span className="tenant-avatar">E</span>
          <span><strong>Example tenant</strong><small>Local environment</small></span>
        </div>
      </aside>

      <section className="workspace" id="dashboard">
        <header className="topbar">
          <h1>Operations overview</h1>
          <div className="top-actions"><button className="refresh-button" onClick={() => void load()} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh'}</button><span className="user-avatar" aria-label="Signed in as operations console">OC</span></div>
        </header>

        <div className="content">
          <section className="hero-row" aria-labelledby="system-status">
            <div><div className="status-line"><span className={`pulse ${apiOnline === false ? 'offline' : ''}`} /><span id="system-status">{apiOnline === null ? 'Checking triage API' : apiOnline ? 'Triage API operational' : 'Triage API unavailable'}</span></div><p>Live tenant controls and recent pipeline activity.</p></div>
          </section>

          {error && <div className="api-banner" role="alert"><span>{error}</span><button onClick={() => void load()}>Try again</button></div>}

          <section className="metric-grid" aria-label="Triage metrics" aria-busy={loading}>
            <article className="metric-card featured"><p>Open escalations</p><div className="metric-value">{loading ? '—' : escalations.length.toLocaleString()}</div><div className="metric-foot"><span>Awaiting an operator decision</span></div></article>
            <article className="metric-card"><p>Audit events loaded</p><div className="metric-value">{loading ? '—' : activity.length.toLocaleString()}</div><div className="metric-foot"><span>Most recent tenant events</span></div></article>
            <article className="metric-card"><p>Response threshold</p><div className="metric-value">{policy ? policy.confidence_threshold.toFixed(2) : '—'}</div><div className="metric-foot"><span>Below threshold escalates</span></div><div className="progress-track"><span style={{ width: `${(policy?.confidence_threshold ?? 0) * 100}%` }} /></div></article>
            <article className="metric-card"><p>Policy version</p><div className="metric-value">{policy ? `v${policy.version}` : '—'}</div><div className="metric-foot"><span>{policy ? `Updated ${new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(policy.updated_at))}` : 'No policy loaded'}</span></div></article>
          </section>

          <section className="dashboard-grid">
            <article className="panel queue-panel" id="queue">
              <header className="panel-head"><div><h2>Needs human review</h2><p>Open escalations, ordered by arrival time.</p></div></header>
              <div className="table-wrap"><table>
                <thead><tr><th>Ticket</th><th>Reason</th><th>Attempts</th><th>Age</th><th><span className="sr-only">Action</span></th></tr></thead>
                <tbody>{escalations.map((item) => <tr key={item.id}>
                  <td><strong>{item.subject || 'Untitled ticket'}</strong><small>{item.ticket_id}</small></td>
                  <td><span className="risk high">{item.escalation_reason ?? 'Manual review required'}</span></td><td>{item.attempts}</td><td className="age">{age(item.created_at)}</td>
                  <td><button className="review-button" onClick={() => openReview(item)}>Review</button></td>
                </tr>)}</tbody>
              </table>{!loading && escalations.length === 0 && <div className="empty-state"><strong>No open escalations</strong><span>New fail-safe escalations will appear here.</span></div>}</div>
            </article>

            <aside className="panel provider-panel" id="providers">
              <header className="panel-head"><div><h2>Configured provider</h2><p>Tenant routing allowlist</p></div></header>
              <div className="provider-primary"><span className="provider-logo">LM</span><span><strong>LM Studio</strong><small>Local OpenAI-compatible endpoint</small></span><i className={lmStudioAllowed ? 'online' : 'online offline-label'}>{lmStudioAllowed ? 'Allowed' : 'Blocked'}</i></div>
              <dl className="provider-stats"><div><dt>Region</dt><dd>{policy?.allowed_regions.includes('local') ? 'Local' : 'Not allowed'}</dd></div><div><dt>Fail-safe</dt><dd>Human escalation</dd></div><div><dt>API connection</dt><dd>{apiOnline ? 'Reachable' : 'Unavailable'}</dd></div></dl>
            </aside>

            <article className="panel activity-panel" id="activity">
              <header className="panel-head"><div><h2>Audit activity</h2><p>Latest immutable pipeline records.</p></div><span className="live-label"><i /> Current</span></header>
              <div className="activity-list">{activity.map((item) => <div className="activity-item" key={item.sequence_id}><time dateTime={item.occurred_at}>{new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date(item.occurred_at))}</time><span className={`event-dot ${String(item.attributes.action) === 'escalate' ? 'escalated' : ''}`} /><strong>{item.ticket_id}</strong><span>{item.event_type}</span><small>{typeof item.attributes.provider === 'string' ? item.attributes.provider : 'system'}</small></div>)}</div>
              {!loading && activity.length === 0 && <div className="empty-state"><strong>No audit activity</strong><span>Process a ticket to create the first event.</span></div>}
            </article>

            <article className="panel policy-panel" id="policies">
              <header className="panel-head"><div><h2>Active policy</h2><p>Example tenant</p></div><span className="version">v{policy?.version ?? '—'}</span></header>
              <div className="policy-score"><span>Response threshold</span><strong>{policy?.confidence_threshold.toFixed(2) ?? '—'}</strong></div><div className="policy-track"><span style={{ width: `${(policy?.confidence_threshold ?? 0) * 100}%` }} /></div>
              <div className="policy-tags"><span>{policy?.allowed_regions.join(', ') || 'No regions'}</span><span>PII redaction</span><span>Exact citations</span></div><button className="policy-button" onClick={openPolicy} disabled={!policy}>Manage policy</button>
            </article>
          </section>
        </div>
      </section>

      {selectedTicket && <div className="modal-backdrop" role="presentation" onMouseDown={() => !saving && setSelectedTicket(null)}>
        <section className="modal" role="dialog" aria-modal="true" aria-labelledby="review-title" onMouseDown={(event) => event.stopPropagation()}>
          <header><div><p className="dialog-meta">Human review · {selectedTicket.ticket_id}</p><h2 id="review-title">{selectedTicket.subject || 'Untitled ticket'}</h2></div><button aria-label="Close review" onClick={() => setSelectedTicket(null)} disabled={saving}>Close</button></header>
          <div className="review-context"><span>Escalation reason<strong>{selectedTicket.escalation_reason ?? 'Manual review required'}</strong></span><span>Attempts<strong>{selectedTicket.attempts}</strong></span><span>Waiting<strong>{age(selectedTicket.created_at)}</strong></span></div>
          <label>Operator response<textarea autoFocus value={operatorResponse} maxLength={10000} onChange={(event) => setOperatorResponse(event.target.value)} /></label>
          {error && <p className="dialog-error" role="alert">{error}</p>}
          <div className="evidence"><strong>Fail-safe state</strong><p>No customer-facing message has been sent. Approval records the reviewed response; keeping it escalated closes this queue item for downstream handling.</p></div>
          <footer><button className="secondary" disabled={saving} onClick={() => void review('keep_escalated')}>Keep escalated</button><button className="primary" disabled={saving || !operatorResponse.trim()} onClick={() => void review('approve_response')}>{saving ? 'Saving…' : 'Approve response'}</button></footer>
        </section>
      </div>}

      {policyOpen && policy && <div className="modal-backdrop" role="presentation" onMouseDown={() => !saving && setPolicyOpen(false)}>
        <form className="modal policy-modal" role="dialog" aria-modal="true" aria-labelledby="policy-title" onSubmit={savePolicy} onMouseDown={(event) => event.stopPropagation()}>
          <header><div><p className="dialog-meta">Example tenant · v{policy.version}</p><h2 id="policy-title">Response policy</h2></div><button type="button" aria-label="Close policy" onClick={() => setPolicyOpen(false)} disabled={saving}>Close</button></header>
          <label>Minimum confidence <div className="range-value"><input autoFocus type="range" min="0" max="1" step="0.05" value={threshold} onChange={(event) => setThreshold(Number(event.target.value))} /><output>{threshold.toFixed(2)}</output></div></label>
          <fieldset><legend>Allowed providers</legend><label className="check-row"><input type="checkbox" checked={lmStudioAllowed} onChange={(event) => setLmStudioAllowed(event.target.checked)} />LM Studio · local</label></fieldset>
          {error && <p className="dialog-error" role="alert">{error}</p>}
          <div className="evidence"><strong>Fail-safe behavior</strong><p>Invalid schemas, unverifiable citations, provider exhaustion, and scores below this threshold are escalated automatically.</p></div>
          <footer><button type="button" className="secondary" onClick={() => setPolicyOpen(false)} disabled={saving}>Cancel</button><button className="primary" disabled={saving}>{saving ? 'Saving…' : 'Save policy'}</button></footer>
        </form>
      </div>}
    </main>
  );
}
