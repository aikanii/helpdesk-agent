const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value = '') => String(value).replace(/[&<>'"]/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));

const state = { tickets: [], docs: [], stats: {}, notifications: [], token: localStorage.getItem('relay_token'), user: null, showAllTickets: false, showAllDocs: false };

async function getJson(url, options = {}) {
  const isFormData = options.body instanceof FormData;
  const headers = { ...(isFormData ? {} : { 'Content-Type': 'application/json' }), ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(url, { ...options, headers });
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || 'Something went wrong');
  return response.json();
}

function updateUserProfile(user) {
  state.user = user;
  const initials = user.full_name.split(/\s+/).map(part => part[0]).join('').slice(0, 2).toUpperCase();
  $('#profileName').textContent = user.full_name;
  $('#profileRole').textContent = user.role.charAt(0).toUpperCase() + user.role.slice(1);
  $('#profileAvatar').textContent = initials;
  $('#topAvatar').textContent = initials;
  $('#uploadKnowledgeBtn')?.classList.toggle('hidden-app', !['admin', 'manager'].includes(user.role));
  $('#inviteUserBtn')?.classList.toggle('hidden-app', user.role !== 'admin');
}

function showAuthenticatedApp(user) {
  updateUserProfile(user);
  $('#authGate').classList.add('hidden-app');
  $('#appShell').classList.remove('hidden-app');
  loadDashboard();
  loadNotifications();
}

function showLogin() {
  $('#appShell').classList.add('hidden-app');
  $('#authGate').classList.remove('hidden-app');
  $('#loginEmail').focus();
}

async function authenticate() {
  if (!state.token) { showLogin(); return; }
  try {
    const user = await getJson('/api/auth/me');
    showAuthenticatedApp(user);
  } catch (error) {
    localStorage.removeItem('relay_token');
    state.token = null;
    showLogin();
  }
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
function statusClass(status) { if (status === 'In progress') return 'progress'; if (status === 'Needs review') return 'needs-review'; return String(status || '').toLowerCase(); }

function renderTickets(tickets = state.tickets) {
  const rows = $('#ticketRows');
  if (!tickets.length) {
    rows.innerHTML = '<tr><td colspan="6" class="loading">No tickets match this view.</td></tr>';
    return;
  }
  const visibleTickets = state.showAllTickets ? tickets : tickets.slice(0, 7);
  rows.innerHTML = visibleTickets.map(ticket => `
    <tr class="ticket-row" data-ticket-id="${ticket.id}">
      <td><strong>${escapeHtml(ticket.ticket_number)}</strong><small>${escapeHtml(ticket.title)}</small></td>
      <td><strong>${escapeHtml(ticket.assignee || 'Service Desk')}</strong><small>${escapeHtml(ticket.category)}</small></td>
      <td><span class="priority ${priorityClass(ticket.priority)}">${escapeHtml(ticket.priority)}</span></td>
      <td><span class="status-pill ${statusClass(ticket.status)}">${escapeHtml(ticket.status)}</span></td>
      <td>${relativeTime(ticket.created_at)}</td>
      <td><button class="row-more" aria-label="More options">•••</button></td>
    </tr>`).join('');
  $('#queueSummary').textContent = state.showAllTickets ? `Showing all ${tickets.length} tickets` : `Showing ${Math.min(tickets.length, 7)} of ${tickets.length} tickets`;
}

function renderDocs(docs = state.docs) {
  const list = $('#docList');
  if (!docs.length) { list.innerHTML = '<div class="loading">No matching runbooks.</div>'; return; }
  const visibleDocs = state.showAllDocs ? docs : docs.slice(0, 4);
  list.innerHTML = visibleDocs.map(doc => `
    <a class="doc-item" href="#knowledge" data-doc-id="${escapeHtml(doc.id)}">
      <div class="doc-title"><i>⌁</i><span>${escapeHtml(doc.title)}</span></div>
      <div class="doc-meta"><span>${escapeHtml(doc.category)} · updated ${escapeHtml(doc.updated)}</span><span class="doc-score">${doc.score ? `${Math.round(doc.score * 100)}% match` : 'Runbook'}</span></div>
    </a>`).join('');
}

function switchView(view) {
  const overviewSelectors = ['.page-heading', '.hero-grid', '.result-panel', '.stats-grid', '.lower-grid'];
  overviewSelectors.forEach(selector => document.querySelector(selector)?.classList.toggle('secondary-hidden', view !== 'overview'));
  document.querySelectorAll('.workspace-view').forEach(section => section.classList.add('hidden-app'));
  if (view !== 'overview') document.querySelector(`#${view}View`)?.classList.remove('hidden-app');
  document.querySelectorAll('.nav-link[data-view]').forEach(link => link.classList.toggle('active', link.dataset.view === view));
  if (view === 'analytics') loadAnalytics();
  if (view === 'team') loadTeam();
  if (view === 'settings') loadSettings();
}

async function loadAnalytics() {
  try {
    const data = await getJson('/api/analytics/overview');
    $('#analyticsTickets').textContent = data.totals.tickets;
    $('#analyticsOpen').textContent = data.totals.open;
    $('#analyticsBreaches').textContent = data.totals.sla_breached;
    $('#analyticsAutomation').textContent = `${data.totals.automation_rate}%`;
    $('#analyticsJobs').textContent = data.totals.jobs;
    $('#analyticsJobsMeta').textContent = `${data.totals.jobs_completed} completed · ${data.totals.jobs_failed} failed`;
    $('#feedbackRate').textContent = `${data.totals.feedback_helpful_rate}%`;
    $('#feedbackBar').style.width = `${data.totals.feedback_helpful_rate}%`;
    const maxVolume = Math.max(1, ...data.daily_volume.map(item => item.tickets));
    $('#volumeChart').innerHTML = data.daily_volume.map(item => `<div class="volume-column"><div class="volume-bar" style="height:${Math.max(8, item.tickets / maxVolume * 100)}%" title="${item.tickets} tickets"></div><small>${item.date.slice(5)}</small></div>`).join('');
    const renderBars = (values, formatter = value => value) => { const max = Math.max(1, ...Object.values(values)); return Object.entries(values).sort((a,b) => b[1]-a[1]).map(([label,value]) => `<div class="bar-row"><span>${escapeHtml(label)}</span><div><i style="width:${Math.max(4, value / max * 100)}%"></i></div><b>${formatter(value)}</b></div>`).join('') || '<div class="loading">No data yet.</div>'; };
    $('#categoryChart').innerHTML = renderBars(data.by_category);
    $('#teamChart').innerHTML = renderBars(data.by_team, value => value);
  } catch (error) { showToast(error.message); }
}

async function loadTeam() {
  try {
    const [users, rules] = await Promise.all([getJson('/api/auth/users'), getJson('/api/routing/rules')]);
    $('#teamRows').innerHTML = users.map(user => `<tr><td><strong>${escapeHtml(user.full_name)}</strong><small>${escapeHtml(user.email)}</small></td><td>${state.user.role === 'admin' && user.id !== state.user.id ? `<select class="role-select" data-role-id="${user.id}"><option value="requester" ${user.role === 'requester' ? 'selected' : ''}>requester</option><option value="agent" ${user.role === 'agent' ? 'selected' : ''}>agent</option><option value="manager" ${user.role === 'manager' ? 'selected' : ''}>manager</option><option value="admin" ${user.role === 'admin' ? 'selected' : ''}>admin</option></select>` : `<span class="role-pill">${escapeHtml(user.role)}</span>`}</td><td><span class="status-pill ${user.is_active ? 'resolved' : ''}">${user.is_active ? 'Active' : 'Inactive'}</span></td><td>${state.user.role === 'admin' && user.id !== state.user.id ? `<button class="row-action" data-user-id="${user.id}" data-user-active="${!user.is_active}">${user.is_active ? 'Deactivate' : 'Activate'}</button>` : ''}</td></tr>`).join('') || '<tr><td colspan="4" class="loading">No team members.</td></tr>';
    $('#routingRows').innerHTML = rules.map(rule => `<div class="routing-row"><div><strong>${escapeHtml(rule.category)}</strong><small>Updated by ${escapeHtml(rule.updated_by)}</small></div><input class="route-team" data-category="${escapeHtml(rule.category)}" value="${escapeHtml(rule.team)}" /><input class="route-sla" data-category="${escapeHtml(rule.category)}" type="number" min="1" max="168" value="${rule.sla_hours}" /><label class="route-toggle"><input class="route-escalate" data-category="${escapeHtml(rule.category)}" type="checkbox" ${rule.auto_escalate_high ? 'checked' : ''}/> High</label><button class="row-action" data-save-rule="${escapeHtml(rule.category)}">Save</button></div>`).join('');
  } catch (error) { $('#teamRows').innerHTML = `<tr><td colspan="4" class="loading">${escapeHtml(error.message)}</td></tr>`; $('#routingRows').innerHTML = `<div class="loading">${escapeHtml(error.message)}</div>`; }
}

async function loadSettings() {
  try {
    const [profile, preferences] = await Promise.all([getJson('/api/auth/me'), getJson('/api/notifications/preferences')]);
    $('#profileNameInput').value = profile.full_name; $('#profileEmailInput').value = profile.email;
    $('#prefInApp').checked = preferences.in_app_enabled; $('#prefEmail').checked = preferences.email_enabled; $('#prefSla').checked = preferences.email_on_sla_breach;
    try {
      const integration = await getJson('/api/integrations/jira/status');
      $('#integrationSettings').innerHTML = `<div class="setting-service"><span class="service-icon ${integration.configured ? 'green' : 'amber'}">J</span><div><strong>Jira Service Management</strong><small>${integration.configured ? `Connected to ${escapeHtml(integration.project_key)}` : 'Not configured'}</small></div><span class="status-pill ${integration.configured ? 'resolved' : 'needs-review'}">${integration.configured ? 'Connected' : 'Setup needed'}</span></div>`;
    } catch (error) { $('#integrationSettings').innerHTML = '<div class="setting-service"><span class="service-icon amber">J</span><div><strong>Jira Service Management</strong><small>Admin access required to view integration status</small></div></div>'; }
  } catch (error) { showToast(error.message); }
}

async function loadNotifications() {
  try {
    const result = await getJson('/api/notifications');
    state.notifications = result.items || [];
    const unread = result.unread_count || 0;
    $('#notificationBadge').textContent = unread ? String(unread > 9 ? '9+' : unread) : '';
    $('#notificationBadge').classList.toggle('visible', unread > 0);
    $('#notificationList').innerHTML = state.notifications.length ? state.notifications.map(item => `<button class="notification-item ${item.read_at ? '' : 'unread'}" data-notification-id="${escapeHtml(item.id)}"><span class="notification-icon">${item.notification_type === 'warning' ? '!' : 'i'}</span><span><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.message)}</small><em>${relativeTime(item.created_at)}</em></span></button>`).join('') : '<div class="notification-empty">You are all caught up.</div>';
  } catch (error) { $('#notificationList').innerHTML = `<div class="notification-empty">${escapeHtml(error.message)}</div>`; }
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
  const routingMessage = ticket?.status === 'Escalated'
    ? `Escalated to ${escapeHtml(ticket.assignee || 'the owning team')} · 2-hour SLA`
    : `Routed to ${escapeHtml(ticket?.assignee || 'Service Desk')}`;
  panel.innerHTML = `
    <div class="result-header">
      <div><div class="result-kicker">✦ DIAGNOSIS COMPLETE · ${escapeHtml(result.run_id)}</div><h2>${escapeHtml(result.intent)}</h2><p>${escapeHtml(result.summary)} <span class="status-pill ${priorityClass(result.priority)}">${escapeHtml(result.priority)} priority</span></p></div>
      <div class="confidence" title="Agent confidence">${escapeHtml(result.confidence)}%</div>
    </div>
    ${result.requires_approval ? `<div class="safety-notice"><strong>Human review required.</strong> Relay paused external or high-impact actions. ${escapeHtml((result.safety_flags || []).join(', '))}</div>` : ''}
    <div class="result-body">
      <div><h4>RECOMMENDED NEXT STEPS</h4><div class="action-list">${result.actions.map((action, index) => `<div class="action-item"><span class="action-number">${index + 1}</span><div><strong>${escapeHtml(action.label)}</strong><p>${escapeHtml(action.detail)}</p></div></div>`).join('')}</div></div>
      <div><h4>RETRIEVED EVIDENCE</h4><div class="evidence-list">${result.evidence.length ? result.evidence.map(doc => `<div class="evidence-item"><strong>${escapeHtml(doc.title)}</strong><p>${escapeHtml(doc.excerpt)}</p><span>${Math.round(doc.score * 100)}% relevance</span></div>`).join('') : '<div class="evidence-item"><p>No matching documents found. Add a runbook to improve future diagnoses.</p></div>'}</div></div>
    </div>
    <div class="result-footer"><span>${result.agent_trace.map(escapeHtml).join(' · ')}</span><div class="result-actions">${ticket ? `<span class="ticket-created">Ticket ${escapeHtml(ticket.ticket_number)} · ${routingMessage} →</span>` : '<span>Ticket creation was skipped</span>'}<span class="feedback-label">Was this helpful?</span><button class="feedback-button" data-rating="helpful" data-run-id="${escapeHtml(result.run_id)}" data-ticket-number="${escapeHtml(ticket?.ticket_number || '')}">Yes</button><button class="feedback-button" data-rating="not_helpful" data-run-id="${escapeHtml(result.run_id)}" data-ticket-number="${escapeHtml(ticket?.ticket_number || '')}">No</button></div></div>`;
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

$('#loginForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button[type="submit"]');
  const error = $('#loginError');
  button.disabled = true;
  error.textContent = '';
  try {
    const result = await getJson('/api/auth/login', { method: 'POST', body: JSON.stringify({ username: $('#loginEmail').value, password: $('#loginPassword').value }) });
    state.token = result.access_token;
    localStorage.setItem('relay_token', state.token);
    showAuthenticatedApp(result.user);
  } catch (requestError) {
    error.textContent = requestError.message || 'Unable to sign in';
  } finally { button.disabled = false; }
});

$('#logoutBtn').addEventListener('click', () => {
  localStorage.removeItem('relay_token');
  state.token = null;
  state.user = null;
  showLogin();
});

document.querySelectorAll('.nav-link[data-view]').forEach(link => link.addEventListener('click', (event) => {
  event.preventDefault();
  const view = link.dataset.view;
  switchView(view);
  if (view === 'overview' && link.getAttribute('href') !== '#overview') document.querySelector(link.getAttribute('href'))?.scrollIntoView({ behavior: 'smooth' });
}));
$('#refreshAnalytics').addEventListener('click', loadAnalytics);

$('#inviteUserBtn').addEventListener('click', async () => {
  const fullName = window.prompt('Teammate name');
  if (!fullName) return;
  const email = window.prompt('Teammate email');
  if (!email) return;
  const password = window.prompt('Temporary password (8+ characters)');
  if (!password) return;
  const role = window.prompt('Role: requester, agent, manager, or admin', 'agent') || 'agent';
  try { await getJson('/api/auth/users', { method: 'POST', body: JSON.stringify({ full_name: fullName, email, password, role }) }); showToast('Teammate added'); await loadTeam(); } catch (error) { showToast(error.message); }
});
$('#teamRows').addEventListener('change', async (event) => {
  const select = event.target.closest('[data-role-id]');
  if (!select) return;
  try { await getJson(`/api/auth/users/${select.dataset.roleId}/role?role=${encodeURIComponent(select.value)}`, { method: 'PATCH' }); showToast('Role updated'); await loadTeam(); } catch (error) { showToast(error.message); await loadTeam(); }
});
$('#teamRows').addEventListener('click', async (event) => {
  const button = event.target.closest('[data-user-id]');
  if (!button) return;
  try { await getJson(`/api/auth/users/${button.dataset.userId}/active?active=${button.dataset.userActive}`, { method: 'PATCH' }); showToast('Team member updated'); await loadTeam(); } catch (error) { showToast(error.message); }
});
$('#routingRows').addEventListener('click', async (event) => {
  const button = event.target.closest('[data-save-rule]');
  if (!button) return;
  const category = button.dataset.saveRule;
  const team = document.querySelector(`.route-team[data-category="${CSS.escape(category)}"]`).value;
  const sla_hours = Number(document.querySelector(`.route-sla[data-category="${CSS.escape(category)}"]`).value);
  const auto_escalate_high = document.querySelector(`.route-escalate[data-category="${CSS.escape(category)}"]`).checked;
  try { await getJson('/api/routing/rules', { method: 'PUT', body: JSON.stringify({ category, team, sla_hours, auto_escalate_high }) }); showToast('Routing rule saved'); await loadTeam(); } catch (error) { showToast(error.message); }
});

$('#profileForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  try { const profile = await getJson('/api/auth/me', { method: 'PATCH', body: JSON.stringify({ full_name: $('#profileNameInput').value, email: $('#profileEmailInput').value }) }); updateUserProfile(profile); $('#profileMessage').textContent = 'Profile saved'; showToast('Profile updated'); } catch (error) { $('#profileMessage').textContent = error.message; }
});
$('#passwordForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  try { await getJson('/api/auth/change-password', { method: 'POST', body: JSON.stringify({ current_password: $('#currentPasswordInput').value, new_password: $('#newPasswordInput').value }) }); $('#passwordMessage').textContent = 'Password updated'; event.target.reset(); showToast('Password updated'); } catch (error) { $('#passwordMessage').textContent = error.message; }
});
$('#notificationPreferencesForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  try { await getJson('/api/notifications/preferences', { method: 'PUT', body: JSON.stringify({ in_app_enabled: $('#prefInApp').checked, email_enabled: $('#prefEmail').checked, email_on_assignment: true, email_on_status_change: true, email_on_sla_breach: $('#prefSla').checked }) }); $('#preferencesMessage').textContent = 'Preferences saved'; showToast('Preferences saved'); } catch (error) { $('#preferencesMessage').textContent = error.message; }
});

