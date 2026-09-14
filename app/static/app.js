const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value = '') => String(value).replace(/[&<>'"]/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));

const state = { tickets: [], docs: [], stats: {} };

async function getJson(url, options = {}) {
  const response = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...options });
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || 'Something went wrong');
  return response.json();
}

function relativeTime(dateString) {
  const date = new Date(dateString);
  const seconds = Math.max(1, Math.floor((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function renderStats() {
  $('#openStat').textContent = state.stats.open ?? '—';
  $('#urgentStat').textContent = state.stats.urgent ?? '—';
  $('#automationStat').textContent = state.stats.automation_rate ? `${state.stats.automation_rate}%` : '—';
  $('#responseStat').textContent = state.stats.avg_response ?? '—';
  $('#queueCount').textContent = state.stats.open ?? '—';
}

function priorityClass(priority) { return String(priority || '').toLowerCase(); }
function statusClass(status) { return status === 'In progress' ? 'progress' : String(status || '').toLowerCase(); }

function renderTickets(tickets = state.tickets) {
  const rows = $('#ticketRows');
  if (!tickets.length) {
    rows.innerHTML = '<tr><td colspan="6" class="loading">No tickets match this view.</td></tr>';
    return;
  }
  rows.innerHTML = tickets.slice(0, 7).map(ticket => `
    <tr>
      <td><strong>${escapeHtml(ticket.ticket_number)}</strong><small>${escapeHtml(ticket.title)}</small></td>
      <td><strong>${escapeHtml(ticket.assignee || 'Service Desk')}</strong><small>${escapeHtml(ticket.category)}</small></td>
      <td><span class="priority ${priorityClass(ticket.priority)}">${escapeHtml(ticket.priority)}</span></td>
      <td><span class="status-pill ${statusClass(ticket.status)}">${escapeHtml(ticket.status)}</span></td>
      <td>${relativeTime(ticket.created_at)}</td>
      <td><button class="row-more" aria-label="More options">•••</button></td>
    </tr>`).join('');
  $('#queueSummary').textContent = `Showing ${Math.min(tickets.length, 7)} of ${tickets.length} tickets`;
}

function renderDocs(docs = state.docs) {
  const list = $('#docList');
  if (!docs.length) { list.innerHTML = '<div class="loading">No matching runbooks.</div>'; return; }
  list.innerHTML = docs.slice(0, 4).map(doc => `
    <a class="doc-item" href="#knowledge" data-doc-id="${escapeHtml(doc.id)}">
      <div class="doc-title"><i>⌁</i><span>${escapeHtml(doc.title)}</span></div>
      <div class="doc-meta"><span>${escapeHtml(doc.category)} · updated ${escapeHtml(doc.updated)}</span><span class="doc-score">${doc.score ? `${Math.round(doc.score * 100)}% match` : 'Runbook'}</span></div>
    </a>`).join('');
}

async function loadDashboard() {
  try {
    const [stats, tickets, docs] = await Promise.all([getJson('/api/stats'), getJson('/api/tickets'), getJson('/api/docs')]);
    state.stats = stats; state.tickets = tickets; state.docs = docs;
    renderStats(); renderTickets(); renderDocs();
  } catch (error) {
    showToast(error.message);
  }
}

function renderResult(result) {
  const panel = $('#resultPanel');
  const ticket = result.ticket;
  panel.innerHTML = `
    <div class="result-header">
      <div><div class="result-kicker">✦ DIAGNOSIS COMPLETE · ${escapeHtml(result.run_id)}</div><h2>${escapeHtml(result.intent)}</h2><p>${escapeHtml(result.summary)} <span class="status-pill ${priorityClass(result.priority)}">${escapeHtml(result.priority)} priority</span></p></div>
      <div class="confidence" title="Agent confidence">${escapeHtml(result.confidence)}%</div>
    </div>
    <div class="result-body">
      <div><h4>RECOMMENDED NEXT STEPS</h4><div class="action-list">${result.actions.map((action, index) => `<div class="action-item"><span class="action-number">${index + 1}</span><div><strong>${escapeHtml(action.label)}</strong><p>${escapeHtml(action.detail)}</p></div></div>`).join('')}</div></div>
      <div><h4>RETRIEVED EVIDENCE</h4><div class="evidence-list">${result.evidence.length ? result.evidence.map(doc => `<div class="evidence-item"><strong>${escapeHtml(doc.title)}</strong><p>${escapeHtml(doc.excerpt)}</p><span>${Math.round(doc.score * 100)}% relevance</span></div>`).join('') : '<div class="evidence-item"><p>No matching documents found. Add a runbook to improve future diagnoses.</p></div>'}</div></div>
    </div>
    <div class="result-footer"><span>${result.agent_trace.map(escapeHtml).join(' · ')}</span>${ticket ? `<span class="ticket-created">Ticket ${escapeHtml(ticket.ticket_number)} created and routed →</span>` : '<span>Ticket creation was skipped</span>'}</div>`;
  panel.classList.remove('hidden');
  panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

async function runDiagnosis() {
  const button = $('#diagnoseBtn');
  const message = $('#issueInput').value.trim();
  if (message.length < 3) { showToast('Describe the issue first.'); $('#issueInput').focus(); return; }
  button.disabled = true; button.innerHTML = '<span class="button-sparkle">✦</span> Thinking…';
  try {
    const result = await getJson('/api/diagnose', { method: 'POST', body: JSON.stringify({ message, create_ticket: true }) });
    renderResult(result);
    await loadDashboard();
    showToast(result.ticket ? `Created ${result.ticket.ticket_number}` : 'Diagnosis complete');
  } catch (error) { showToast(error.message); }
  finally { button.disabled = false; button.innerHTML = '<span class="button-sparkle">✦</span> Run diagnosis <span class="arrow">→</span>'; }
}

function showToast(message) { const toast = $('#toast'); toast.textContent = message; toast.classList.add('show'); clearTimeout(window.toastTimer); window.toastTimer = setTimeout(() => toast.classList.remove('show'), 3000); }

$('#diagnoseBtn').addEventListener('click', runDiagnosis);
$('#issueInput').addEventListener('keydown', (event) => { if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') runDiagnosis(); });
$('.suggestions').addEventListener('click', (event) => { const prompt = event.target.closest('[data-prompt]')?.dataset.prompt; if (prompt) { $('#issueInput').value = prompt; $('#issueInput').focus(); } });
$('#newRequestBtn').addEventListener('click', () => { $('#issueInput').value = ''; $('#issueInput').focus(); $('#resultPanel').classList.add('hidden'); });
$('#statusFilter').addEventListener('click', () => {
  const options = ['All', 'Open', 'In progress', 'Resolved'];
  const current = $('#statusFilter').dataset.value || 'All';
  const next = options[(options.indexOf(current) + 1) % options.length];
  $('#statusFilter').dataset.value = next; $('#statusFilter').innerHTML = `${next === 'All' ? 'All statuses' : next} <span>⌄</span>`;
  renderTickets(next === 'All' ? state.tickets : state.tickets.filter(ticket => ticket.status === next));
});

loadDashboard();
