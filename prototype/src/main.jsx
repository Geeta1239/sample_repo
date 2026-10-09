import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

const DEFAULT_TARGET = 'http://127.0.0.1:3000';

const PIPELINE_STAGES = [
  ['01', 'Target accepted', 'URL normalized and queued'],
  ['02', 'Browser opened', 'Fresh Chromium context'],
  ['03', 'Evidence captured', 'Routes, DOM, state, screenshots'],
  ['04', 'Evidence classified', 'Rules + NLP compatibility layer'],
  ['05', 'Report persisted', 'SQLite + JSON artifacts'],
];

const CASE_STUDIES = [
  { label: 'FTC · September 2025 order', title: 'Amazon Prime enrollment and cancellation', pattern: 'Subscription Trap · Interface Interference', summary: 'The FTC said Amazon enrolled millions of consumers without consent and made Prime cancellation exceedingly difficult. The finalized settlement requires changes to both enrollment and cancellation.', stat: '$2.5B', statLabel: 'historic settlement', detail: '$1B civil penalty + $1.5B redress for an estimated 35M consumers', source: 'https://www.ftc.gov/news-events/news/press-releases/2025/09/ftc-secures-historic-25-billion-settlement-against-amazon', image: '/assets/cases/amazon-prime-settlement.jpg', accent: 'amazon' },
  { label: 'FTC · March 2023 finalized order', title: 'Epic Games / Fortnite unwanted charges', pattern: 'Basket Sneaking · Trick Question', summary: 'The FTC finalized an order requiring Epic Games to pay consumers over allegations that confusing controls and dark patterns caused unwanted in-game purchases, including purchases by children without parental consent.', stat: '$245M', statLabel: 'consumer refunds', detail: 'The order bars charging through dark patterns without affirmative consent', source: 'https://www.ftc.gov/news-events/news/press-releases/2023/03/ftc-finalizes-order-requiring-fortnite-maker-epic-games-pay-245-million-tricking-users-making', image: '/assets/cases/epic-dark-pattern.jpg', accent: 'epic' },
  { label: 'FTC · November 2022 refunds', title: 'Vonage cancellation maze', pattern: 'Subscription Trap · Drip Pricing', summary: 'The FTC said Vonage made it difficult for customers to cancel subscriptions and continued charging some consumers. The agency announced refunds and required changes to cancellation and billing practices.', stat: '$100M', statLabel: 'consumer refunds', detail: 'A subscription case where exit friction became a measurable customer cost', source: 'https://www.ftc.gov/news-events/news/press-releases/2022/11/ftc-refunds-nearly-100-million-vonage-consumers-who-were-trapped-subscriptions-dark-patterns', image: '/assets/cases/vonage-refunds.png', accent: 'vonage' },
  { label: 'FTC · September 2022 staff report', title: 'Bringing Dark Patterns to Light', pattern: 'False Urgency · Drip Pricing · Disguised Ads', summary: 'The FTC report describes four recurring tactic families: disguising ads, difficult cancellation, buried terms and junk fees, and steering people into sharing data.', stat: '4', statLabel: 'tactic families', detail: 'A regulator-backed vocabulary for talking about pressure, cost, consent, and privacy', source: 'https://www.ftc.gov/news-events/news/press-releases/2022/09/ftc-report-shows-rise-sophisticated-dark-patterns-designed-trick-trap-consumers', image: '/assets/cases/vonage-refunds.png', accent: 'report' },
];

const GUIDELINES = [
  ['01', 'Look for pressure', 'Check whether timers, low-stock messages, or repeated prompts create urgency that is not supported by truthful evidence.', 'False Urgency', 'Is the pressure truthful and necessary?'],
  ['02', 'Trace consent', 'Inspect every checkbox, default, and add-on. An optional cost should require a clear, affirmative choice.', 'Basket Sneaking', 'Did the customer affirmatively choose this?'],
  ['03', 'Read the labels', 'Compare the emotional weight of accept and decline actions. Neutral wording should not shame a customer.', 'Confirm Shaming', 'Are both choices emotionally neutral?'],
  ['04', 'Follow the full journey', 'Start with the first click and continue to cancellation, payment, and renewal. Friction often appears after commitment.', 'Forced Action', 'Is any unrelated action required?'],
  ['05', 'Trace commitment', 'Follow signup, renewal, billing, and cancellation as one connected journey.', 'Subscription Trap', 'Is exit as simple as entry?'],
  ['06', 'Compare visual weight', 'Give consequential choices equal prominence. A muted alternative can be as influential as a misleading label.', 'Interface Interference', 'Are consequential choices equally visible?'],
  ['07', 'Compare promise and outcome', 'Record what was offered first and what remains available at the final step.', 'Bait and Switch', 'Did the promised outcome stay available?'],
  ['08', 'Recalculate the price', 'Record the first price and the final payable amount. Late fees prevent meaningful comparison.', 'Drip Pricing', 'Can the customer compare the full price early?'],
  ['09', 'Identify persuasion', 'Check whether sponsored or commercial content resembles independent information.', 'Disguised Advertisement', 'Can the customer recognize the commercial intent?'],
  ['10', 'Track repetition', 'Record whether prompts return after the customer dismisses or declines them.', 'Nagging', 'Does the interface respect a declined prompt?'],
  ['11', 'Read for ambiguity', 'Look for double negatives, vague labels, or choices whose consequences are hard to predict.', 'Trick Question', 'Would a reasonable customer understand the result?'],
  ['12', 'Audit recurring billing', 'Inspect trial language, renewal notices, billing defaults, and account exit paths.', 'SaaS Billing', 'Is renewal explicit and easy to control?'],
  ['13', 'Protect the boundary', 'Do not create fake infection warnings, malicious downloads, or device-compromise behavior.', 'Rogue Malware', 'Is the experience safe and non-malicious?'],
];

function normalizeTarget(value) {
  const candidate = value.trim();
  if (!candidate) throw new Error('Enter the URL of the website you want ShadowBait to inspect.');
  const parsed = new URL(candidate);
  if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('Target URL must use http:// or https://.');
  return parsed.toString().replace(/\/$/, '');
}

function hostnameFor(value) {
  try { return new URL(value || DEFAULT_TARGET).hostname || ''; } catch { return ''; }
}
function isFlipkartTarget(value) {
  return /(^|\.)flipkart\.com$/i.test(hostnameFor(value));
}