$('#notificationBtn').addEventListener('click', (event) => { event.stopPropagation(); $('#notificationPanel').classList.toggle('hidden-app'); });
document.addEventListener('click', (event) => { if (!event.target.closest('#notificationPanel') && !event.target.closest('#notificationBtn')) $('#notificationPanel').classList.add('hidden-app'); });
$('#readAllNotifications').addEventListener('click', async () => { try { await getJson('/api/notifications/read-all', { method: 'POST' }); await loadNotifications(); } catch (error) { showToast(error.message); } });
$('#notificationList').addEventListener('click', async (event) => { const item = event.target.closest('[data-notification-id]'); if (!item) return; try { await getJson(`/api/notifications/${item.dataset.notificationId}/read`, { method: 'PATCH' }); await loadNotifications(); } catch (error) { showToast(error.message); } });
document.querySelectorAll('.more-button').forEach(button => button.addEventListener('click', () => showToast('More workspace actions will be available as this view grows.')));
$('#globalSearchBtn').addEventListener('click', () => { switchView('overview'); $('#issueInput').focus(); });
$('#managePlanBtn').addEventListener('click', () => showToast('Plan management is available to workspace administrators.'));
$('#statusPageBtn').addEventListener('click', () => { switchView('settings'); document.querySelector('#integrationSettings')?.scrollIntoView({ behavior: 'smooth' }); });
$('#viewAllTicketsBtn').addEventListener('click', () => { state.showAllTickets = !state.showAllTickets; $('#viewAllTicketsBtn').innerHTML = state.showAllTickets ? 'Show recent tickets <span>↑</span>' : 'View all tickets <span>→</span>'; renderTickets(); });
$('#browseDocsBtn').addEventListener('click', () => { state.showAllDocs = !state.showAllDocs; $('#browseDocsBtn').innerHTML = state.showAllDocs ? 'Show top runbooks <span>↑</span>' : 'Browse all documentation <span>→</span>'; renderDocs(); });
$('#attachContextBtn').addEventListener('click', () => showToast('Attachments can be added from the ticket timeline after diagnosis.'));
$('#addContextBtn').addEventListener('click', () => { const input = $('#issueInput'); input.value += '\\n\\nContext: '; input.focus(); showToast('Added a context prompt'); });
$('#uploadKnowledgeBtn').addEventListener('click', () => $('#knowledgeFileInput').click());
$('#knowledgeFileInput').addEventListener('change', async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const form = new FormData();
  form.append('file', file);
  try {
    await getJson('/api/docs/upload', { method: 'POST', body: form });
    showToast('Runbook uploaded and indexed');
    await loadDashboard();
  } catch (error) { showToast(error.message); }
  event.target.value = '';
});

