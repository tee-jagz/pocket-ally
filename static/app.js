'use strict';
let state = null, journal = [], companion = null, csrf = '', rendering = false, refreshQueued = false;
let clientError = '', pendingApproval = null, activeView = 'home', activeNote = null;
const checkinEdits = new Map(), checkinSaved = new Set();
let checkinSaving = null;
let authLocked = false, eventStream = null, accessPending = null, accessTokenInFlight = '', accessAttempt = 0;
const refreshWaiters = [];
let chosenStyle = 'soft', companionPreview = null, companionInitialised = false;
let recorder = null, micStream = null, recordChunks = [], recordedBlob = null, recordedURL = '', recordStarted = 0, recordTimer = null, recordLimit = null;
const MAX_AUDIO_BYTES = 10 * 1024 * 1024, MAX_RECORD_SECONDS = 120;
const $ = selector => document.querySelector(selector);
const clean = value => String(value ?? '').replaceAll(String.fromCharCode(8212), ' - ');
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icon = name => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const date = (value, year = false) => new Date(value).toLocaleDateString('en-GB', {day:'numeric',month:'long',...(year ? {year:'numeric'} : {}),timeZone:'Europe/London'});
const clock = value => new Date(value).toLocaleTimeString('en-GB', {hour:'2-digit',minute:'2-digit',timeZone:'Europe/London'});
const isLocal = value => value?.delivery_mode ? value.delivery_mode === 'local-outbox' : value?.mode !== 'live integrations';
const selectedCompanion = () => companion?.saved || companion?.selected || companion?.selection || {};
const visualFilter = value => value?.mode === 'local-personalised-preview' && Number.isFinite(value?.descriptor?.hue) ? `hue-rotate(${(value.descriptor.hue % 37) - 18}deg)` : 'none';
const styleImage = style => `/assets/companion-${['soft','playful','minimal'].includes(style) ? style : 'soft'}.png`;
const imageURL = value => typeof value === 'string' && /^\/(assets|api)\//.test(value) ? value : styleImage('soft');
const companionImage = () => imageURL(selectedCompanion().image_url || styleImage(selectedCompanion().style));
const noteList = result => Array.isArray(result) ? result : result?.entries || result?.notes || [];
const noteText = note => note?.transcript || note?.text || '';
const noteTitle = note => note?.title || noteText(note).split(/[.!?]/)[0].slice(0,65) || 'Voice note';
const noteTime = note => note?.timestamp || note?.created_at || new Date().toISOString();