function navigate(path) {
  window.history.pushState({}, '', path);
  window.dispatchEvent(new PopStateEvent('popstate'));
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function App() {
  const [path, setPath] = useState(window.location.pathname || '/');
  const [darkMode, setDarkMode] = useState(() => window.localStorage.getItem('shadowbait-theme') === 'dark');
  const [targetUrl, setTargetUrl] = useState(() => window.localStorage.getItem('shadowbait-target-url') || DEFAULT_TARGET);
  const [scan, setScan] = useState({ running: false, completed: 0, total: 0, findings: [], pages: [], message: 'Ready — enter a target website URL to begin.', error: '', meta: null, report: null, scanId: '' });
  const [uploadFile, setUploadFile] = useState(null);
  const eventSourceRef = useRef(null);

  useEffect(() => {
    const onPopState = () => setPath(window.location.pathname || '/');
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = darkMode ? 'dark' : 'light';
    window.localStorage.setItem('shadowbait-theme', darkMode ? 'dark' : 'light');
  }, [darkMode]);

  useEffect(() => () => eventSourceRef.current?.close(), []);

  const startInspection = () => {
    let normalized;
    try { normalized = normalizeTarget(targetUrl); } catch (error) {
      setScan((current) => ({ ...current, error: error.message, message: 'Inspection not started.' }));
      navigate('/inspect');
      return;
    }
    window.localStorage.setItem('shadowbait-target-url', normalized);
    eventSourceRef.current?.close();
    setScan({ running: true, completed: 0, total: 0, findings: [], pages: [], message: 'Connecting to the inspection API…', error: '', meta: null, report: null, scanId: '' });
    navigate('/inspect');
    const configuredApi = window.localStorage.getItem('shadowbait-inspection-api') || '';
    const source = new EventSource(`${configuredApi}/api/inspection/stream?target=${encodeURIComponent(normalized)}`);
    eventSourceRef.current = source;
    source.addEventListener('started', (event) => { const data = JSON.parse(event.data); setScan((current) => ({ ...current, meta: data, total: data.total || current.total, message: data.message })); });
    source.addEventListener('stage', (event) => { const data = JSON.parse(event.data); setScan((current) => ({ ...current, completed: data.completed || 0, total: data.total || current.total, pages: data.page_url ? [...current.pages.filter((page) => page.url !== data.page_url), { index: data.page_index, url: data.page_url, title: data.page_title, status: data.page_status }] : current.pages, message: data.message })); });
    source.addEventListener('finding', (event) => { const data = JSON.parse(event.data); setScan((current) => ({ ...current, completed: data.completed || current.completed, total: data.total || current.total, findings: [...current.findings, data.finding], message: data.message })); });
    source.addEventListener('classification', (event) => { const data = JSON.parse(event.data); setScan((current) => ({ ...current, message: data.message, findings: current.findings.map((finding) => finding.id === data.pattern_id ? { ...finding, m2_status: data.status, m2_findings: data.findings || [] } : finding) })); });
    source.addEventListener('complete', async (event) => {
      const data = JSON.parse(event.data);
      const apiRoot = window.localStorage.getItem('shadowbait-inspection-api') || '';
      let report = { scan: { ...(data.scan || {}), target: normalized, scan_id: data.scan_id, finished_at: data.finished_at }, findings: data.findings || [], ux_findings: data.ux_findings || [], summary: data.summary || {} };
      try { const response = await fetch(`${apiRoot}/api/scans/${encodeURIComponent(data.scan_id)}/report`); if (response.ok) report = await response.json(); } catch { /* stream payload remains usable */ }
      setScan((current) => ({ ...current, running: false, completed: data.completed || current.total, total: data.total || current.total, findings: data.findings || current.findings, pages: report.pages || current.pages, message: data.message, meta: { ...(current.meta || {}), finished_at: data.finished_at, summary: data.summary }, report, scanId: data.scan_id }));
      source.close();
    });
    source.addEventListener('error', (event) => { let message = 'Live inspection API could not be reached.'; try { if (event.data) message = JSON.parse(event.data).message || message; } catch { /* native EventSource error */ } setScan((current) => { if (current.report || (current.completed >= current.total && current.total > 0)) return current; return { ...current, running: false, error: `${message} Start backend/inspection_server.py from this project, then reload the prototype.`, message: 'Inspection stopped.' }; }); source.close(); });
  };
  const startArtifactScan = async () => {
    if (!uploadFile) { setScan((current) => ({ ...current, error: 'Choose a screenshot or file before starting artifact analysis.', message: 'Upload not started.' })); return; }
    const kind = uploadFile.type.startsWith('image/') ? 'screenshot' : 'file';
    setScan({ running: true, completed: 0, total: 1, findings: [], pages: [], message: `Reading ${uploadFile.name}…`, error: '', meta: null, report: null, scanId: '' });
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const apiRoot = window.localStorage.getItem('shadowbait-inspection-api') || '';
        const response = await fetch(`${apiRoot}/api/artifact-scan`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind, filename: uploadFile.name, data: reader.result }) });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Artifact analysis failed.');
        setScan({ running: false, completed: 1, total: 1, findings: data.report.findings || [], pages: data.report.pages || [], message: data.message, error: '', meta: { ...data.report.scan, mode: `${kind} artifact scan` }, report: data.report, scanId: data.scan_id });
      } catch (error) { setScan((current) => ({ ...current, running: false, error: error.message, message: 'Artifact analysis stopped.' })); }
    };
    reader.onerror = () => setScan((current) => ({ ...current, running: false, error: 'The selected file could not be read.', message: 'Artifact analysis stopped.' }));
    reader.readAsDataURL(uploadFile);
  };

  const resetInspection = () => { eventSourceRef.current?.close(); setScan({ running: false, completed: 0, total: 0, findings: [], pages: [], message: 'Ready — enter a target website URL to begin.', error: '', meta: null, report: null, scanId: '' }); navigate('/inspect'); };

  const page = useMemo(() => {
    if (path === '/inspect') return <InspectionPage targetUrl={targetUrl} setTargetUrl={setTargetUrl} scan={scan} startInspection={startInspection} uploadFile={uploadFile} setUploadFile={setUploadFile} startArtifactScan={startArtifactScan} />;
    if (path.startsWith('/results/')) return <ResultsPage targetUrl={targetUrl} scan={scan} scanId={decodeURIComponent(path.slice('/results/'.length))} />;
    if (path === '/guidelines') return <GuidelinesPage />;
    if (path === '/case-studies') return <CaseStudiesPage />;
    if (path === '/diff') return <InteractiveDiffPage scan={scan} targetUrl={targetUrl} />;
    if (path === '/architecture') return <ArchitecturePage />;
    return <OverviewPage targetUrl={targetUrl} scan={scan} />;
  }, [path, targetUrl, scan, uploadFile]);

  return <div className="prototype-shell">
    <div className="demo-ribbon"><strong>SHADOWBAIT PLATFORM</strong><span>Evidence-first website auditing for responsible product teams</span></div>
    <header className="site-header"><button className="brand" onClick={() => navigate('/')} aria-label="Go to ShadowBait overview"><span className="brand-mark">SB</span><span>ShadowBait</span></button><nav className="main-nav" aria-label="ShadowBait navigation"><button className={path === '/' ? 'active' : ''} onClick={() => navigate('/')}>Platform</button><button className={path === '/inspect' ? 'active' : ''} onClick={() => navigate('/inspect')}>Inspect</button><button className={path.startsWith('/results/') ? 'active' : ''} onClick={() => scan.scanId ? navigate(`/results/${encodeURIComponent(scan.scanId)}`) : navigate('/inspect')}>Evidence</button><button className={path === '/guidelines' ? 'active' : ''} onClick={() => navigate('/guidelines')}>Guidelines</button><button className={path === '/case-studies' ? 'active' : ''} onClick={() => navigate('/case-studies')}>Case Studies</button><button className={path === '/architecture' ? 'active' : ''} onClick={() => navigate('/architecture')}>Architecture</button><button className="reset-link" onClick={resetInspection}>Reset Run</button><button className="theme-toggle" onClick={() => setDarkMode((value) => !value)} aria-label="Toggle ShadowBait theme">{darkMode ? '☀ Light' : '◐ Dark'}</button></nav></header>
    <main>{page}</main>
    <footer className="site-footer"><span>ShadowBait · Explainable dark-pattern inspection</span><span>Technical observation · Not a legal conclusion</span></footer>
  </div>;
}

