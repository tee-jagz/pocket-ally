let state = null, csrf = '', rendering = false, refreshQueued = false;
let clientError = '', pendingApproval = null, noteRequest = 0;
const $ = s => document.querySelector(s);
const esc = x => String(x ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const date = x => new Date(x).toLocaleDateString('en-GB', {day:'numeric', month:'long', timeZone:'Europe/London'});
const clock = x => new Date(x).toLocaleTimeString('en-GB', {hour:'2-digit', minute:'2-digit', timeZone:'Europe/London'});
const mascotLabels = {idle:'Ready when you are', reading:'Finding the little details', planning:'Making a little room', filling:'One less form to carry', waiting:'Your say, before send', sending:'Saving your approved draft', done:'A little less to carry', stuck:'Paused. Let’s check this.'};
function mascot(value) {
  $('#mascot').className = 'mascot ' + value;
  $('#mascot-label').textContent = value === 'sending' && state?.mode === 'live integrations' ? 'Sending your approved draft' : mascotLabels[value] || value;
}
async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-Demo-CSRF':csrf}, body:JSON.stringify(body)});
  if (!r.ok) {
    const e = await r.json().catch(() => ({detail:'Connection failed. Check the local demo server.'}));
    throw Error(typeof e.detail === 'string' ? e.detail : 'Request failed. Reload the page and review again.');
  }
  return r.json();
}
function error(message) {
  clientError = message;
  $('#error').hidden = false;
  $('#error').textContent = message;
  mascot('stuck');
}
async function refresh() {
  if (rendering) { refreshQueued = true; return; }
  rendering = true;
  try { state = await api('/api/status'); csrf = state.csrf; render(); }
  catch (e) { error(e.message); }
  finally {
    rendering = false;
    if (refreshQueued) { refreshQueued = false; refresh(); }
  }
}
function render() {
  const s = state, offline = s.mode.includes('offline');
  const failure = s.error || clientError;
  mascot(failure ? 'stuck' : pendingApproval ? 'sending' : s.mascot);
  $('#mode').textContent = s.mode;
  $('#launch').hidden = ['awaiting-approval','complete'].includes(s.phase);
  $('#start').disabled = s.phase === 'running';
  $('#start').innerHTML = s.phase === 'error' ? 'Retry preparation <span>↗</span>' : 'Prepare my paperwork <span>↗</span>';
  $('#progress').hidden = s.phase !== 'running';
  $('#error').hidden = !failure;
  $('#error').textContent = failure || '';
  $('#workspace').hidden = !s.attendance;
  if (s.attendance) {
    const a = s.attendance;
    $('#appointment').innerHTML = `<p class="appointment-date">${esc(date(a.next_appointment.value))}</p><p class="appointment-time">${esc(clock(a.next_appointment.value))} · personal appointment</p><p class="location">${esc(a.hospital.value)}<br>${esc(a.department.value)}</p>`;
    $('#provenance').innerHTML = Object.entries(a).map(([k,v]) => `<div class="source-field"><strong>${esc(k.replaceAll('_',' '))} · email line ${esc(v.line)}</strong><blockquote>${esc(v.quote)}</blockquote></div>`).join('');
  }
  if (s.calendar) $('#calendar').innerHTML = `<div class="travel">◷ Includes ${esc(s.calendar.travel_minutes)} minutes for travel · planning estimate</div><p class="muted">${esc(s.calendar.mode)}</p>${s.calendar.url ? `<a class="small-link" href="${esc(s.calendar.url)}">Download calendar event ↗</a>` : ''}`;
  if (s.claim) {
    const c = s.claim;
    $('#claim').innerHTML = `<p class="amount">${esc(c.estimate.split(' estimate')[0])} <span class="estimate-label">ESTIMATE</span></p><p class="estimate-label">Synthetic receipt amount · subject to verification</p><p class="deadline">Claim deadline: <strong>${esc(new Date(c.deadline).toLocaleDateString('en-GB', {day:'numeric', month:'long', year:'numeric', timeZone:'Europe/London'}))}</strong><br><span class="muted">${esc(c.deadline_basis)}</span></p><ul class="checklist">${c.checklist.map(x => `<li><span class="check">${x.present ? '✓' : '!'}</span>${esc(x.label)} · synthetic</li>`).join('')}</ul><a class="small-link" href="${esc(c.url)}" target="_blank" rel="noopener">Review HC5(T) PDF draft ↗</a><p class="bank-notice">${esc(c.bank_notice)}</p><p class="pending">Still needs review: ${c.pending_fields.map(esc).join(', ')}. TfL fare: ${esc(c.fare_estimate)}</p>`;
  }
  $('#drafts').innerHTML = s.drafts.map(d => `<article class="card draft" aria-label="${d.kind === 'claim' ? 'Travel claim email review' : 'Manager email review'}"><div class="card-heading"><span class="icon" aria-hidden="true">${d.kind === 'claim' ? '▤' : '✉'}</span><span class="tag">${d.kind === 'claim' ? 'CLAIM TEST INBOX' : 'MANAGER TEST INBOX'}</span></div><h2>${d.kind === 'claim' ? 'Your travel claim pack' : 'A note to Sam'}</h2><p class="to">To: ${esc(d.recipient)}</p><h3>${esc(d.subject)}</h3><div class="email-body">${esc(d.body)}</div>${d.source_note ? `<button class="text-button source-note" data-note="${esc(d.source_note)}">From your diary · review source ↗</button>` : ''}<div class="attachments">${d.attachments.map((a,i) => `<a class="attachment" href="/api/drafts/${encodeURIComponent(d.id)}/attachments/${i}" target="_blank" rel="noopener" aria-label="Review attachment ${esc(a.split('/').pop())}">▤ ${esc(a.split('/').pop())} ↗</a>`).join('') || '<span class="muted">No attachments</span>'}</div>${d.result ? `<div class="sent-note">✓ Approved by you · ${esc(d.result.delivery)}${d.result.download ? `<br><a href="${esc(d.result.download)}">Open saved email ↗</a>` : ''}</div>` : d.sending ? '<div class="pending" role="status">Delivery uncertain or in progress. Check the test inbox before retrying.</div>' : `<button class="approve" data-id="${esc(d.id)}" data-digest="${esc(d.digest)}" ${!['awaiting-approval','complete'].includes(s.phase) || pendingApproval ? 'disabled' : ''}>${pendingApproval === d.id ? 'Recording your approval…' : 'Approve & ' + (offline ? 'save to local outbox' : 'send to test inbox') + ' ↗'}</button><p class="approval-copy">Approves exactly this recipient, subject, text and attached files.${offline ? ' No email leaves this computer.' : ''}</p>`}</article>`).join('');
  const answer = s.answer;
  if (answer) $('#answer').innerHTML = `<p class="answer">${answer.sentences.map(x => `${esc(x.text)}<button class="citation source-note" data-note="${esc(x.note_id)}" aria-label="Open diary source from ${esc(x.date)}">[${esc(date(x.date))}]</button>`).join(' ')}</p><p class="muted">${esc(answer.method)}</p>`;
  $('#diary-mode').textContent = s.diary?.mode || 'Preparing diary…';
  $('#events').innerHTML = s.events.filter(x => x.kind !== 'tool-start').map(x => `<li><time>${esc(clock(x.time))}</time><strong>${esc(x.tool)}</strong><span>${esc(x.detail || x.kind)}</span></li>`).join('');
  document.querySelectorAll('.approve').forEach(b => b.onclick = async () => {
    if (pendingApproval) return;
    pendingApproval = b.dataset.id;
    clientError = '';
    render();
    try { await api('/api/drafts/' + encodeURIComponent(pendingApproval) + '/approve-send', {digest:b.dataset.digest}); }
    catch (e) { error(e.message); }
    finally { pendingApproval = null; await refresh(); }
  });
  document.querySelectorAll('.attachment').forEach(a => a.onclick = e => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    $('#attachment-title').textContent = a.textContent.replace(/[▤↗]/g, '').trim();
    $('#attachment-preview').src = a.href;
    $('#attachment-download').href = a.href;
    $('#attachment-dialog').showModal();
  });
  document.querySelectorAll('.source-note').forEach(b => b.onclick = () => openNote(b.dataset.note));
}
async function openNote(id) {
  const request = ++noteRequest;
  try {
    const n = await api('/api/notes/' + encodeURIComponent(id));
    if (request !== noteRequest) return;
    $('#note-date').textContent = date(n.timestamp);
    $('#note-transcript').textContent = n.transcript;
    $('#note-audio').pause();
    $('#audio-status').hidden = true;
    $('#note-audio').src = n.audio_url;
    if (!$('#note-dialog').open) $('#note-dialog').showModal();
  } catch (e) { error(e.message); }
}
$('#attachment-close').onclick = () => $('#attachment-dialog').close();
$('#attachment-dialog').addEventListener('close', () => $('#attachment-preview').removeAttribute('src'));
$('#note-audio').addEventListener('error', () => {
  $('#audio-status').hidden = false;
  $('#audio-status').textContent = 'Recording unavailable. You can still review the complete dated transcript above.';
});
$('.dialog-close').onclick = () => $('#note-dialog').close();
$('#note-dialog').addEventListener('close', () => $('#note-audio').pause());
$('#show-notes').onclick = () => openNote('note-1');
$('#start').onclick = async () => {
  clientError = '';
  $('#start').disabled = true;
  try { await api('/api/start', {}); await refresh(); }
  catch (e) { error(e.message); $('#start').disabled = false; }
};
refresh();
const events = new EventSource('/api/events');
events.onmessage = e => {
  try {
    const x = JSON.parse(e.data);
    if (!clientError && !state?.error) mascot(x.state);
    $('#progress-label').textContent = x.tool;
    refresh();
  } catch { error('An update could not be read. Reload to check the saved state.'); }
};
document.querySelectorAll('[data-source]').forEach(b => b.onclick = () => openNote(b.dataset.source));