async function api(path, body, method, extraHeaders = {}) {
  const requestAccessAttempt = accessAttempt;
  const binary = typeof Blob !== 'undefined' && body instanceof Blob;
  const form = typeof FormData !== 'undefined' && body instanceof FormData;
  const options = {credentials:'same-origin'};
  if (body !== undefined) {
    options.method = method || 'POST';
    options.headers = {'X-Demo-CSRF':csrf,...extraHeaders};
    if (!form && !binary) options.headers['Content-Type'] = 'application/json';
    options.body = form || binary ? body : JSON.stringify(body);
  }
  const response = await fetch(path,options);
  if (body === undefined && requestAccessAttempt !== accessAttempt) { const stale = new Error('Access changed while this request was in flight.'); stale.staleAuth = true; throw stale; }
  if (!response.ok) {
    const result = await response.json().catch(() => ({detail:'Connection unavailable. Please try again when you’re online.'}));
    const message = response.status === 401 ? (path === '/api/session' ? 'That link or access code did not work. Please check it and try again.' : 'Open your private access link to continue securely.') : typeof result.detail === 'string' ? result.detail : 'This could not be saved. Please review and try again.';
    if (response.status === 401 && path !== '/api/session') lockAccess();
    const error = new Error(clean(message)); error.status = response.status; throw error;
  }
  return response.status === 204 ? {} : response.json();
}
function showError(message) {
  clientError = clean(message);
  $('#error').textContent = clientError;
  $('#error').hidden = false;
  const modal = document.querySelector('dialog[open]');
  if (modal) { let notice = modal.querySelector('.dialog-error'); if (!notice) { notice = document.createElement('p'); notice.className = 'error dialog-error'; notice.setAttribute('role','alert'); modal.prepend(notice); } notice.textContent = clientError; }
  document.querySelectorAll('.guide').forEach(element => element.classList.add('is-stuck'));
  document.querySelectorAll('.home-summary').forEach(element => element.classList.add('is-stuck'));
}
function clearNoteNotice() { if ($('#connection').dataset.kind === 'note') { $('#connection').hidden = true; $('#connection').textContent = ''; delete $('#connection').dataset.kind; } }
function clearError() { clientError = ''; $('#error').hidden = true; document.querySelectorAll('.dialog-error').forEach(element => element.remove()); }
function guide(text, stuck = false) {
  return `<div class="guide ${stuck ? 'is-stuck' : ''}"><img src="${esc(companionImage())}" alt="Your companion" style="filter:${visualFilter(selectedCompanion())}"><p class="guide-bubble">${esc(text)}</p></div>`;
}
function currentGuide() {
  const activeCase = state?.current_case;
  if (activeCase && !clientError && !state?.error) return activeCase.status === 'running' ? 'Reading the event and choosing the next safe action.' : activeCase.error ? 'This case paused safely. You can review the record and retry.' : activeCase.missing_evidence?.length ? 'The case is waiting for a missing detail. Check what is needed below.' : 'The case record shows what happened and why. You choose any external sharing.';
  if (clientError || state?.error) return 'Paused safely. Check the message above before continuing.';
  if (pendingApproval) return isLocal(state) ? 'Saving the exact draft you approved.' : 'Sending the exact draft you approved.';
  if (state?.phase === 'running') return 'Getting the details together. Nothing is being sent.';
  if (state?.phase === 'awaiting-approval') return 'Your drafts are ready. Your approval comes first.';
  if (state?.phase === 'complete') return 'Your approved paperwork is taken care of.';
  return 'One step at a time. You decide what happens next.';
}
function navigate(view, focus = false) {
  clearNoteNotice();
  stopJournalAudio(); $('#note-audio').pause();
  if (!['home','tasks','journal','companion','demo'].includes(view)) view = 'home';
  if (recorder?.state === 'recording' && view !== 'journal') stopRecording();
  if (view !== 'tasks') stopCaseReplay();
  activeView = view;
  document.querySelectorAll('.screen').forEach(screen => screen.hidden = screen.id !== 'screen-' + view);
  document.querySelectorAll('.bottom-nav [data-view]').forEach(button => {
    if (button.dataset.view === view) button.setAttribute('aria-current','page'); else button.removeAttribute('aria-current');
  });
  history.replaceState(null,'',location.pathname + location.search + '#' + view);
  window.scrollTo({top:0,behavior:'instant'});
  if (focus) $('#screen-' + view + ' h1').focus({preventScroll:true});
}
async function refresh() {
  if (rendering) { refreshQueued = true; return new Promise(resolve => refreshWaiters.push(resolve)); }
  rendering = true;
  try {
    state = await api('/api/status');
    csrf = state.csrf;
    unlockAccess();
    const results = await Promise.allSettled([api('/api/journal'),api('/api/companion'),api('/api/scenarios')]);
    if (results[0].status === 'fulfilled') journal = noteList(results[0].value);
    if (results[1].status === 'fulfilled') companion = results[1].value;
    if (results[2].status === 'fulfilled' && Array.isArray(results[2].value.scenarios)) scenarios = results[2].value.scenarios;
    render();
  } catch (error) { if (error.staleAuth) { /* A new access exchange owns recovery. */ } else if (error.status === 401) lockAccess(); else showError(error.message); }
  finally {
    rendering = false;
    if (refreshQueued) { refreshQueued = false; await refresh(); }
    refreshWaiters.splice(0).forEach(resolve => resolve());
  }
}
function render() {
  if (!state) return;
  const failure = state.error || clientError;
  $('#error').hidden = !failure;
  $('#error').textContent = clean(failure || '');
  renderHome(); renderTasks(); renderDemo(); renderJournal(); renderCompanion();
  document.querySelectorAll('img').forEach(img => img.onerror = () => { if (!img.src.endsWith('/companion-soft.png')) img.src = styleImage('soft'); });
}
function renderHome() {
  const hour = Number(new Intl.DateTimeFormat('en-GB',{hour:'numeric',hour12:false,timeZone:'Europe/London'}).format(new Date()));
  $('#home-title').textContent = `${hour < 12 ? 'Morning' : hour < 18 ? 'Afternoon' : 'Evening'}, Ade.`;
  if (caseUIAvailable()) { renderCaseHome(); return; }
  const drafts = state.drafts || [], pending = drafts.filter(draft => !draft.result);
  const priority = ['awaiting-approval','complete'].includes(state.phase) ? pending.find(draft => draft.kind === 'claim') || pending[0] : null;
  const complete = state.phase === 'complete';
  let summaryTitle = complete ? 'A little less to carry.' : state.phase === 'running' ? 'Your next steps are coming together.' : priority ? 'Your paperwork is organised.' : 'A little room for your day.';
  let summary = complete ? 'Your approved drafts are saved. Your next appointment is here when you need it.' : priority ? 'Travel is planned. Your drafts need a review.' : state.phase === 'running' ? 'We’re checking the details. Nothing has been sent.' : 'One appointment email is ready. Let’s take it one step at a time.';
  if (state.error || clientError) { summaryTitle = 'Let’s pause and check.'; summary = 'Your approval stays in your hands. Nothing is retried automatically.'; }
  let decision = '';
  if (priority) decision = `<div class="decision-card"><span class="decision-label">! ${pending.length} ${pending.length === 1 ? 'decision' : 'decisions'} waiting</span><h2>${priority.kind === 'claim' ? 'Your travel claim is ready' : 'Your manager note is ready'}</h2><p>Check the details before anything is ${isLocal(state) ? 'saved to the local outbox' : 'sent'}.</p><button class="primary" data-review="${esc(priority.id)}">${priority.kind === 'claim' ? 'Review claim' : 'Review manager note'} ${icon('arrow')}</button></div>`;
  else if (!complete) decision = `<div class="decision-card"><span class="decision-label">${state.phase === 'running' ? 'Getting ready' : 'One next step'}</span><h2>${state.phase === 'running' ? 'Preparing your paperwork' : 'Start with your appointment email'}</h2><p>${state.phase === 'running' ? 'You can check progress in Tasks. Nothing has been sent.' : 'We can prepare the claim and a private manager draft for your review.'}</p><button class="primary" data-view="tasks">${state.phase === 'running' ? 'See progress' : 'Get things ready'} ${icon('arrow')}</button></div>`;
  const a = state.attendance?.next_appointment?.value;
  const upcoming = a ? `<button class="row-card" data-view="tasks"><span class="date-tile">${esc(new Date(a).toLocaleDateString('en-GB',{weekday:'short',timeZone:'Europe/London'}))}<b>${esc(new Date(a).toLocaleDateString('en-GB',{day:'2-digit',timeZone:'Europe/London'}))}</b></span><span><strong>Personal appointment</strong><span class="muted">${esc(date(a))} · ${esc(clock(a))}</span><span class="muted">${state.calendar?.url ? 'Calendar download ready' : state.calendar ? 'Calendar event created' : 'Travel details being prepared'}</span></span>${icon('arrow')}</button>` : '<p class="empty-state">Your next appointment will appear here after the email is checked.</p>';
  const completions = [];
  if (state.calendar) completions.push(state.calendar.url ? 'Appointment calendar file ready' : 'Appointment added to calendar');
  drafts.filter(draft => draft.result).forEach(draft => completions.push((draft.kind === 'claim' ? 'Claim email' : 'Manager email') + (draft.result.delivery === 'local outbox only' ? ' saved locally' : ' sent to test inbox')));
  const latest = [...journal].sort((a,b) => noteTime(b).localeCompare(noteTime(a)))[0];
  $('#home-content').innerHTML = `<section class="home-summary ${state.error || clientError ? 'is-stuck' : ''}"><div class="summary-copy"><h2>${esc(summaryTitle)}</h2><p>${esc(summary)}</p></div><img src="${esc(companionImage())}" alt="Your companion" style="filter:${visualFilter(selectedCompanion())}"></section>${decision}<div class="section-heading"><h2>Upcoming appointment</h2><button class="text-button" data-view="tasks">See details</button></div>${upcoming}<div class="section-heading"><h2>Already taken care of</h2></div>${completions.length ? `<ul class="completion-list">${completions.map(text => `<li><span class="tick">${icon('check')}</span>${esc(text)}</li>`).join('')}</ul>` : '<p class="muted">No completed tasks yet. We’ll keep the record here.</p>'}<button class="row-card" data-write-note>${icon('write')}<span><strong>Make a note of today</strong>${latest ? `<span class="muted">Last note: ${esc(noteTitle(latest))}</span>` : '<span class="muted">Keep your words close</span>'}</span>${icon('arrow')}</button><p class="safety-note">Adults’ synthetic demo only. Refund and eligibility are not confirmed.</p>`;
}
function linkedNotes(kind) {
  const notes = journal.filter(note => (note.linked_tasks || []).includes(kind));
  return notes.length ? `<div class="linked-notes"><p class="muted">Linked notes for your review</p>${notes.map(note => `<button class="text-button" data-journal-note="${esc(note.id)}">${esc(noteTitle(note))} ↗</button>`).join('')}<p class="muted">For reference only. Not attached to this email.</p></div>` : '';
}
function canApproveDraft(draft) {
  if (draft.kind === 'checkin_reply' && (checkinEdits.has(draft.id) || checkinSaving)) return false;
  if (draft.obsolete) return false;
  if (draft.case_id) { const item = (state.cases || []).find(candidate => candidate.id === draft.case_id) || (state.current_case?.id === draft.case_id ? state.current_case : null); return !!item && ['ready','complete'].includes(item.status); }
  return ['awaiting-approval','complete'].includes(state.phase);
}
function draftName(draft) { return draft.kind==='claim'?'Claim email':draft.kind==='checkin_reply'?'Check-in reply':'Manager email'; }
function checkinEditor(draft) {
  if(draft.kind!=='checkin_reply'||draft.result||draft.sending||draft.obsolete)return '';
  const edit=checkinEdits.get(draft.id);
  if(!edit)return `<button type="button" class="secondary" data-edit-checkin="${esc(draft.id)}">Edit reply</button>${checkinSaved.has(draft.id)?'<p class="notice">Changes saved. Review this exact copy before approving.</p>':''}`;
  const busy=checkinSaving===draft.id;
  return `<section class="checkin-editor"><h3>Edit your reply</h3><label for="reply-subject-${esc(draft.id)}">Subject</label><input id="reply-subject-${esc(draft.id)}" data-checkin-field="subject" data-checkin-id="${esc(draft.id)}" maxlength="200" value="${esc(edit.subject)}" ${busy?'disabled':''}><label for="reply-body-${esc(draft.id)}">Reply body</label><textarea id="reply-body-${esc(draft.id)}" data-checkin-field="body" data-checkin-id="${esc(draft.id)}" rows="8" maxlength="10000" ${busy?'disabled':''}>${esc(edit.body)}</textarea><p class="notice">Save changes first, then review the saved exact copy before approving. Nothing is sent by saving.</p>${edit.error?`<p class="notice warning" role="alert">${esc(edit.error)}</p>`:''}<button type="button" class="primary" data-save-checkin="${esc(draft.id)}" ${busy?'disabled':''}>${busy?'Saving changes...':'Save changes'}</button><button type="button" class="text-button" data-cancel-checkin="${esc(draft.id)}" ${busy?'disabled':''}>Cancel edits</button><p class="muted">Saved exact copy below. Your unsaved changes are not approved.</p></section>`;
}
async function saveCheckinReply(id) {
  const edit=checkinEdits.get(id);if(!edit||checkinSaving)return;
  if(!edit.subject.trim()||!edit.body.trim()){edit.error='Add a subject and reply body before saving.';renderTasks();return;}
  checkinSaving=id;edit.error='';renderTasks();
  try{const result=await api('/api/drafts/'+encodeURIComponent(id),{subject:edit.subject,body:edit.body},'PATCH');if(result.draft?.id)checkinSaved.add(result.draft.id);await refresh();checkinEdits.delete(id);}
  catch(error){edit.error=error.message;}
  finally{checkinSaving=null;renderTasks();}
}
function renderDraftCard(draft) {
  const offline = isLocal(state),reply=draft.kind==='checkin_reply';
  return `<article id="draft-${esc(draft.id)}" class="card draft" aria-label="${draft.kind === 'claim' ? 'Travel claim email review' : reply?'Check-in reply review':'Manager email review'}"><div class="draft-title"><span class="doc-icon">${draft.kind === 'claim' ? 'PDF' : 'MAIL'}</span><div><h2>${draft.kind === 'claim' ? 'Your travel claim pack' : reply?'Your check-in reply':'A note to Sam'}</h2><p class="muted">${draft.kind === 'claim' ? 'Claim test inbox' : reply?'Check-in test inbox':'Manager test inbox'}</p></div></div><p class="to"><strong>To</strong> ${esc(draft.recipient)}</p>${checkinEditor(draft)}<h3>${esc(draft.subject)}</h3><div class="email-body">${esc(draft.body)}</div>${draft.source_note ? `<button class="text-button" data-source-note="${esc(draft.source_note)}">From your journal · check source ↗</button>` : ''}${linkedNotes(draft.kind)}<div class="attachments">${draft.attachments.map((file,index) => `<a class="attachment" href="/api/drafts/${encodeURIComponent(draft.id)}/attachments/${index}" data-attachment="${esc(file.split('/').pop())}" target="_blank" rel="noopener">${esc(file.split('/').pop())} ↗</a>`).join('') || '<span class="muted">No attachments</span>'}</div>${draft.result ? `<div class="sent-note">✓ Approved by you · ${esc(draft.result.delivery)}${draft.result.download ? `<br><a href="${esc(draft.result.download)}">Open saved email ↗</a>` : ''}</div>` : draft.sending ? '<p class="notice warning">Delivery uncertain or in progress. Inspect the test inbox before retrying.</p>' : `<p class="notice">ⓘ Nothing has been ${offline ? 'saved to the outbox' : 'sent'}.</p><button class="primary approve" data-id="${esc(draft.id)}" data-digest="${esc(draft.digest)}" ${!canApproveDraft(draft) || pendingApproval ? 'disabled' : ''}>${pendingApproval === draft.id ? 'Recording your approval...' : offline ? 'Approve & save to local outbox' : 'Approve & send to test inbox'}</button><p class="approval-copy">Approves exactly this recipient, subject, body and attached files.${offline ? ' Nothing is emailed. This saves a local demo copy.' : ''}</p>`}</article>`;
}
function renderTasks() {
  if (renderCaseTasks()) return;
  const s = state, offline = isLocal(s);
  $('#mode').textContent = offline ? 'Local demo' : 'Connected test inboxes';
  $('#task-guide').innerHTML = `<span class="status-chip ${s.error || clientError ? 'stuck' : ''}">${s.phase === 'awaiting-approval' ? 'Ready for your review' : s.phase === 'complete' ? 'Approved drafts complete' : s.phase === 'running' ? 'Preparing your drafts' : s.error ? 'Paused safely' : 'You’re in control'}</span>${guide(currentGuide(),!!(s.error || clientError))}`;
  if (s.phase === 'ready') $('#task-guide').innerHTML += '<button class="secondary" data-view="demo">Open Demo</button>';
  $('#progress').hidden = s.phase !== 'running';
  $('#workspace').hidden = !s.attendance;
  if (!s.attendance) return;
  $('#task-timeline').innerHTML = `<li><span class="timeline-dot">${icon('check')}</span>Appointment details checked</li><li><span class="timeline-dot ${s.claim ? '' : 'pending'}">${s.claim ? icon('check') : '·'}</span>Claim draft ${s.claim ? 'prepared' : 'being prepared'}</li><li><span class="timeline-dot ${(s.drafts || []).every(draft => draft.result) && s.drafts.length ? '' : 'pending'}">${s.phase === 'complete' ? icon('check') : '○'}</span><strong>${s.phase === 'complete' ? 'Your approvals recorded' : 'Your approval needed'}</strong></li>`;
  if (s.claim) {
    const c = s.claim;
    $('#task-summary').innerHTML = `<details class="card claim-detail"><summary>Travel claim details · ${esc(c.estimate.split(' estimate')[0])} estimate</summary><p class="amount">${esc(c.estimate)}</p><p>Claim deadline: <strong>${esc(date(c.deadline,true))}</strong></p><p class="muted">${esc(c.deadline_basis)}</p><ul class="checklist">${c.checklist.map(item => `<li><span>${item.present ? '✓' : '!'}</span>${esc(item.label)} · synthetic</li>`).join('')}</ul><p class="notice warning">Refund and eligibility are unconfirmed. Signature and bank fields stay blank.</p><p class="muted">Needs review: ${c.pending_fields.map(esc).join(', ')}. Fare estimate: ${esc(c.fare_estimate)}.</p></details>`;
  }
  $('#drafts').innerHTML = (s.drafts || []).map(renderDraftCard).join('');
  const a = s.attendance;
  $('#appointment').innerHTML = `<p class="appointment-date">${esc(date(a.next_appointment.value,true))}</p><p class="appointment-time">${esc(clock(a.next_appointment.value))} · personal appointment</p><p class="location">${esc(a.hospital.value)}<br>${esc(a.department.value)}</p>`;
  if (s.calendar) $('#calendar').innerHTML = `<p class="travel">Includes ${esc(s.calendar.travel_minutes)} minutes for travel · planning estimate</p><p class="muted">${esc(s.calendar.mode)}</p>${s.calendar.url ? `<a class="small-link" href="${esc(s.calendar.url)}">Download calendar event ↗</a>` : ''}`;
  $('#provenance').innerHTML = Object.entries(a).map(([key,value]) => `<div class="source-field"><strong>${esc(key.replaceAll('_',' '))} · email line ${esc(value.line)}</strong><blockquote>${esc(value.quote)}</blockquote></div>`).join('');
  $('#events').innerHTML = (s.events || []).filter(event => event.kind !== 'tool-start').map(event => `<li><time>${esc(clock(event.time))}</time><strong>${esc(event.tool)}</strong><span>${esc(event.detail || event.kind)}</span></li>`).join('');
}
function renderJournal() {
  $('#recall-provider-notice').hidden = state?.capabilities?.semantic_retrieval !== true;
  $('#journal-count').textContent = `${journal.length} ${journal.length === 1 ? 'entry' : 'entries'}`;
  $('#journal-entries').innerHTML = journal.length ? [...journal].sort((a,b) => noteTime(b).localeCompare(noteTime(a))).map(note => `<article class="entry-card"><button class="entry-open" data-journal-note="${esc(note.id)}"><span><time>${esc(date(noteTime(note)))} · ${esc(clock(noteTime(note)))}</time><h3>${esc(noteTitle(note))}</h3></span>${icon('arrow')}</button>${note.audio_url || note.audio_path || note.kind === 'audio' ? journalAudioControls(note) : `<p class="entry-excerpt">${esc(noteText(note).slice(0,130))}${noteText(note).length > 130 ? '...' : ''}</p>`}</article>`).join('') : '<div class="empty-state">A small place for your words. Record or write your first synthetic note.</div>';
  $('#journal-guide').innerHTML = guide(clientError || state?.error ? 'Paused safely. Check the message above before continuing.' : caseUIAvailable() ? 'Relevant dated notes are brought into your case automatically. You can always check the source.' : 'Keep the original words. Link a note to a task only when you choose.',!!(clientError || state?.error));
  $('#journal-context-policy').textContent = caseUIAvailable() ? 'Relevant journal and diary text can inform your case automatically. Nothing is attached to an email or shared without your review and exact approval.' : 'Your journal stays separate from tasks. A note is linked to a task only when you choose to link it.';
}
function renderCompanion() {
  const saved = selectedCompanion();
  if (!companionInitialised && companion) {
    chosenStyle = saved.style || 'soft';
    $('#companion-prompt').value = saved.prompt || $('#companion-prompt').value;
    companionInitialised = true;
  }
  const visual = companionPreview || saved;
  const style = visual.style || chosenStyle;
  $('#companion-stage').className = 'companion-stage ' + style;
  const descriptor = visual.descriptor;
  $('#companion-stage').style.background = descriptor && visual.mode === 'local-personalised-preview' ? `radial-gradient(ellipse,hsl(${Number(descriptor.accent_hue) % 360} 20% 90%),#f0f2e8 65%,transparent 66%)` : '';
  $('#companion-stage').style.borderRadius = descriptor?.shape === 'squircle' ? '28%' : descriptor?.shape === 'oval' ? '44% 44% 48% 48%' : '50%';
  $('#companion-stage').innerHTML = `<img src="${esc(imageURL(visual.image_url || styleImage(style)))}" alt="${esc(style)} companion preview" style="filter:${visualFilter(visual)}">`;
  document.querySelectorAll('[data-style]').forEach(button => { const selected = button.dataset.style === chosenStyle; button.classList.toggle('selected',selected); button.setAttribute('aria-pressed',String(selected)); });
  $('#prompt-count').textContent = $('#companion-prompt').value.length + '/200';
  $('#companion-method').textContent = visual.mode === 'openai-generated' ? (companionPreview ? 'Generated preview' : 'Generated companion') : (visual.id ? 'Personalised preview using packaged artwork' : 'Choose a style to preview');
  $('#companion-saved').hidden = !saved.id || !!companionPreview;
  if (saved.id && !companionPreview) $('#companion-saved').textContent = saved.mode === 'openai-generated' ? 'Your generated companion is saved.' : 'Your companion is saved.';
}
async function approve(id,digest) {
  if (pendingApproval || checkinEdits.has(id) || (checkinSaving && (state?.drafts||[]).some(draft=>draft.id===id&&draft.kind==='checkin_reply'))) return;
  clearError(); pendingApproval = id; renderTasks();
  try { await api('/api/drafts/' + encodeURIComponent(id) + '/approve-send',{digest}); }
  catch (error) { showError(error.message); }
  finally { pendingApproval = null; await refresh(); }
}
function openWrite() { stopJournalAudio(); $('#note-audio').pause(); $('#write-dialog').showModal(); $('#note-title').focus(); }
async function openNote(id, source = false) {
  stopJournalAudio(); $('#note-audio').pause();
  try {
    let note = journal.find(item => item.id === id);
    if (!note || source) {
      try { note = await api('/api/notes/' + encodeURIComponent(id)); }
      catch (error) { if (!note) throw error; }
    }
    activeNote = note;
    $('#note-date').textContent = date(noteTime(note),true) + ' · ' + clock(noteTime(note));
    $('#note-heading').textContent = noteTitle(note);
    $('#note-transcript').textContent = noteText(note) || 'Audio saved. Add a transcript below to make this note available for recall.';
    $('#note-audio').pause(); $('#note-audio').removeAttribute('src');
    const audioURL = note.audio_url || (note.audio_path ? '/api/notes/' + encodeURIComponent(note.id) + '/audio' : '');
    $('#note-audio').hidden = !audioURL;
    if (audioURL) $('#note-audio').src = audioURL;
    $('#audio-status').hidden = true;
    const editable = !source && note.source !== 'fixture' && !String(note.id).startsWith('note-') && !note.read_only;
    $('#note-editor').hidden = !editable;
    $('#note-linker').hidden = !editable;
    $('#note-edit-text').value = noteText(note);
    $('#link-task').value = '';
    $('#note-linked').textContent = (note.linked_tasks || []).length ? 'Linked to: ' + note.linked_tasks.join(', ') : 'Not linked to a task.';
    $('#note-source-label').textContent = source || String(note.id).startsWith('note-') ? 'Synthetic source fixture. Not a real patient’s voice.' : note.transcript_pending ? 'Audio saved. Add a transcript to use this note in recall.' : note.transcription_mode === 'gpt-4o-transcribe' ? ((note.transcription_language === 'en' ? 'English transcription. ' : 'Transcribed from your recording. ') + 'Please check and edit the words below.') : 'Your saved words. Review before using them in paperwork.';
    if (!$('#note-dialog').open) $('#note-dialog').showModal();
  } catch (error) { showError(error.message); }
}
function stopMicTracks() { micStream?.getTracks().forEach(track => track.stop()); micStream = null; clearInterval(recordTimer); clearTimeout(recordLimit); }
function resetRecording() {
  stopMicTracks();
  if (recordedURL) URL.revokeObjectURL(recordedURL);
  recordedURL = ''; recordedBlob = null; recordChunks = [];
  $('#record-preview').hidden = true; $('#record-save').hidden = true; $('#record-live').hidden = true;
}
async function startRecording() {
  stopJournalAudio(); $('#note-audio').pause();
  if (recorder?.state === 'recording') return;
  $('#record-note').disabled = true;
  clearError(); navigate('journal'); $('#record-panel').hidden = false;
  resetRecording(); $('#record-help').textContent = 'Requesting microphone access. You can write a note instead.';
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    $('#record-help').textContent = 'Recording is unavailable in this browser or connection. You can write a note instead.'; $('#record-note').disabled = false; return;
  }
  try {
    const supported = ['audio/webm;codecs=opus','audio/mp4','audio/webm','audio/ogg;codecs=opus'].find(type => MediaRecorder.isTypeSupported(type));
    if (!supported) throw new Error('This browser has no supported recording format. Please write a note instead.');
    micStream = await navigator.mediaDevices.getUserMedia({audio:true});
    if (activeView !== 'journal' || $('#record-panel').hidden) { stopMicTracks(); $('#record-note').disabled = false; return; }
    recorder = new MediaRecorder(micStream,{mimeType:supported});
    const activeRecorder = recorder;
    recordStarted = Date.now(); recordChunks = [];
    recorder.ondataavailable = event => {
      if (event.data.size) recordChunks.push(event.data);
      if (recordChunks.reduce((total,chunk) => total + chunk.size,0) > MAX_AUDIO_BYTES) {
        $('#record-help').textContent = 'The 10 MB recording limit was reached. Use a shorter recording or write a note.';
        recorder._tooLarge = true; stopRecording();
      }
    };
    recorder.onerror = () => { stopMicTracks(); $('#record-note').disabled = false; $('#record-live').hidden = true; $('#record-help').textContent = 'Recording stopped unexpectedly. Please try again or write a note.'; };
    recorder.onstop = () => {
      const duration = Math.min(MAX_RECORD_SECONDS,(Date.now() - recordStarted) / 1000);
      const discard = activeRecorder._discard || activeRecorder._tooLarge;
      $('#record-note').disabled = false;
      stopMicTracks(); $('#record-live').hidden = true;
      if (discard) { recorder = null; return; }
      recordedBlob = new Blob(recordChunks,{type:supported}); recordedBlob.durationSeconds = duration;
      if (!recordedBlob.size || recordedBlob.size > MAX_AUDIO_BYTES) { $('#record-help').textContent = 'The recording could not be saved. Please try a shorter note or write instead.'; recorder = null; return; }
      recordedURL = URL.createObjectURL(recordedBlob); $('#record-preview').src = recordedURL; $('#record-preview').hidden = false; $('#record-save').hidden = false;
      $('#record-help').textContent = 'Microphone off. Listen before saving. Your note is not saved yet.';
      recorder = null;
    };
    recorder.start(1000); $('#record-live').hidden = false; $('#record-help').textContent = 'Recording now. Synthetic information only. Limit: 2 minutes or 10 MB.';
    const update = () => { const seconds = Math.min(MAX_RECORD_SECONDS,Math.floor((Date.now()-recordStarted)/1000)); $('#record-timer').textContent = Math.floor(seconds/60) + ':' + String(seconds%60).padStart(2,'0'); };
    update(); recordTimer = setInterval(update,250); recordLimit = setTimeout(stopRecording,MAX_RECORD_SECONDS*1000);
  } catch (error) { stopMicTracks(); $('#record-note').disabled = false; $('#record-help').textContent = error.name === 'NotAllowedError' ? 'Microphone access was not granted. You can write a note instead.' : clean(error.message); }
}
function stopRecording(discard = false) {
  if (recorder?.state === 'recording') { recorder._discard = discard; recorder.stop(); }
  stopMicTracks();
}
async function saveRecording() {
  if (!recordedBlob || recordedBlob.size > MAX_AUDIO_BYTES) return;
  const button = $('#save-recording'); button.disabled = true;
  try {
    const result = await api('/api/journal/audio',recordedBlob,'POST',{
      'Content-Type':recordedBlob.type,
      'X-Audio-Duration':String(recordedBlob.durationSeconds || 0),
      'X-Audio-Title':encodeURIComponent($('#record-note-title').value || 'Voice note'),
      'X-Synthetic':'true'
    });
    const transcript = $('#record-transcript').value.trim();
    const savedEntry = result.entry || result;
    if (transcript && savedEntry.id) await api('/api/journal/' + encodeURIComponent(savedEntry.id),{transcript,synthetic:true},'PATCH');
    resetRecording(); $('#record-panel').hidden = true;
    await refresh();
    $('#record-note-title').value = ''; $('#record-transcript').value = '';
    if (!transcript && (result.entry?.transcript_pending || !noteText(result.entry || result))) $('#connection').textContent = 'Voice note saved. Add a transcript to use it in recall.';
    else $('#connection').textContent = 'Voice note saved with its transcript.';
    $('#connection').dataset.kind = 'note';
    $('#connection').hidden = false;
  } catch (error) { showError(error.message); }
  finally { button.disabled = false; }
}
async function showRecall(question) {
  const button = $('#recall-form button'); button.disabled = true;
  try {
    clearError(); const result = await api('/api/journal/recall',{question});
    const sentences = result.sentences || result.answer?.sentences || [];
    const matches = result.matches || result.citations || [];
    let answer = sentences.map(sentence => `<p>${esc(sentence.text)}<br><button class="citation" data-journal-note="${esc(sentence.note_id || sentence.id)}">${esc(date(sentence.date || sentence.timestamp))} ↗</button></p>`).join('');
    if (!answer && matches.length) answer = matches.map(note => `<p>${esc(note.text || note.transcript || note.excerpt)}<br><button class="citation" data-journal-note="${esc(note.note_id || note.id)}">${esc(date(note.timestamp || note.date))} ↗</button></p>`).join('');
    if (!answer) answer = `<p>${esc((typeof result.answer === 'string' ? result.answer : '') || result.message || 'No matching saved text found. Add a transcript or try different words.')}</p>`;
    const retrieval = result.retrieval || {};
    const method = retrieval.mode === 'openai-embeddings' ? 'Matched by meaning across your saved words. The excerpts above stay exactly as recorded.' : retrieval.mode === 'lexical-provider-unavailable' ? 'Meaning-based matching is unavailable. Showing matches from saved words instead.' : retrieval.mode === 'lexical-fallback' ? 'Matched using saved words. Meaning-based matching is not connected.' : result.method || 'Extracted from saved note text. Review the original words before using them.';
    $('#recall-result').innerHTML = `<section class="recall-card"><p class="eyebrow">✧ FROM YOUR NOTES</p><p class="question">${esc(question)}</p>${answer}<p class="muted">${esc(method)}</p>${retrieval.notice ? `<p class="notice">${esc(retrieval.notice)}</p>` : ''}</section>`;
    $('#recall-result').hidden = false;
  } catch (error) { showError(error.message); }
  finally { button.disabled = false; }
}