function PageIntro({ eyebrow, title, copy, actions }) { return <section className="inspection-hero"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{copy}</p></div>{actions && <div className="inspection-actions">{actions}</div>}</section>; }

function OverviewPage({ targetUrl, scan }) {
  return <div className="page-wrap overview-page"><div className="breadcrumb">Home <span>/</span> Platform</div><section className="platform-hero"><div className="platform-hero-copy"><span className="eyebrow">THE RESPONSIBLE INTERFACE AUDIT</span><h1>See the choice behind the click.</h1><p>ShadowBait turns a website URL into a defensible evidence trail. It captures what a customer actually sees, explains the possible impact, and gives teams a clearer path to fix it.</p><div className="hero-actions"><button className="primary-cta" onClick={() => navigate('/inspect')}>START AN INSPECTION <span>→</span></button><button className="secondary-cta" onClick={() => navigate('/guidelines')}>LEARN THE GUIDELINES</button></div><div className="hero-proof"><span><strong>7</strong> evidence categories</span><span><strong>3</strong> analysis layers</span><span><strong>1</strong> reviewable report</span></div></div><div className="hero-console"><div className="console-top"><span>SHADOWBAIT / LIVE VIEW</span><span className="console-status">● READY</span></div><div className="console-url">{targetUrl}</div><div className="hero-bars"><span style={{ width: '92%' }} /><span style={{ width: '74%' }} /><span style={{ width: '84%' }} /><span style={{ width: '58%' }} /></div><div className="hero-console-footer"><strong>Evidence before judgment</strong><span>Browser · Rules · Review</span></div></div></section><section className="platform-stats"><Stat value="01" label="Capture" copy="Observe routes, DOM state, screenshots, and selectors." /><Stat value="02" label="Explain" copy="Connect a pattern to customer impact without hiding the evidence." /><Stat value="03" label="Improve" copy="Compare the original experience with an ethical alternative." /></section><PatternAtlas /><RealityStrip /><DemoVideoSection /><section className="platform-section"><div className="section-heading wide-heading"><div><span className="eyebrow">A COMPLETE REVIEW WORKSPACE</span><h2>From first signal to confident conversation.</h2></div><p>Designed for demos, product reviews, trust teams, and anyone who needs to discuss interface behavior with more precision than a screenshot alone.</p></div><div className="feature-grid"><Feature icon="◎" title="Evidence ledger" copy="Every finding keeps the target route, selector, visible text, state, and screenshot together." action="Open inspection" onClick={() => navigate('/inspect')} /><Feature icon="⌁" title="Impact language" copy="Move beyond labels. See how the interface can pressure, confuse, or redirect a customer." action="See guidelines" onClick={() => navigate('/guidelines')} /><Feature icon="↔" title="Interactive diff" copy="Compare the problematic state with a clearer alternative and articulate the customer benefit." action="Compare states" onClick={() => navigate('/diff')} /><Feature icon="▣" title="Real-world context" copy="Anchor the conversation with regulator-documented cases and source links." action="Read case studies" onClick={() => navigate('/case-studies')} /></div></section><section className="workflow-band"><div><span className="eyebrow">THE PRESENTATION STORY</span><h2>Show the journey in one clean narrative.</h2><p>Start in the separate demo website. Then bring the URL into ShadowBait and let the evidence lead the explanation.</p></div><div className="workflow-steps"><WorkflowStep number="01" title="Target URL" /><WorkflowStep number="02" title="Browser capture" /><WorkflowStep number="03" title="Customer impact" /><WorkflowStep number="04" title="Ethical diff" /></div></section><section className="case-teaser"><div><span className="eyebrow">WHY THIS MATTERS</span><h2>Dark patterns are not just a design debate.</h2><p>Regulators have described and acted on the same kinds of pressure, hidden cost, and cancellation friction that ShadowBait helps teams see.</p></div><button className="secondary-cta" onClick={() => navigate('/case-studies')}>VIEW CASE STUDIES <span>→</span></button></section><section className="platform-cta"><span className="eyebrow">READY TO LOOK CLOSER?</span><h2>Bring a URL. Leave with evidence.</h2><p>Use the inspection console for a live presentation or a repeatable review.</p><button className="primary-cta" onClick={() => navigate('/inspect')}>NEW INSPECTION <span>→</span></button></section><div className="overview-note"><strong>Current target:</strong><span>{targetUrl} · {scan.scanId ? `last scan ${scan.scanId}` : 'no scan run yet'}</span></div></div>;
}

function Stat({ value, label, copy }) { return <div className="platform-stat"><strong>{value}</strong><div><h3>{label}</h3><p>{copy}</p></div></div>; }
function Feature({ icon, title, copy, action, onClick }) { return <article className="feature-card"><span className="feature-icon">{icon}</span><h3>{title}</h3><p>{copy}</p><button className="text-link" onClick={onClick}>{action} →</button></article>; }
function WorkflowStep({ number, title }) { return <div className="workflow-step"><span>{number}</span><strong>{title}</strong></div>; }

function DemoVideoSection() {
  return <section className="demo-video-section"><div className="demo-video-copy"><span className="eyebrow">WATCH THE WORKFLOW · 00:43</span><h2>From a URL to a defensible conversation.</h2><p>See the exact story a judge can follow: ShadowBait accepts the separate storefront URL, opens a fresh browser, captures the visible states, classifies the findings, and lands on the customer-impact diff.</p><div className="video-step-rail"><span><b>01</b>Target URL</span><span><b>02</b>Browser capture</span><span><b>03</b>Evidence ledger</span><span><b>04</b>Ethical diff</span></div></div><div className="demo-video-frame"><video controls playsInline preload="metadata" poster="/assets/shadowbait-video-poster.jpg"><source src="/assets/shadowbait-workflow.mp4" type="video/mp4" />Your browser does not support the demo video.</video><div className="video-caption"><span><i />Recorded from the working prototype · narrated walkthrough</span><span>1440 × 900 · MP4 · voiceover</span></div></div></section>;
}