$('#diagnoseBtn').addEventListener('click', runDiagnosis);
$('#issueInput').addEventListener('keydown', (event) => { if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') runDiagnosis(); });
$('.suggestions').addEventListener('click', (event) => { const prompt = event.target.closest('[data-prompt]')?.dataset.prompt; if (prompt) { $('#issueInput').value = prompt; $('#issueInput').focus(); } });
$('#newRequestBtn').addEventListener('click', () => { $('#issueInput').value = ''; $('#issueInput').focus(); $('#resultPanel').classList.add('hidden'); });
$('#statusFilter').addEventListener('click', () => {
  const options = ['All', 'Open', 'In progress', 'Needs review', 'Escalated', 'Resolved'];
  const current = $('#statusFilter').dataset.value || 'All';
  const next = options[(options.indexOf(current) + 1) % options.length];
  $('#statusFilter').dataset.value = next; $('#statusFilter').innerHTML = `${next === 'All' ? 'All statuses' : next} <span>⌄</span>`;
  renderTickets(next === 'All' ? state.tickets : state.tickets.filter(ticket => ticket.status === next));
});

function openModal() { $('#ticketModal').classList.remove('hidden'); $('#ticketModal').setAttribute('aria-hidden', 'false'); }
function closeModal() { $('#ticketModal').classList.add('hidden'); $('#ticketModal').setAttribute('aria-hidden', 'true'); }

async function openTicket(ticketId) {
  openModal();
  $('#ticketDetail').innerHTML = '<div class="loading">Loading ticket details…</div>';
  try {
    const [ticket, events] = await Promise.all([getJson(`/api/tickets/${ticketId}`), getJson(`/api/tickets/${ticketId}/events`)]);
    $('#modalTitle').textContent = `${ticket.ticket_number} · ${ticket.title}`;
    const timeline = events.length ? events.map(event => `<div class="timeline-item"><span class="timeline-dot ${event.event_type}"></span><div><strong>${escapeHtml(event.message)}</strong><small>${escapeHtml(event.actor)} · ${relativeTime(event.created_at)}</small></div></div>`).join('') : '<p class="empty-note">No activity recorded yet.</p>';
    $('#ticketDetail').innerHTML = `
      <div class="detail-summary"><div><span class="status-pill ${statusClass(ticket.status)}">${escapeHtml(ticket.status)}</span><span class="priority ${priorityClass(ticket.priority)}">${escapeHtml(ticket.priority)} priority</span></div><span class="detail-team">${escapeHtml(ticket.assignee || 'Service Desk')}</span></div>${ticket.requires_approval ? '<span class="status-pill needs-review">Approval required</span>' : ''}</div>
      <div class="integration-card"><div><span class="integration-icon">J</span><div><strong>${ticket.external_id ? `Linked Jira issue ${escapeHtml(ticket.external_id)}` : 'Jira Service Management'}</strong><small>${ticket.external_id ? 'Last sync ' + (ticket.last_synced_at ? relativeTime(ticket.last_synced_at) : 'pending') : 'Not linked yet'}</small></div></div><div class="integration-actions">${ticket.external_url ? `<a href="${escapeHtml(ticket.external_url)}" target="_blank" rel="noreferrer" class="jira-link">Open ↗</a>` : ''}<button class="modal-action" data-sync-jira="true">${ticket.external_id ? 'Sync' : 'Create Jira issue'}</button></div></div>
      <p class="detail-description">${escapeHtml(ticket.description)}</p>
      <div class="detail-metrics"><div><span>Category</span><strong>${escapeHtml(ticket.category)}</strong></div><div><span>SLA due</span><strong>${ticket.sla_due_at ? new Date(ticket.sla_due_at).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : 'Not set'}</strong></div><div><span>Source</span><strong>${escapeHtml(ticket.source)}</strong></div>${ticket.resolution_code ? `<div><span>Resolution</span><strong>${escapeHtml(ticket.resolution_code)}</strong></div>` : ''}</div>
      <div class="modal-section"><h4>ACTIVITY TIMELINE</h4><div class="timeline">${timeline}</div></div>
      <div class="modal-section"><h4>UPDATE TICKET</h4><div class="status-actions">${ticket.requires_approval ? '<button class="modal-action approve" data-approve-ticket="true">Approve safety review</button>' : ''}${!['Resolved', 'Closed'].includes(ticket.status) ? '<button class="modal-action" data-ticket-status="In progress">Mark in progress</button><button class="modal-action" data-ticket-status="Pending">Pending</button><button class="modal-action" data-ticket-status="Resolved">Resolve</button>' : ''}${ticket.status === 'Resolved' ? '<button class="modal-action" data-ticket-status="Closed">Close ticket</button><button class="modal-action" data-ticket-status="Reopened">Reopen</button>' : ''}${ticket.status === 'Closed' ? '<button class="modal-action" data-ticket-status="Reopened">Reopen</button>' : ''}${ticket.status !== 'Escalated' && !ticket.requires_approval && !['Resolved', 'Closed'].includes(ticket.status) ? '<button class="modal-action danger" data-escalate-ticket="true">Escalate</button>' : ''}</div><textarea id="ticketNote" class="note-input" rows="2" placeholder="Add an internal note…"></textarea><button class="button primary note-submit" data-add-note="true">Add note <span class="arrow">→</span></button><div class="attachment-row"><input id="ticketAttachment" type="file" accept=".pdf,.txt,.csv,.json,.png,.jpg,.jpeg,.webp" /><button class="modal-action" data-upload-attachment="true">Attach file</button></div></div>`;
    document.querySelectorAll('[data-ticket-status]').forEach(button => button.addEventListener('click', () => updateTicketStatus(ticket.id, button.dataset.ticketStatus)));
    $('[data-escalate-ticket]')?.addEventListener('click', () => escalateTicket(ticket.id));
    $('[data-approve-ticket]')?.addEventListener('click', () => approveTicket(ticket.id));
    $('[data-sync-jira]')?.addEventListener('click', () => syncJiraTicket(ticket.id));
    $('[data-add-note]')?.addEventListener('click', () => addTicketNote(ticket.id));
    $('[data-upload-attachment]')?.addEventListener('click', () => uploadTicketAttachment(ticket.id));
  } catch (error) { $('#ticketDetail').innerHTML = `<div class="loading">${escapeHtml(error.message)}</div>`; }
}

async function updateTicketStatus(ticketId, status) {
  try { await getJson(`/api/tickets/${ticketId}/status?status=${encodeURIComponent(status)}`, { method: 'PATCH' }); showToast(`Ticket marked ${status.toLowerCase()}`); closeModal(); await loadDashboard(); } catch (error) { showToast(error.message); }
}

async function escalateTicket(ticketId) {
  const reason = window.prompt('Why should this ticket be escalated?', 'User impact requires immediate attention');
  if (reason === null) return;
  try { await getJson(`/api/tickets/${ticketId}/escalate`, { method: 'POST', body: JSON.stringify({ reason }) }); showToast('Ticket escalated with a 2-hour SLA'); closeModal(); await loadDashboard(); } catch (error) { showToast(error.message); }
}

async function approveTicket(ticketId) {
  try {
    await getJson(`/api/tickets/${ticketId}/approve`, { method: 'POST' });
    showToast('Safety review approved');
    await openTicket(ticketId);
    await loadDashboard();
  } catch (error) { showToast(error.message); }
}

async function syncJiraTicket(ticketId) {
  try {
    await getJson(`/api/tickets/${ticketId}/sync`, { method: 'POST' });
    showToast('Ticket synced to Jira');
    await openTicket(ticketId);
    await loadDashboard();
  } catch (error) { showToast(error.message); }
}

async function uploadTicketAttachment(ticketId) {
  const file = $('#ticketAttachment')?.files?.[0];
  if (!file) { showToast('Choose a file first.'); return; }
  const form = new FormData();
  form.append('file', file);
  try { await getJson(`/api/tickets/${ticketId}/attachments`, { method: 'POST', body: form }); showToast('Attachment uploaded'); await openTicket(ticketId); } catch (error) { showToast(error.message); }
}

async function addTicketNote(ticketId) {
  const input = $('#ticketNote');
  const message = input?.value.trim();
  if (!message) { showToast('Write a note first.'); return; }
  try { await getJson(`/api/tickets/${ticketId}/events`, { method: 'POST', body: JSON.stringify({ message, actor: 'Alex Morgan' }) }); showToast('Internal note added'); await openTicket(ticketId); } catch (error) { showToast(error.message); }
}

document.addEventListener('click', (event) => {
  if (event.target.dataset.closeModal === 'true' || event.target.id === 'closeModal') closeModal();
  const row = event.target.closest('.ticket-row');
  if (row) openTicket(row.dataset.ticketId);
  const feedback = event.target.closest('[data-rating]');
  if (feedback) {
    getJson('/api/feedback', { method: 'POST', body: JSON.stringify({ run_id: feedback.dataset.runId, ticket_number: feedback.dataset.ticketNumber || null, rating: feedback.dataset.rating }) }).then(() => { feedback.parentElement.querySelectorAll('[data-rating]').forEach(button => button.disabled = true); showToast('Thanks for the feedback'); }).catch(error => showToast(error.message));
  }
});

document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeModal(); });

authenticate();
