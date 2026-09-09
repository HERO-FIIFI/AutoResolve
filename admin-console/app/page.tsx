'use client';

import { useEffect, useState } from 'react';

const queue = [
  { id: 'INC-24091', subject: 'Unable to verify payroll export', account: 'Northstar Health', age: '4m', risk: 'high', reason: 'Sensitive data' },
  { id: 'INC-24088', subject: 'SAML metadata rotation failed', account: 'Arcway Financial', age: '11m', risk: 'high', reason: 'Identity' },
  { id: 'INC-24076', subject: 'Invoice total differs from contract', account: 'Basin Works', age: '23m', risk: 'medium', reason: 'Low confidence' },
];

const activity = [
  ['16:24:08', 'INC-24095', 'Responded', 'LM Studio · 1.2s'],
  ['16:23:51', 'INC-24094', 'Escalated', 'Citation mismatch'],
  ['16:23:37', 'INC-24093', 'Responded', 'LM Studio · 1.6s'],
  ['16:22:58', 'INC-24092', 'Responded', 'LM Studio · 1.1s'],
];

function Mark() {
  return <span className="brand-mark" aria-hidden="true"><span /><span /><span /></span>;
}

export default function Home() {
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [selectedTicket, setSelectedTicket] = useState<(typeof queue)[number] | null>(null);
  const [policyOpen, setPolicyOpen] = useState(false);

  useEffect(() => {
    const apiUrl = process.env.NEXT_PUBLIC_TRIAGE_API_URL ?? 'http://localhost:8080';
    const check = () => fetch(`${apiUrl}/healthz`).then((response) => setApiOnline(response.ok)).catch(() => setApiOnline(false));
    check();
    const timer = window.setInterval(check, 15000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <main className="shell">
      <aside className="sidebar">
        <a className="brand" href="#overview" aria-label="AgenticTriage home"><Mark /><span>AgenticTriage</span></a>
        <nav aria-label="Primary navigation">
          <p className="nav-label">Workspace</p>
          <a className="nav-item active" href="#overview"><span className="nav-icon">⌁</span>Overview</a>
          <a className="nav-item" href="#queue"><span className="nav-icon">↗</span>Escalation queue<span className="nav-count">3</span></a>
          <a className="nav-item" href="#activity"><span className="nav-icon">≡</span>Audit activity</a>
          <p className="nav-label nav-section">Configure</p>
          <a className="nav-item" href="#knowledge"><span className="nav-icon">◇</span>Knowledge base</a>
          <a className="nav-item" href="#policies"><span className="nav-icon">◫</span>Tenant policies</a>
          <a className="nav-item" href="#providers"><span className="nav-icon">⌘</span>Model providers</a>
        </nav>
        <div className="tenant-card">
          <span className="tenant-avatar">A</span>
          <span><strong>Acme Europe</strong><small>Production · EU</small></span>
          <button aria-label="Open tenant menu">•••</button>
        </div>
      </aside>

      <section className="workspace" id="overview">
        <header className="topbar">
          <div><p className="eyebrow">Operations</p><h1>Good afternoon, Maya</h1></div>
          <div className="top-actions">
            <button className="icon-button" aria-label="Search">⌕</button>
            <button className="icon-button notification" aria-label="Notifications">○</button>
            <span className="user-avatar">MK</span>
          </div>
        </header>

        <div className="content">
          <section className="hero-row" aria-labelledby="system-status">
            <div><div className="status-line"><span className={`pulse ${apiOnline === false ? 'offline' : ''}`} /><span id="system-status">{apiOnline === null ? 'Checking triage API' : apiOnline ? 'All systems operational' : 'Triage API unavailable'}</span></div><p>Live triage health across the Acme Europe workspace.</p></div>
            <div className="window-select" aria-label="Reporting period">Last 24 hours <span>⌄</span></div>
          </section>

          <section className="metric-grid" aria-label="Triage metrics">
            <article className="metric-card featured">
              <p>Tickets processed</p><div className="metric-value">2,481</div>
              <div className="metric-foot"><span className="trend up">↗ 12.4%</span><span>vs previous period</span></div>
              <div className="bars" aria-hidden="true">{[38,53,46,68,59,76,65,88,71,92,82,96].map((height,index)=><i key={index} style={{height:`${height}%`}} />)}</div>
            </article>
            <article className="metric-card">
              <p>Auto-resolution</p><div className="metric-value">78.6%</div>
              <div className="metric-foot"><span className="trend up">↗ 3.1%</span><span>verified responses</span></div>
              <div className="progress-track"><span style={{width:'78.6%'}} /></div>
            </article>
            <article className="metric-card">
              <p>Median latency</p><div className="metric-value">1.4<span className="unit">s</span></div>
              <div className="metric-foot"><span className="trend up">↓ 180ms</span><span>across all stages</span></div>
              <div className="latency-row"><span>Risk</span><b>18ms</b><span>RAG</span><b>220ms</b><span>LLM</span><b>1.1s</b></div>
            </article>
            <article className="metric-card">
              <p>Cost per ticket</p><div className="metric-value">$0.018</div>
              <div className="metric-foot"><span className="trend neutral">Within budget</span><span>$43.94 today</span></div>
              <div className="budget-line"><span /><i>34%</i></div>
            </article>
          </section>

          <section className="dashboard-grid">
            <article className="panel queue-panel" id="queue">
              <header className="panel-head"><div><h2>Needs human review</h2><p>Highest-risk escalations, ordered by SLA.</p></div><a href="#queue">View queue <span>→</span></a></header>
              <div className="table-wrap"><table>
                <thead><tr><th>Ticket</th><th>Account</th><th>Reason</th><th>Age</th><th /></tr></thead>
                <tbody>{queue.map((item)=><tr key={item.id}>
                  <td><strong>{item.subject}</strong><small>{item.id}</small></td><td>{item.account}</td>
                  <td><span className={`risk ${item.risk}`}>{item.reason}</span></td><td className="age">{item.age}</td>
                  <td><button className="review-button" onClick={() => setSelectedTicket(item)}>Review</button></td>
                </tr>)}</tbody>
              </table></div>
            </article>

            <aside className="panel provider-panel" id="providers">
              <header className="panel-head"><div><h2>Provider health</h2><p>Fallback order</p></div><button aria-label="Provider settings">•••</button></header>
              <div className="provider-primary"><span className="provider-logo">LM</span><span><strong>LM Studio</strong><small>qwen/qwen3.5-9b</small></span><i className={apiOnline === false ? 'online offline-label' : 'online'}>{apiOnline === false ? 'Unavailable' : 'Online'}</i></div>
              <dl className="provider-stats"><div><dt>Success rate</dt><dd>99.8%</dd></div><div><dt>P95 latency</dt><dd>2.3s</dd></div><div><dt>Circuit</dt><dd><span className="circuit-dot" /> Closed</dd></div></dl>
              <div className="fallback-note"><span>2</span><p><strong>Secondary provider</strong><small>Not configured</small></p><button>Add</button></div>
            </aside>

            <article className="panel activity-panel" id="activity">
              <header className="panel-head"><div><h2>Live decision stream</h2><p>Recent pipeline outcomes.</p></div><span className="live-label"><i /> Live</span></header>
              <div className="activity-list">{activity.map(([time,ticket,result,detail])=><div className="activity-item" key={ticket}><time>{time}</time><span className={`event-dot ${result.toLowerCase()}`} /><strong>{ticket}</strong><span>{result}</span><small>{detail}</small></div>)}</div>
            </article>

            <article className="panel policy-panel" id="policies">
              <header className="panel-head"><div><h2>Active policy</h2><p>Acme Europe</p></div><span className="version">v12</span></header>
              <div className="policy-score"><span>Response threshold</span><strong>0.80</strong></div><div className="policy-track"><span /></div>
              <div className="policy-tags"><span>EU residency</span><span>PII redaction</span><span>Exact citations</span></div><button className="policy-button" onClick={() => setPolicyOpen(true)}>Manage policy</button>
            </article>
          </section>
        </div>
      </section>

      {selectedTicket && <div className="modal-backdrop" role="presentation" onMouseDown={() => setSelectedTicket(null)}>
        <section className="modal" role="dialog" aria-modal="true" aria-labelledby="review-title" onMouseDown={(event) => event.stopPropagation()}>
          <header><div><p className="eyebrow">Human review · {selectedTicket.id}</p><h2 id="review-title">{selectedTicket.subject}</h2></div><button aria-label="Close review" onClick={() => setSelectedTicket(null)}>×</button></header>
          <div className="review-context"><span>Account<strong>{selectedTicket.account}</strong></span><span>Escalation reason<strong>{selectedTicket.reason}</strong></span><span>Waiting<strong>{selectedTicket.age}</strong></span></div>
          <label>Operator response<textarea defaultValue="Thanks for flagging this. A support specialist is reviewing the request and will follow up shortly." /></label>
          <div className="evidence"><strong>Why this was escalated</strong><p>The deterministic risk gate prevented an automated response. No customer-facing message has been sent.</p></div>
          <footer><button className="secondary" onClick={() => setSelectedTicket(null)}>Keep escalated</button><button className="primary" onClick={() => setSelectedTicket(null)}>Approve response</button></footer>
        </section>
      </div>}

      {policyOpen && <div className="modal-backdrop" role="presentation" onMouseDown={() => setPolicyOpen(false)}>
        <section className="modal policy-modal" role="dialog" aria-modal="true" aria-labelledby="policy-title" onMouseDown={(event) => event.stopPropagation()}>
          <header><div><p className="eyebrow">Acme Europe · v12</p><h2 id="policy-title">Response policy</h2></div><button aria-label="Close policy" onClick={() => setPolicyOpen(false)}>×</button></header>
          <label>Minimum confidence <div className="range-value"><input type="range" min="0" max="1" step="0.05" defaultValue="0.8" /><strong>0.80</strong></div></label>
          <fieldset><legend>Allowed providers</legend><label className="check-row"><input type="checkbox" defaultChecked />LM Studio · local</label><label className="check-row"><input type="checkbox" />Secondary provider</label></fieldset>
          <div className="evidence"><strong>Fail-safe behavior</strong><p>Invalid schemas, unverifiable citations, provider exhaustion, and scores below this threshold are escalated automatically.</p></div>
          <footer><button className="secondary" onClick={() => setPolicyOpen(false)}>Cancel</button><button className="primary" onClick={() => setPolicyOpen(false)}>Save draft</button></footer>
        </section>
      </div>}
    </main>
  );
}