function RealityStrip() {
  const cards = [
    ['35M', 'estimated consumers in the Amazon Prime redress figure', 'FTC · 2025'],
    ['$245M', 'Epic consumer refunds required by a finalized FTC order', 'FTC · 2023'],
    ['$100M', 'Vonage refunds announced for trapped subscriptions', 'FTC · 2022'],
  ];
  const [active, setActive] = useState(0);
  useEffect(() => { const timer = window.setInterval(() => setActive((value) => (value + 1) % cards.length), 3200); return () => window.clearInterval(timer); }, []);
  return <section className="reality-strip"><div className="reality-heading"><span className="eyebrow">THE PAPER TRAIL · LIVE ROTATION</span><h2>Real interfaces create real costs.</h2><p>These are not hypothetical labels. They are source-backed figures that explain why a screenshot needs context.</p></div><div className="reality-feature"><span className="reality-number">{cards[active][0]}</span><div><strong>{cards[active][1]}</strong><small>{cards[active][2]} · <a href="/case-studies" onClick={(event) => { event.preventDefault(); navigate('/case-studies'); }}>open the evidence room ↗</a></small></div></div><div className="reality-dots">{cards.map((card, index) => <button key={card[0]} className={active === index ? 'active' : ''} aria-label={`Show ${card[0]} statistic`} onClick={() => setActive(index)} />)}</div></section>;
}

function patternStatus(id) {
  if (id === '13') return 'EXCLUDED';
  return ['01', '02', '03', '05', '06', '07', '08'].includes(id) ? 'VERIFIED' : 'REVIEW';
}