document.addEventListener('input',event=>{
  const id=event.target.dataset?.checkinId,key=event.target.dataset?.checkinField,edit=checkinEdits.get(id);
  if(edit&&['subject','body'].includes(key)&&!checkinSaving){edit[key]=event.target.value;edit.error='';}
});
document.addEventListener('click', async event => {
  const target = event.target.closest('button,a'); if (!target) return;
  if (target.dataset.view) { event.preventDefault(); navigate(target.dataset.view,true); }
  if (target.hasAttribute('data-write-note')) { navigate('journal'); openWrite(); }
  if (target.dataset.review) { navigate('tasks'); $('#draft-' + target.dataset.review)?.scrollIntoView({block:'start',behavior:'smooth'}); }
  if (target.dataset.close) $('#' + target.dataset.close).close();
  if (target.dataset.sourceNote) openNote(target.dataset.sourceNote,true);
  if (target.dataset.journalNote) openNote(target.dataset.journalNote);
  if(target.dataset.editCheckin){const draft=(state.drafts||[]).find(item=>item.id===target.dataset.editCheckin);if(draft&&draft.kind==='checkin_reply'&&!draft.result&&!draft.sending){checkinEdits.set(draft.id,{subject:draft.subject,body:draft.body,error:''});renderTasks();}}
  if(target.dataset.cancelCheckin&&!checkinSaving){checkinEdits.delete(target.dataset.cancelCheckin);renderTasks();}
  if(target.dataset.saveCheckin)saveCheckinReply(target.dataset.saveCheckin);
  if (target.classList.contains('approve')) approve(target.dataset.id,target.dataset.digest);
  if (target.dataset.attachment && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) {
    event.preventDefault(); stopJournalAudio(); $('#note-audio').pause(); $('#attachment-title').textContent = target.dataset.attachment; $('#attachment-preview').src = target.href; $('#attachment-download').href = target.href; $('#attachment-dialog').showModal();
  }
  if (target.dataset.style) {
    chosenStyle = target.dataset.style; companionPreview = null; $('#choose-companion').hidden = true; $('#companion-preview-status').hidden = true;
    document.querySelectorAll('[data-style]').forEach(button => { const active = button.dataset.style === chosenStyle; button.classList.toggle('selected',active); button.setAttribute('aria-pressed',String(active)); });
  }
});
$('#start').onclick = async () => {
  if(demoState.request)return;demoState.request='send';demoState.error='';renderDemo();
  try{await api('/api/start',{});demoState.accepted_case_id='legacy';demoState.status='Message accepted by Pocket Ally. Background activity is available in Tasks.';await refresh();}
  catch(error){demoState.error=error.message;}
  finally{demoState.request=null;renderDemo();}
};
$('#write-note').onclick = openWrite;
$('#write-form').onsubmit = async event => {
  event.preventDefault(); const button = $('#write-form button'); button.disabled = true;
  try { clearError(); await api('/api/journal',{title:$('#note-title').value,transcript:$('#note-text').value,synthetic:true}); $('#write-dialog').close(); $('#write-form').reset(); await refresh(); }
  catch (error) { showError(error.message); } finally { button.disabled = false; }
};
$('#record-note').onclick = startRecording;
$('#stop-recording').onclick = () => stopRecording();
$('#record-dismiss').onclick = () => { stopRecording(true); resetRecording(); $('#record-panel').hidden = true; };
$('#record-typed-fallback').onclick = () => { stopRecording(true); $('#record-panel').hidden = true; openWrite(); };
$('#save-recording').onclick = saveRecording;
$('#recall-form').onsubmit = event => { event.preventDefault(); showRecall($('#recall-question').value); };
$('#note-audio').onplay = stopJournalAudio;
$('#record-preview').onplay = stopJournalAudio;
$('#note-audio').onerror = () => { $('#audio-status').hidden = false; $('#audio-status').textContent = 'Recording unavailable. The saved transcript above remains accessible.'; };
$('#note-dialog').addEventListener('close',() => $('#note-audio').pause());
$('#attachment-dialog').addEventListener('close',() => $('#attachment-preview').removeAttribute('src'));
$('#save-transcript').onclick = async () => {
  if (!activeNote) return;
  try { clearError(); await api('/api/journal/' + encodeURIComponent(activeNote.id),{transcript:$('#note-edit-text').value,synthetic:true},'PATCH'); clearNoteNotice(); await refresh(); await openNote(activeNote.id); }
  catch (error) { showError(error.message); }
};
$('#link-note').onclick = async () => {
  if (!activeNote || !$('#link-task').value) return;
  try { await api('/api/journal/' + encodeURIComponent(activeNote.id) + '/link',{task:$('#link-task').value}); await refresh(); await openNote(activeNote.id); }
  catch (error) { showError(error.message); }
};
$('#companion-prompt').oninput = () => { $('#prompt-count').textContent = $('#companion-prompt').value.length + '/200'; companionPreview = null; $('#choose-companion').hidden = true; $('#companion-preview-status').hidden = true; };
$('#companion-form').onsubmit = async event => {
  event.preventDefault(); const button = $('#preview-companion'); button.disabled = true;
  try {
    clearError(); const result = await api('/api/companion/preview',{prompt:$('#companion-prompt').value,style:chosenStyle});
    companionPreview = result.preview || result;
    $('#choose-companion').hidden = false; $('#companion-saved').hidden = true; $('#companion-preview-status').hidden = false;
    $('#companion-preview-status').textContent = clean(companionPreview.fallback_reason || (companionPreview.mode === 'openai-generated' ? 'Your generated preview is ready. Choose it to use it across your day.' : 'Personalised style preview. Choose it to use it across your day.'));
    $('#companion-method').textContent = companionPreview.mode === 'openai-generated' ? 'Generated preview' : 'Personalised preview using packaged artwork'; renderCompanion();
  } catch (error) { showError(error.message); }
  finally { button.disabled = false; }
};
$('#choose-companion').onclick = async () => {
  if (!companionPreview) return;
  const button = $('#choose-companion'); button.disabled = true;
  try {
    await api('/api/companion/select',{preview_id:companionPreview.preview_id || companionPreview.id});
    companionPreview = null; companionInitialised = false; await refresh(); button.hidden = true; $('#companion-preview-status').hidden = true;
    $('#companion-saved').hidden = false; $('#companion-saved').textContent = 'Your companion is saved. You’ll see it as you move through your day.';
  } catch (error) { showError(error.message); } finally { button.disabled = false; }
};
window.addEventListener('pagehide',() => stopRecording(true));
window.addEventListener('offline',() => { $('#connection').dataset.kind = 'offline'; $('#connection').hidden = false; $('#connection').textContent = 'You’re offline. Saving, approvals and sending need a connection.'; });
window.addEventListener('online',() => { $('#connection').hidden = true; clearError(); refresh(); });
function lockAccess(message = '') {
  stopJournalAudio();
  authLocked = true; state = null; csrf = '';
  stopRecording(true); stopCasePolling(); stopCaseReplay();
  eventStream?.close(); eventStream = null;
  document.querySelectorAll('dialog[open]').forEach(dialog => dialog.close());
  $('#main-content').hidden = true; $('.bottom-nav').hidden = true;
  $('#access-panel').hidden = false; $('#error').hidden = true;
  $('#connection').hidden = true;
  if (message) { $('#access-error').textContent = message; $('#access-error').hidden = false; }
}
function unlockAccess() {
  authLocked = false;
  $('#access-panel').hidden = true; $('#access-error').hidden = true;
  $('#main-content').hidden = false; $('.bottom-nav').hidden = false;
  ensureEvents();
}
function ensureEvents() {
  if (eventStream || authLocked || !state) return;
  eventStream = new EventSource('/api/events');
  eventStream.onmessage = event => { try { const update = JSON.parse(event.data); $('#progress-label').textContent = clean(update.tool); refresh(); } catch { showError('An update could not be read. Reload to check the saved state.'); } };
  eventStream.onerror = () => { if (!authLocked && navigator.onLine) refresh(); };
}
function setAccessBusy(busy) {
  $('#access-submit').disabled = busy;
  $('#access-submit').textContent = busy ? 'Opening securely...' : 'Open securely';
  $('#access-feedback').textContent = busy ? 'Checking your private access. Your code is not saved.' : 'Paste the link you were given, or open it again on this device.';
}
function accessCodeFromInput(value) {
  const input = value.trim();
  if (!input) return '';
  if (/^https?:\/\//i.test(input) || input.startsWith('#')) {
    const link = new URL(input,location.href);
    return new URLSearchParams(link.hash.slice(1)).get('access') || '';
  }
  if (input.startsWith('access=')) return new URLSearchParams(input).get('access') || '';
  return input;
}
function exchangeAccessToken(value) {
  let token = value.trim();
  if (!token) { lockAccess('Paste a complete private link or access code, then try again.'); return Promise.resolve(false); }
  if (accessPending && token === accessTokenInFlight) { token = ''; return accessPending; }
  const attempt = ++accessAttempt;
  const previous = accessPending || Promise.resolve();
  accessTokenInFlight = token;
  lockAccess(); $('#access-error').hidden = true; setAccessBusy(true);
  accessPending = (async () => {
    await previous.catch(() => {});
    if (attempt !== accessAttempt) { token = ''; return false; }
    try {
      await api('/api/session',{token}); token = '';
      if (attempt !== accessAttempt) return false;
      clearError(); $('#access-error').hidden = true;
      await refresh();
      return !!state && !authLocked;
    } catch (error) {
      if (attempt === accessAttempt) lockAccess([401,403].includes(error.status) ? 'That link or access code did not work. Please check it and try again.' : 'Access could not be checked. Please try again when you’re connected.');
      return false;
    } finally {
      token = '';
      if (attempt === accessAttempt) { accessPending = null; accessTokenInFlight = ''; setAccessBusy(false); }
    }
  })();
  return accessPending;
}
async function handleAccessFragment() {
  const fragment = new URLSearchParams(location.hash.slice(1));
  if (!fragment.has('access')) return false;
  let token = fragment.get('access') || '';
  history.replaceState(null,'',location.pathname + location.search + '#' + activeView);
  $('#access-input').value = '';
  const exchange = exchangeAccessToken(token); token = '';
  await exchange;
  return true;
}
$('#access-form').onsubmit = async event => {
  event.preventDefault();
  let input = $('#access-input').value; $('#access-input').value = '';
  let token = '';
  try { token = accessCodeFromInput(input); } catch { token = ''; }
  input = '';
  const exchange = exchangeAccessToken(token); token = '';
  await exchange;
};
window.addEventListener('hashchange',async () => {
  if (await handleAccessFragment()) return;
  const view = location.hash.slice(1);
  if (['home','tasks','journal','companion','demo'].includes(view)) navigate(view);
});
async function boot() {
  const requestedView = ['home','tasks','journal','companion','demo'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'home';
  if (!(await handleAccessFragment())) { navigate(requestedView); await refresh(); }
  if ('serviceWorker' in navigator && window.isSecureContext) navigator.serviceWorker.register('/sw.js',{scope:'/'}).catch(() => {});
}
boot();