function PatternAtlas({ compact = false }) {
  const [selected, setSelected] = useState('01');
  const selectedItem = GUIDELINES.find(([id]) => id === selected) || GUIDELINES[0];
  const points = GUIDELINES.map((item, index) => {
    const angle = (-Math.PI / 2) + (index / GUIDELINES.length) * Math.PI * 2;
    return { item, x: 180 + Math.cos(angle) * 132, y: 160 + Math.sin(angle) * 112 };
  });
  return <section className={`atlas-card ${compact ? 'compact' : ''}`}>
    <div className="atlas-copy"><span className="eyebrow">PATTERN ATLAS · INTERACTIVE</span><h2>Thirteen ways a choice can be bent.</h2><p>Hover or select a signal to see its review status, customer impact, and the question ShadowBait asks before raising it.</p><div className="atlas-legend"><span><i className="legend-dot verified" />Verified fixture</span><span><i className="legend-dot review" />Review category</span><span><i className="legend-dot excluded" />Safe boundary</span></div><div className="atlas-selected"><div><span className={`status-token ${patternStatus(selectedItem[0]).toLowerCase()}`}>{patternStatus(selectedItem[0])}</span><strong>{selectedItem[0]} · {selectedItem[3]}</strong></div><p>{selectedItem[2]}</p><small><b>Ask:</b> {selectedItem[4]}</small></div></div>
    <div className="atlas-visual"><div className="atlas-orbit orbit-one" /><div className="atlas-orbit orbit-two" /><svg viewBox="0 0 360 320" role="img" aria-label="Interactive dark pattern category atlas"><defs><radialGradient id="atlasCore" cx="50%" cy="50%"><stop offset="0" stopColor="var(--sb-blue)" stopOpacity=".9" /><stop offset="1" stopColor="var(--sb-purple)" stopOpacity=".22" /></radialGradient></defs><circle cx="180" cy="160" r="43" fill="url(#atlasCore)" className="atlas-core" /><text x="180" y="155" textAnchor="middle" className="atlas-core-label">SHADOW</text><text x="180" y="170" textAnchor="middle" className="atlas-core-label">BAIT</text>{points.map(({ item, x, y }) => { const [id, , , name] = item; const status = patternStatus(id); return <g key={id} className={`atlas-node ${selected === id ? 'selected' : ''} ${status.toLowerCase()}`} role="button" tabIndex="0" aria-label={`${id} ${name}`} onClick={() => setSelected(id)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') setSelected(id); }}><line x1="180" y1="160" x2={x} y2={y} className="atlas-spoke" /><circle cx={x} cy={y} r={selected === id ? 15 : 10} className="atlas-node-ring" /><text x={x} y={y + 3} textAnchor="middle" className="atlas-node-label">{id}</text></g>; })}</svg></div>
  </section>;
}

function InspectionPage({ targetUrl, setTargetUrl, scan, startInspection, uploadFile, setUploadFile, startArtifactScan }) {
  const inspectedPages = scan.pages || [];
  const progress = scan.total ? Math.min(100, (scan.completed / scan.total) * 100) : 0;
  const flipkartMode = scan.meta?.mode === 'Flipkart 13-category scan with isolated cart check' || isFlipkartTarget(targetUrl);
  const localDemo = /^http:\/\/(?:localhost|127\.0\.0\.1):3000(?:\/|$)/i.test(targetUrl || DEFAULT_TARGET);
  const visibleFindings = scan.report
    ? (scan.report.findings || [])
    : scan.findings.length
      ? scan.findings
      : localDemo && scan.completed
        ? []
        : [];
  const pipeline = PIPELINE_STAGES.map(([number, title, copy], index) => ({ number, title, copy, done: scan.completed >= index + 1, active: scan.running && scan.completed === index }));
  return <div className="page-wrap inspection-page"><div className="breadcrumb">Home <span>/</span> Inspect</div><PageIntro eyebrow="LIVE INSPECTION CONSOLE" title="Inspect a separate website." copy={flipkartMode ? "Flipkart mode runs six public pages through all 13 categories and returns read-only evidence." : "Enter the normal demo-site URL below. ShadowBait will pass it to the shared Playwright pipeline and return a traceable evidence package."} actions={<><button className="primary-cta" onClick={startInspection} disabled={scan.running}>{scan.running ? 'INSPECTION RUNNING…' : scan.completed ? 'RUN INSPECTION AGAIN' : 'START INSPECTION'} <span>→</span></button>{scan.completed > 0 && !scan.running && <button className="secondary-cta" onClick={() => navigate(`/results/${encodeURIComponent(scan.scanId)}`)}>OPEN RESULTS</button>}</>} />{scan.error && <div className="inspection-error">{scan.error}</div>}<section className="target-card"><div><label htmlFor="target-url">TARGET WEBSITE URL</label><input id="target-url" value={targetUrl} onChange={(event) => setTargetUrl(event.target.value)} placeholder="https://www.flipkart.com/" onKeyDown={(event) => { if (event.key === 'Enter') startInspection(); }} /><small>{flipkartMode ? "Flipkart mode: 6 public pages · 13 categories · read-only evidence" : "Demo target: https://your-demo-site.example · Local: http://127.0.0.1:3000"}</small></div><div className="target-ready"><span>●</span>{scan.running ? 'SCANNING TARGET' : 'READY TO SCAN'}</div></section><section className="artifact-input-card"><div><span className="eyebrow">SECOND INPUT · SCREENSHOT OR FILE</span><h2>Analyze an artifact</h2><p>Upload a screenshot for OCR-based signals, or HTML, text, JSON, Markdown, or PDF for content analysis. The artifact is kept as evidence.</p></div><div className="artifact-input-actions"><input id="artifact-upload" type="file" accept="image/*,.html,.htm,.txt,.md,.json,.csv,.pdf" onChange={(event) => setUploadFile(event.target.files?.[0] || null)} /><button className="secondary-cta" onClick={startArtifactScan} disabled={scan.running || !uploadFile}>{uploadFile ? `ANALYZE ${uploadFile.name}` : "CHOOSE A FILE"} <span>→</span></button></div></section><div className="inspection-note"><strong>{flipkartMode ? "Flipkart coverage." : "Inspection scope."}</strong><span>{flipkartMode ? "Six public pages are evaluated across all 13 categories; potential matches remain subject to human review." : "Evidence is captured before interpretation."}</span></div><section className="inspection-status"><div className="status-copy"><span className={scan.running ? 'live-dot running' : 'live-dot'} />{scan.message}</div><div className="progress-track"><span style={{ width: `${progress}%` }} /></div><strong>{scan.completed}/{scan.total}</strong></section><div className="inspection-meta">{scan.meta && <><span>SCAN {scan.meta.scan_id}</span><span>{scan.meta.browser} · {scan.meta.viewport?.width}×{scan.meta.viewport?.height}</span><span>TARGET {scan.meta.target}</span></>}{scan.scanId && !scan.running && <button className="text-link" onClick={() => navigate('/inspect')}>RESET ACTIVE RUN</button>}</div><section className="panel pages-panel"><div className="section-heading"><div><span className="eyebrow">PAGES INSPECTED</span><h2>Live page trail</h2></div><span className="result-count">{inspectedPages.length}/{scan.total}</span></div>{inspectedPages.length === 0 ? <div className="empty-inspection"><strong>No page captured yet.</strong><p>Each Flipkart page will appear here immediately after its browser capture completes.</p></div> : <div className="page-trail">{inspectedPages.map((page) => <div className="page-trail-row" key={page.url || page.url_final}><span className="pipeline-number">{page.status === "ERROR" ? "!" : "✓"}</span><div><strong>{page.title || "Untitled page"}</strong><small>{page.url || page.url_final}</small></div><span className="pipeline-state">{page.status || "INSPECTED"}</span></div>)}</div>}</section><section className="console-grid"><article className="panel pipeline-panel"><div className="section-heading"><div><span className="eyebrow">LIVE EVENT LOG</span><h2>Inspection pipeline</h2></div><span className="scan-badge">{scan.running ? 'LIVE' : scan.completed ? 'SAVED' : 'IDLE'}</span></div><div className="pipeline-list">{pipeline.map((stage) => <div key={stage.number} className={`pipeline-row ${stage.done ? 'done' : ''} ${stage.active ? 'active' : ''}`}><span className="pipeline-number">{stage.done ? '✓' : stage.number}</span><div><strong>{stage.title}</strong><small>{stage.copy}</small></div><span className="pipeline-state">{stage.done ? 'DONE' : stage.active ? 'NOW' : 'QUEUED'}</span></div>)}</div></article><article className="panel evidence-panel"><div className="section-heading"><div><span className="eyebrow">CAPTURED EVIDENCE</span><h2>What the inspector saw</h2></div><span className="result-count">{visibleFindings.length} findings</span></div>{visibleFindings.length === 0 ? <div className="empty-inspection"><strong>Your evidence cards will appear here.</strong><p>Start the inspection to watch ShadowBait capture screenshots and selectors from the target website.</p></div> : <div className="evidence-grid">{visibleFindings.map((finding) => <EvidenceCard finding={finding} key={finding.id} />)}</div>}</article></section><div className="inspection-note"><strong>Separation boundary:</strong> The target website demonstrates the interface. ShadowBait owns the evidence, analysis, customer impact, and ethical alternative.</div></div>;
}

function EvidenceCard({ finding }) {
  const image = finding.screenshot || finding.image;
  return <article className="evidence-card">{image ? <img src={image} alt={`${finding.name} captured evidence`} /> : <div className="evidence-placeholder"><span>{finding.id}</span><strong>{finding.name}</strong><small>Awaiting captured screenshot</small></div>}<div className="evidence-card-body"><div className="evidence-card-head"><div><span className="mini-verified">{finding.id} · {finding.status || 'VERIFIED'}</span><h3>{finding.name}</h3></div><span className="route-chip">{finding.route}</span></div><div className="finding-metrics"><span>SEVERITY · {finding.severity || "REVIEW"}</span><span>CONFIDENCE · {finding.confidence != null ? `${Math.round(Number(finding.confidence) * 100)}%` : "—"}</span></div><p><strong>Observed:</strong> {finding.observed_text || finding.evidence}</p><p><strong>Selector:</strong> <code>{finding.selector}</code></p><p><strong>Customer impact:</strong> {finding.harm}</p><div className="fix-callout"><strong>Ethical alternative</strong><span>{finding.fix || 'Make the choice clear, neutral, and easy to review.'}</span></div>{finding.m2_findings?.length > 0 && <div className="classification-chip">M2 · {finding.m2_findings[0].severity || 'CLASSIFIED'} · {Math.round(Number(finding.m2_findings[0].confidence || 0) * 100)}% confidence</div>}</div></article>;
}

function UXFindingCard({ finding }) {
  const evidence = finding.evidence || {};
  const box = evidence.bounding_box;
  const screenshot = evidence.screenshot || evidence.image;
  return <article className="ux-finding-card">{screenshot ? <img className="ux-evidence-screenshot" src={screenshot} alt={`${finding.name} evidence screenshot`} /> : <div className="ux-evidence-placeholder">{finding.status === 'NOT_ASSESSABLE' ? 'DOM evidence unavailable for this input' : 'No screenshot attached'}</div>}<div className="ux-finding-head"><div><span className="mini-verified">{finding.category || 'UX'} · {finding.status || 'OBSERVED'}</span><h3>{finding.name}</h3></div><span className="route-chip">{finding.severity || 'INFO'}</span></div><div className="finding-metrics"><span>{finding.id}</span><span>CONFIDENCE · {Math.round(Number(finding.confidence || 0) * 100)}%</span></div><p><strong>Evidence:</strong> {evidence.text || evidence.reason || evidence.selector || finding.scope}</p>{evidence.selector && <p><strong>Element:</strong> <code>{evidence.selector}</code></p>}{box && <p><strong>Location:</strong> x {box.x ?? '—'}, y {box.y ?? '—'}, width {box.width ?? '—'}, height {box.height ?? '—'} px</p>}{evidence.observed_value != null && <p><strong>Measured:</strong> {evidence.observed_value} · threshold {evidence.threshold}</p>}<details className="ux-evidence-details"><summary>View DOM evidence</summary><pre>{evidence.html || 'No DOM snippet available for this input.'}</pre>{evidence.screenshot_file && <small>Artifact: {evidence.screenshot_file}</small>}</details><p><strong>User impact:</strong> {finding.impact}</p><div className="fix-callout"><strong>Recommended improvement</strong><span>{finding.recommendation}</span></div></article>;
}

function ResultsPage({ targetUrl, scan, scanId }) {
  const [persistedReport, setPersistedReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState('');
  const report = scan.report?.scan?.scan_id === scanId || scan.scanId === scanId
    ? scan.report
    : persistedReport;
  useEffect(() => {
    let cancelled = false;
    if (scan.report?.scan?.scan_id === scanId || scan.scanId === scanId) {
      setPersistedReport(scan.report);
      return undefined;
    }
    setLoading(true);
    setLoadError('');
    const apiRoot = window.localStorage.getItem('shadowbait-inspection-api') || '';
    fetch(`${apiRoot}/api/scans/${encodeURIComponent(scanId)}/report`)
      .then((response) => response.ok ? response.json() : response.json().catch(() => ({})).then((body) => Promise.reject(new Error(body.error || 'Saved report could not be loaded.'))))
      .then((data) => { if (!cancelled) setPersistedReport(data); })
      .catch((error) => { if (!cancelled) setLoadError(error.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [scanId, scan.report, scan.scanId]);
  const findings = report?.findings || [];
  const uxFindings = report?.ux_findings || [];
  const summary = report?.summary || {};
  const risk = report?.risk || {};
  const riskLevel = risk.risk_level || summary.risk_level || 'REVIEW';
  const score = risk.risk_score ?? summary.risk_score ?? '—';
  return <div className="page-wrap results-page"><div className="breadcrumb">Home <span>/</span> Evidence <span>/</span> {scanId}</div>{loading && <div className="inspection-note"><strong>Loading saved report…</strong><span>Reading the persisted evidence package for this scan.</span></div>}{loadError && <div className="inspection-error">{loadError}</div>}<PageIntro eyebrow="SAVED INSPECTION RESULT" title="Evidence, explained." copy="This result keeps the target, screenshots, classifications, risk score, customer impact, and ethical alternatives together for review." actions={<><button className="primary-cta" onClick={() => downloadJson(report || { scan: { target: targetUrl }, findings, summary })}>DOWNLOAD JSON <span>↓</span></button><button className="secondary-cta" onClick={() => navigate('/diff')}>OPEN INTERACTIVE DIFF</button></>} /><section className="result-summary"><div><span className="eyebrow">TARGET WEBSITE</span><strong>{report?.scan?.target || targetUrl}</strong><small>{report?.scan?.finished_at || scan.meta?.finished_at || 'Live result'}</small></div><div className={`risk-orb ${typeof score === 'number' ? 'scored' : 'unscored'}`}><span>OVERALL RISK</span><strong>{typeof score === 'number' ? riskLevel : 'NOT SCORED'}</strong><em>{typeof score === 'number' ? `${score.toFixed(1)} points` : 'Run an inspection first'}</em></div></section>{report?.scan?.inspection_status && report.scan.inspection_status !== 'INSPECTED' && <div className="inspection-note"><strong>{report.scan.inspection_status} · HTTP {report.scan.http_status ?? 'status unavailable'}</strong><span>{report.scan.message}</span></div>}<section className="results-kpis"><Kpi label="CAPTURED" value={summary.captured_findings ?? summary.verified_findings ?? findings.length} note="evidence-backed candidates" /><Kpi label="M2 CLASSIFIED" value={summary.m2_classified_findings ?? summary.m2_verified_findings ?? 0} note="language findings" /><Kpi label="HIGH SEVERITY" value={summary.high_severity_findings ?? 0} note="items for review" /><Kpi label="MAPPED" value={summary.compliance_mapped_findings ?? report?.compliance?.mapped_findings ?? 0} note="technical mappings" /></section><section className="impact-banner"><div><span className="eyebrow">CUSTOMER IMPACT LENS</span><h2>What changed for the person on the other side of the screen?</h2></div><p>Every finding should answer more than “what is this pattern?” It should show the decision pressure, cost, confusion, or commitment it can create.</p></section><section className="results-evidence"><div className="section-heading"><div><span className="eyebrow">EVIDENCE LEDGER</span><h2>Every captured finding</h2></div><span className="result-count">{findings.length} findings</span></div>{findings.length === 0 && report?.scan?.message && <div className="empty-inspection"><strong>No findings were produced for this scan.</strong><p>{report.scan.message}</p></div>}<div className="results-list">{findings.map((finding) => <EvidenceCard finding={finding} key={`${finding.id}-${finding.route}`} />)}</div></section>{uxFindings.length > 0 && <section className="ux-review"><div className="section-heading"><div><span className="eyebrow">UX QUALITY REVIEW</span><h2>Accessibility and readability</h2></div><span className="result-count">{uxFindings.length} observations</span></div><div className="ux-review-summary"><span>ACCESSIBILITY · {summary.accessibility_findings ?? uxFindings.filter((item) => item.category === 'ACCESSIBILITY').length}</span><span>READABILITY · {summary.readability_findings ?? uxFindings.filter((item) => item.category === 'READABILITY').length}</span><span>NOT ASSESSABLE · {summary.ux_not_assessable ?? uxFindings.filter((item) => item.status === 'NOT_ASSESSABLE').length}</span></div><div className="ux-findings-grid">{uxFindings.map((finding, index) => <UXFindingCard finding={finding} key={`${finding.id}-${index}`} />)}</div><p className="ux-disclaimer">These are evidence-backed heuristics, not a complete WCAG certification or legal conclusion.</p></section>}<div className="overview-note"><strong>Review boundary.</strong><span>Risk and compliance values are explainable prototype outputs. They support human review and do not determine legal liability.</span></div></div>;
}

function Kpi({ label, value, note }) { return <div className="kpi"><span className="eyebrow">{label}</span><strong>{value}</strong><small>{note}</small></div>; }

function GuidelinesPage() {
  const [filter, setFilter] = useState('ALL');
  const [selected, setSelected] = useState('01');
  const filtered = GUIDELINES.filter(([id]) => filter === 'ALL' || patternStatus(id) === filter);
  return <div className="page-wrap guidelines-page"><div className="breadcrumb">Home <span>/</span> Guidelines</div><PageIntro eyebrow="HOW TO CHECK A DARK PATTERN" title="A living review system." copy="Explore all 13 categories as an interactive atlas. Select a signal, compare its status, and use the review question to turn a visual suspicion into a documented observation." actions={<button className="primary-cta" onClick={() => navigate('/inspect')}>APPLY TO A URL <span>→</span></button>} /><PatternAtlas compact /><section className="guideline-workbench"><div className="workbench-top"><div><span className="eyebrow">GUIDELINE LIBRARY · 13 CATEGORIES</span><h2>Filter the review lens.</h2></div><div className="filter-tabs">{['ALL', 'VERIFIED', 'REVIEW', 'EXCLUDED'].map((option) => <button className={filter === option ? 'active' : ''} onClick={() => setFilter(option)} key={option}>{option}<span>{option === 'ALL' ? 13 : GUIDELINES.filter(([id]) => patternStatus(id) === option).length}</span></button>)}</div></div><div className="guideline-grid">{filtered.map(([number, title, copy, tag, question]) => <article className={`guideline-card ${selected === number ? 'selected' : ''}`} onClick={() => setSelected(number)} key={number}><div className="guideline-card-top"><span className="guideline-number">{number}</span><span className={`status-token ${patternStatus(number).toLowerCase()}`}>{patternStatus(number)}</span></div><span className="guideline-tag">{tag}</span><h2>{title}</h2><p>{copy}</p><div className="guideline-question"><strong>Ask:</strong><span>{question}</span></div>{selected === number && <div className="guideline-expanded"><span>REVIEW MODE</span><strong>{patternStatus(number) === 'VERIFIED' ? 'Evidence fixture available' : patternStatus(number) === 'EXCLUDED' ? 'Safe demo boundary' : 'Candidate category for future fixtures'}</strong></div>}</article>)}</div></section><section className="review-checklist"><div><span className="eyebrow">THE SHADOWBAIT CHECKLIST</span><h2>Document before you conclude.</h2><p>Capture the route, the visible text, the selector, the state transition, the customer impact, and the least manipulative alternative.</p></div><div className="checklist-items"><span>✓ Preserve the original state</span><span>✓ Record the full journey</span><span>✓ Separate observation from legal conclusion</span><span>✓ Explain the customer impact</span></div></section></div>;
}

function CaseStudiesPage() { return <div className="page-wrap case-studies-page"><div className="breadcrumb">Home <span>/</span> Case Studies</div><PageIntro eyebrow="DOCUMENTED CONSEQUENCES" title="The patterns have a paper trail." copy="A stronger review does not stop at naming a pattern. It connects the interface to a public record, a measurable customer cost, and a design decision a team can change." /><section className="case-stat-grid"><div><strong>$2.5B</strong><span>Amazon Prime settlement</span></div><div><strong>35M</strong><span>estimated consumers in redress figure</span></div><div><strong>$245M</strong><span>Epic consumer refunds</span></div><div><strong>$100M</strong><span>Vonage refunds</span></div></section><div className="case-grid">{CASE_STUDIES.map((item) => <article className="case-card" key={item.title}><div className={`case-visual ${item.accent}`}><img src={item.image} alt={`${item.title} source visual`} /><span>{item.stat}</span><small>{item.label}</small></div><span className="case-label">{item.label}</span><h2>{item.title}</h2><span className="case-pattern">{item.pattern}</span><p>{item.summary}</p><div className="case-metric"><strong>{item.stat}</strong><span>{item.statLabel}</span><small>{item.detail}</small></div><a href={item.source} target="_blank" rel="noreferrer">Read the official source ↗</a></article>)}</div><div className="case-disclaimer"><strong>Presentation wording:</strong><span>Say “the regulator alleged” for complaints, “the order required” for finalized orders, and “the report describes” for broader research findings. Figures are shown with their source dates.</span></div></div>; }

function InteractiveDiffPage({ scan, targetUrl }) {
  const flipkartTarget = isFlipkartTarget(targetUrl);
  const hasLiveReport = Boolean(scan.report);
  const findings = hasLiveReport
    ? (scan.report.findings || [])
    : flipkartTarget
      ? []
      : [];
  const [selectedKey, setSelectedKey] = useState('');
  const findingKey = (finding, index) => `${finding.id}-${finding.route}-${index}`;
  const selectedIndex = findings.findIndex((finding, index) => findingKey(finding, index) === selectedKey);
  const selected = findings[selectedIndex >= 0 ? selectedIndex : 0];

  return <div className="page-wrap diff-page">
    <div className="breadcrumb">Home <span>/</span> Interactive Diff</div>
    <PageIntro
      eyebrow="CAPTURED STATE → ETHICAL ALTERNATIVE"
      title={hasLiveReport ? "Compare captured evidence with a clearer alternative." : "Make the customer impact visible."}
      copy={hasLiveReport
        ? "This view uses evidence captured in your latest inspection. Heuristic candidates require human review and are not confirmed violations."
        : "The diff connects an observed interface choice to its customer impact and a clearer alternative."}
    />
    {findings.length === 0
      ? <section className="panel empty-inspection">
        <strong>{scan.report?.scan?.inspection_status === 'NO_CONTENT'
          ? "The website returned no visible page content."
          : scan.report?.scan?.inspection_status === 'BLOCKED'
            ? "The website blocked this inspection."
            : flipkartTarget ? "No Flipkart evidence to compare yet." : "No captured findings yet."}</strong>
        <p>{scan.report?.scan?.message || (flipkartTarget
          ? "Run a Flipkart inspection first. The diff will use only evidence-backed findings from that scan."
          : "Start an inspection to populate the diff with captured findings.")}</p>
        <button className="primary-cta" onClick={() => navigate('/inspect')}>OPEN INSPECTION <span>→</span></button>
      </section>
      : <div className="diff-shell">
        <aside className="diff-sidebar">
          <span className="eyebrow">SELECT A FINDING</span>
          {findings.map((finding, index) => <button
            className={(selectedIndex >= 0 ? selectedIndex : 0) === index ? 'selected' : ''}
            onClick={() => setSelectedKey(findingKey(finding, index))}
            key={findingKey(finding, index)}
          ><span>{finding.id}</span><strong>{finding.name}</strong></button>)}
        </aside>
        {selected && <section className="diff-main">
          <div className="diff-heading">
            <div><span className="case-pattern">{selected.category || selected.compliance?.principle || 'Captured evidence'}</span><h2>{selected.name}</h2><p>{selected.observed_text || selected.evidence}</p></div>
            <span className="risk-pill">{selected.m2_findings?.length ? 'LANGUAGE CLASSIFIED' : 'HUMAN REVIEW'}</span>
          </div>
          <div className="diff-panels">
            <article className="diff-panel before">
              <span className="panel-label">CAPTURED STATE · {selected.route || 'DEMO EVIDENCE'}</span>
              {selected.screenshot
                ? <img className="live-diff-screenshot" src={selected.screenshot} alt={`Captured ${selected.name} evidence`} />
                : <div className="mock-browser"><div className="mock-top"><i /><i /><i /></div><div className="mock-content"><div className="mock-title">{selected.name === 'False Urgency' ? 'Only 2 left' : selected.name}</div><div className="mock-alert">{selected.observed_text || selected.evidence}</div><div className="mock-button muted">Captured choice</div></div></div>}
              <p><strong>Customer impact:</strong> {selected.harm}</p>
              {selected.compliance && <p><strong>Heuristic mapping:</strong> {selected.compliance.principle}</p>}
            </article>
            <div className="diff-arrow">→</div>
            <article className="diff-panel after">
              <span className="panel-label">ETHICAL ALTERNATIVE</span>
              <div className="mock-browser ethical"><div className="mock-top"><i /><i /><i /></div><div className="mock-content"><div className="mock-title">Clear choice</div><div className="mock-alert calm">{selected.compliance?.recommendation || selected.fix || 'Make the choice and its consequences clear, neutral, and easy to review.'}</div><div className="mock-button">Continue</div></div></div>
              <p><strong>Review status:</strong> {selected.m2_status || 'Heuristic candidate; requires human review.'}</p>
            </article>
          </div>
          <div className="diff-principle"><span className="eyebrow">DESIGN PRINCIPLE</span><strong>{selected.compliance?.principle || 'Make the honest choice as easy to understand as the persuasive one.'}</strong></div>
        </section>}
      </div>}
  </div>;
}

function ArchitecturePage() {
  const steps = [
    { number: '01', title: 'Target URL', kicker: 'THE INPUT', copy: 'The presenter enters the separate normal demo-site address. ShadowBait validates the protocol, normalizes the route, and stores the active target for a repeatable run.', tech: ['React state', 'URL API', 'localStorage'], input: 'https://morrow-market.example', output: 'Normalized target + scan request' },
    { number: '02', title: 'Browser runner', kicker: 'THE OBSERVER', copy: 'The shared API opens a fresh Chromium context through Playwright. It visits the target like a real customer instead of relying on a static page dump.', tech: ['Flask API', 'Playwright', 'Chromium'], input: 'Normalized target', output: 'Routes, DOM state, viewport context' },
    { number: '03', title: 'Evidence package', kicker: 'THE LEDGER', copy: 'Each step preserves the visible text, selector, screenshot, URL, and state transition. Server-sent events stream progress into the console while the run is still happening.', tech: ['SSE stream', 'Screenshots', 'JSON + SQLite'], input: 'Browser observations', output: 'Traceable evidence cards' },
    { number: '04', title: 'Detection layer', kicker: 'THE CLASSIFIER', copy: 'Rules map stable interface hooks to supported categories. The compatibility layer can add language findings without hiding the original technical observation.', tech: ['Pattern rules', 'M2 NLP', 'Confidence score'], input: 'Evidence cards', output: 'Pattern + status + confidence' },
    { number: '05', title: 'Impact model', kicker: 'THE EXPLAINER', copy: 'ShadowBait translates a label into a customer-impact statement: pressure, cost, confusion, or unwanted commitment, followed by the least manipulative fix.', tech: ['Risk summary', 'Impact copy', 'Ethical fix'], input: 'Classified finding', output: 'Reviewable explanation' },
    { number: '06', title: 'Review workspace', kicker: 'THE PRESENTATION', copy: 'The platform turns the run into a judge-ready story: evidence ledger, interactive diff, 13 guidelines, regulatory case studies, and an exportable report.', tech: ['React routes', 'Interactive Diff', 'PDF / JSON export'], input: 'Complete report', output: 'Evidence before judgment' },
  ];
  const [active, setActive] = useState(0);
  const step = steps[active];
  return <div className="page-wrap architecture-page"><div className="breadcrumb">Home <span>/</span> Architecture</div><PageIntro eyebrow="SYSTEM EXPLANATION · GUIDED MODE" title="Follow the evidence, one node at a time." copy="Meet the investigator behind the flow. Select a stage to see what enters the system, what technology runs it, and what the next team can review." actions={<button className="primary-cta" onClick={() => navigate('/inspect')}>TRY THE LIVE FLOW <span>→</span></button>} /><section className="architecture-explorer"><aside className="architect-guide"><div className="architect-portrait"><img src="/assets/shadowbait-investigator-avatar.jpg" alt="Fictional ShadowBait product investigator" /><span className="portrait-pulse" /></div><span className="eyebrow">YOUR GUIDE · MAYA</span><h2>“I follow the trail, not just the label.”</h2><p>Maya is the fictional product investigator guiding the presentation. She keeps the target website, technical evidence, and ethical interpretation in separate layers.</p><div className="guide-status"><span className="live-dot running" /><div><small>ACTIVE NODE</small><strong>{step.number} · {step.title}</strong></div></div><div className="guide-tip"><span>TIP</span><strong>Click the next node as you explain the hand-off.</strong></div></aside><section className="architecture-map"><div className="map-header"><div><span className="eyebrow">THE SHADOWBAIT PIPELINE</span><h2>Observe → preserve → explain</h2></div><span className="map-counter">{String(active + 1).padStart(2, '0')} / {String(steps.length).padStart(2, '0')}</span></div><div className="node-flow"><div className="node-track" />{steps.map((item, index) => <button key={item.number} className={`flow-node ${active === index ? 'active' : ''} ${index < active ? 'done' : ''}`} onClick={() => setActive(index)}><span className="node-number">{index < active ? '✓' : item.number}</span><span className="node-copy"><small>{item.kicker}</small><strong>{item.title}</strong></span><span className="node-arrow">{index === steps.length - 1 ? '↘' : '→'}</span></button>)}</div><article className="architecture-detail"><div className="detail-heading"><div><span className="eyebrow">NODE {step.number} · {step.kicker}</span><h2>{step.title}</h2></div><span className="detail-state">{active === steps.length - 1 ? 'PRESENTATION READY' : 'HAND-OFF READY'}</span></div><p>{step.copy}</p><div className="detail-columns"><div><small>INPUT</small><strong>{step.input}</strong></div><div><small>OUTPUT</small><strong>{step.output}</strong></div></div><div className="tech-stack"><span>TECH STACK AT THIS NODE</span><div>{step.tech.map((technology) => <b key={technology}>{technology}</b>)}</div></div><div className="detail-actions"><button className="secondary-cta" onClick={() => setActive((active + steps.length - 1) % steps.length)}>← PREVIOUS</button><button className="primary-cta" onClick={() => setActive((active + 1) % steps.length)}>{active === steps.length - 1 ? 'REPLAY FLOW' : 'NEXT NODE'} <span>→</span></button></div></article></section></section><section className="architecture-boundary architecture-boundary-enhanced"><div><span className="eyebrow">SEPARATION BOUNDARY</span><h2>Demo website ≠ ShadowBait</h2><p>The target demonstrates the interface. The platform owns the inspection, evidence, impact analysis, and ethical alternative.</p></div><div className="boundary-lanes"><div><span>DEMO TARGET</span><strong>Normal storefront</strong><small>Routes · DOM · customer states</small></div><div><span>SHADOWBAIT</span><strong>Evidence workspace</strong><small>Capture · classify · explain · improve</small></div></div></section></div>;
}

function downloadJson(payload) { const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }); const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = 'shadowbait-inspection-report.json'; link.click(); URL.revokeObjectURL(url); }

createRoot(document.getElementById('root')).render(<App />);
