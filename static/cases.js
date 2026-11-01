/* Outcome-first case views. All work and saved results come from the server. */
let scenarios = [], scenarioBusy = false;
let savedResultCaseId = '', pollingCaseId = '', casePollTimer = null;
const demoState = {text:'',visit_id:'',origin:'',destination:'',scenario_id:'checkup-email',request:null,status:'',error:'',accepted_case_id:'',pending_followup:null};
const generatedExamplesAvailable = () => state?.capabilities?.generated_examples === true;
const editableMessagesAvailable = () => state?.capabilities?.editable_messages === true;
const caseUIAvailable = () => editableMessagesAvailable() || scenarios.length > 0 || !!state?.current_case;
const activeCase = () => state?.current_case || null;
const needsExistingVisit = item => item?.interpretation?.requires_existing_visit === true || !!item?.missing_evidence?.some(evidence=>evidence.id==='visit-target');
const caseDrafts = item => (state?.drafts || []).filter(draft => (item?.draft_ids || []).includes(draft.id));
const caseDetail = value => typeof value === 'string' ? value : value?.summary || value?.message || value?.detail || '';
const eventTitle = event => event.source_event_id && event.receipt_available ? 'Travel receipt added' : scenarios.find(scenario => scenario.event.id === event.id)?.title || 'Saved source event';
function demoMessage(scenario) {
 const source=scenario.event||{},lines=[source.text||''];
 if(source.hospital&&!source.text?.includes(source.hospital))lines.push('Location: '+source.hospital);
 if(source.department&&!source.text?.includes(source.department))lines.push('Department: '+source.department);
 return lines.join('\n');
}
const scenarioExplanation = id => ({'checkup-email':'You’re asked for an update. Your saved notes help prepare it.','confirmed-visit':'Your appointment is confirmed. We’ll prepare the visit plan.','attended-visit':'You’ve attended a visit. We’ll check what the claim needs.','reschedule':'The same visit has moved. We’ll update the existing plan.'})[id] || '';
const toolTitle = tool => ({read_source_event:'Read the email',retrieve_relevant_context:'Checked relevant dated notes',prepare_wellbeing_summary:'Prepared your observations',prepare_appointment_plan:'Prepared the visit plan',prepare_claim_pack:'Prepared the claim paperwork',prepare_employer_email:'Prepared a private manager email',request_missing_information:'Identified a missing detail',plan_tfl_journey:'Reviewed journey details'})[tool] || 'Completed a preparation step';
const noteSource = (id,label) => `<button class="text-button" data-journal-note="${esc(id)}">${esc(label)} ↗</button>`;
function eventSources(item,eventId) {
 const event=(item.events||[]).find(source=>source.id===eventId);
 return event?`<button class="text-button" data-case-event="${esc(event.id)}">${esc(eventTitle(event))} · ${esc(date(event.timestamp))} ↗</button>`:'';
}
function observationSources(action) {
 return (action.observations||[]).map(observation=>`<div class="observation"><blockquote>${esc(observation.text)}</blockquote>${noteSource(String(observation.source||'').split('/').at(-1),date(observation.date,true)+' · original words')}</div>`).join('');
}
function mainAction(item) {
 const event=item?.events?.at(-1), actions=item?.actions||[];
 const current=actions.filter(action=>action.source_event_id===event?.id||action.event_revision===item?.revision);
 const available=current.length?current:actions;
 const kind=event?.attended?'claim-pack':event?.appointment?'appointment-plan':'wellbeing-summary';
 return available.find(action=>action.kind===kind)||available.find(action=>['claim-pack','appointment-plan','wellbeing-summary'].includes(action.kind))||available.at(-1);
}
function appointmentChange(action,item) {
 const when=action?.appointment||item?.appointment;
 const priorPlans=(item?.runs||[]).flatMap(run=>run.actions||[]).filter(plan=>plan.kind==='appointment-plan'&&plan.appointment&&plan.appointment!==when);
 const previous=action?.previous_appointment||(action?.is_reschedule===undefined?priorPlans.at(-1)?.appointment:null);
 const changed=typeof action?.is_reschedule==='boolean'?action.is_reschedule:item?.interpretation?.intent==='reschedule'||!!previous;
 return {changed,previous};
}
function outcomeTitle(item) {
 if(!item)return 'A little less to carry.';
 if(item.status==='running')return 'Taking care of your next step.';
 if(item.error)return 'One thing needs a check.';
 if(needsExistingVisit(item))return 'Select the existing visit.';
 if(item.missing_evidence?.length)return item.missing_evidence.some(evidence=>evidence.id==='travel-receipt')?'Your claim needs a receipt.':'One detail is needed.';
 const action=mainAction(item);
 if(action?.kind==='wellbeing-summary'){const reply=caseDrafts(item).find(draft=>draft.kind==='checkin_reply');return reply?reply.result?(reply.result.delivery==='local outbox only'?'Your check-in reply is saved':'Your check-in reply was sent'):'Your check-in reply is ready to review':action.summary_mode==='agent-synthesis'?'Your check-in summary':'Original sources for your check-in';}
 if(action?.kind==='appointment-plan')return appointmentChange(action,item).changed?'Your visit date is updated':'Your appointment is planned';
 if(action?.kind==='claim-pack'){const result=caseDrafts(item).find(draft=>draft.kind==='claim'&&draft.result)?.result;return result?(result.delivery==='local outbox only'?'Your claim email is saved':'Your claim email was sent'):'Your claim pack is ready to review';}
 return 'Your result is ready';
}
function outcomeSummary(item) {
 if(!item)return 'Send a synthetic incoming message into Pocket Ally. It will use the facts and relevant saved notes to prepare the next step.';
 if(item.status==='running')return 'Work is happening in the background. No email is being sent.';
 if(item.error)return 'The case paused safely. Open it to check what happened and try again.';
 if(needsExistingVisit(item))return 'Choose which existing visit this date change belongs to. It will update that visit.';
 if(item.missing_evidence?.some(evidence=>evidence.id==='journal-context'))return 'Add your own dated observations in Journal before a grounded update can be prepared.';
 if(item.missing_evidence?.length)return item.missing_evidence.some(evidence=>evidence.id==='travel-receipt')?'Your unsigned paperwork is ready. Add the synthetic receipt to continue the same claim.':'Check the missing detail, then update your message to continue the same visit.';
 const action=mainAction(item);
 if(action?.kind==='wellbeing-summary')return action.summary_mode==='agent-synthesis'?'A generated summary grounded in your dated notes. Review the wording and original sources.':'Original source notes are available. No generated synthesis is shown.';
 if(action?.kind==='appointment-plan')return item.appointment?date(item.appointment,true)+' · '+clock(item.appointment):'Your visit plan and calendar download are ready.';
 if(action?.kind==='claim-pack'){const result=caseDrafts(item).find(draft=>draft.kind==='claim'&&draft.result)?.result;return result?(result.delivery==='local outbox only'?'Your exact approved copy is in the local outbox.':'Your exact approved copy was sent to your configured test inbox.'):'Check the unsigned PDF and exact email before approving.';}
 return 'Open the result to review what has been prepared.';
}
function renderCaseHome() {
 const item=activeCase(),missing=item?.missing_evidence||[],draft=caseDrafts(item).find(candidate=>!candidate.result);
 let next='';
 if(item?.status==='running')next=`<button class="row-card" data-case-section="case-progress"><span><strong>See progress</strong><span class="muted">Only completed steps are listed</span></span>${icon('arrow')}</button>`;
 else if(missing.length)next=`<div class="decision-card"><span class="decision-label">One thing needed</span><h2>${esc(missing[0].label)}</h2><p>${missing.some(evidence=>evidence.id==='journal-context')?'Add your own dated observations in Journal.':needsExistingVisit(item)?'Select the existing visit before applying this date change.':missing.some(evidence=>evidence.id==='travel-receipt')?'Add the demo receipt to finish preparing this same claim.':'Update the message or journey details to continue this same visit.'}</p><button class="primary" data-case-section="case-evidence">Continue ${icon('arrow')}</button></div>`;
 else if(draft)next=`<div class="decision-card"><span class="decision-label">Your review comes first</span><h2>${draft.kind==='claim'?'Review the claim email':draft.kind==='checkin_reply'?'Review your check-in reply':'Review the manager email'}</h2><p>Check the exact recipient, words and files before approving.</p><button class="primary" data-review="${esc(draft.id)}">Review exact draft ${icon('arrow')}</button></div>`;
 else next=`<button class="row-card" data-case-section="${!item&&editableMessagesAvailable()?'incoming-form':'case-workspace'}"><span><strong>${mainAction(item)?.kind==='wellbeing-summary'?'Review your observations':item?'Open your result':'Open Demo'}</strong><span class="muted">${item?'Your sources are there when you need them':editableMessagesAvailable()?'Send a synthetic message from Demo':'Send a demo message to begin'}</span></span>${icon('arrow')}</button>`;
 const latest=[...journal].sort((a,b)=>noteTime(b).localeCompare(noteTime(a)))[0];
 const deliveries=caseDrafts(item).filter(candidate=>candidate.result);
 $('#home-content').innerHTML=`<section class="home-summary ${item?.error||clientError?'is-stuck':''}"><div class="summary-copy"><h2>${esc(outcomeTitle(item))}</h2><p>${esc(outcomeSummary(item))}</p></div><img src="${esc(companionImage())}" alt="Your companion" style="filter:${visualFilter(selectedCompanion())}"></section>${next}${item?.appointment?`<div class="section-heading"><h2>Your visit</h2></div><button class="row-card" data-view="tasks"><span class="date-tile">${esc(new Date(item.appointment).toLocaleDateString('en-GB',{weekday:'short',timeZone:'Europe/London'}))}<b>${esc(new Date(item.appointment).toLocaleDateString('en-GB',{day:'2-digit',timeZone:'Europe/London'}))}</b></span><span><strong>Personal appointment</strong><span class="muted">${esc(date(item.appointment,true))} · ${esc(clock(item.appointment))}</span></span>${icon('arrow')}</button>`:''}${deliveries.length?`<div class="section-heading"><h2>Taken care of</h2></div><ul class="completion-list">${deliveries.map(candidate=>`<li><span class="tick">${icon('check')}</span>${candidate.kind==='claim'?'Claim email':candidate.kind==='checkin_reply'?'Check-in reply':'Manager email'} ${candidate.result.delivery==='local outbox only'?'saved locally':'sent to test inbox'}</li>`).join('')}</ul>`:''}<button class="row-card" data-write-note>${icon('write')}<span><strong>Make a note of today</strong><span class="muted">${latest?'Last note: '+esc(noteTitle(latest)):'Keep your words close'}</span></span>${icon('arrow')}</button><p class="safety-note">Synthetic administrative demo. No clinical advice. Refund and eligibility remain unconfirmed.</p>`;
}
function journeyCard(action) {
 const trip=action.journey||{},routes=trip.journeys||[];
 const query=trip.query||{};
 return `<section class="card outcome-card"><span class="result-label">Journey planning</span><h2>${routes.length?'Your journey options':action.status==='needs-information'?'Add journey details':'Journey options unavailable'}</h2><p>${esc(action.detail||'')}</p>${query.origin&&query.destination?`<p><strong>${esc(query.origin)}</strong> to <strong>${esc(query.destination)}</strong></p>`:''}${routes.map((route,index)=>`<div class="journey-option">${index===trip.selected_index?'<p class="result-label">Used in your calendar</p>':''}<h3>${esc(route.summary||'Journey option')}</h3><p>${esc(route.duration_minutes)} minutes${Number.isFinite(route.walking_minutes)?' · '+esc(route.walking_minutes)+' minutes walking':''}</p>${route.departure&&route.arrival?`<p class="muted">${esc(clock(route.departure))} to ${esc(clock(route.arrival))}</p>`:''}<details><summary>Journey steps</summary><ol class="route-steps">${(route.legs||[]).map(leg=>`<li>${esc(leg.instruction||leg.mode)}${Number.isFinite(leg.duration_minutes)?' · '+esc(leg.duration_minutes)+' min':''}</li>`).join('')}</ol></details></div>`).join('')}${trip.mode==='tfl-live-response'?`<p class="muted">TfL journey planning response${trip.checked_at?' · checked '+esc(date(trip.checked_at,true))+' at '+esc(clock(trip.checked_at)):''}</p>`:'<p class="muted">No TfL journey result is available. No route has been invented.</p>'}${typeof trip.source==='string'&&trip.source.startsWith('https://api.tfl.gov.uk/')?`<a href="${esc(trip.source)}" target="_blank" rel="noopener">TfL route endpoint ↗</a>`:''}<p class="safety-note">${esc(trip.notice||'Planning estimate only. Recheck before travelling. Not a live departure prediction or an accessibility guarantee.')}</p></section>`;
}
function outcomeCard(action,item) {
 if(action.kind==='journey-plan')return journeyCard(action);
 if(action.kind==='wellbeing-summary'){
  const generated=action.summary_mode==='agent-synthesis'&&(action.summary_sentences||[]).length;
  const summary=generated?(action.summary_sentences||[]).map(sentence=>`<p class="synthesised-summary">${esc(sentence.text)}</p><div class="summary-citations">${(sentence.sources||[]).map(source=>noteSource(source.note_id,date(source.date,true)+' · source')).join('')}</div>`).join(''):'';
  return `<section id="case-observations" class="card outcome-card"><span class="result-label">${generated?'Generated summary':'Original sources only'}</span><h2>${generated?'Your check-in summary':'Original sources for your check-in'}</h2>${summary||'<p>No generated synthesis is available. You can review the original dated sources below.</p>'}${action.reply_required?'<p class="muted">Your editable email reply is below. Saving changes does not send it. Review the exact copy before approving.</p>':'<p class="muted">For your own review. No email reply has been prepared.</p>'}<details class="summary-originals"><summary>Review original dated sources</summary>${observationSources(action)||'<p class="muted">No original sources were recorded.</p>'}</details><p class="safety-note">Administrative summary only. No clinical interpretation or advice.</p></section>`;
 }
 if(action.kind==='appointment-plan'){
  const when=action.appointment||item.appointment,{changed,previous}=appointmentChange(action,item);
  return `<section class="card outcome-card"><span class="result-label">Visit plan ready</span><h2>${changed?'Your visit has moved':'Your appointment is planned'}</h2>${when?`<p class="visit-result-date">${esc(date(when,true))}<br><strong>${esc(clock(when))}</strong></p>`:''}${changed&&previous?`<p class="muted">Previously ${esc(date(previous,true))} at ${esc(clock(previous))}. The same visit has been updated.</p>`:''}${action.travel_checked_at?`<p>Calendar travel starts at ${esc(clock(action.travel_departure))}, using the selected TfL journey checked at ${esc(clock(action.travel_checked_at))}. Recheck before travelling. Appointment length is a 60-minute estimate.</p>`:'<p>Calendar includes an unverified 50-minute travel buffer and a 60-minute appointment estimate. Travel has not been checked.</p>'}${action.calendar_url?`<a class="primary action-link" href="${esc(action.calendar_url)}">Download your visit plan ↗</a><p class="muted">Calendar file only. It has not been added to Google Calendar.</p>`:''}</section>`;
 }
 if(action.kind==='claim-pack'){
  const result=caseDrafts(item).find(draft=>draft.kind==='claim'&&draft.result)?.result;
  const local=result?.delivery==='local outbox only';
  return `<section class="card outcome-card"><span class="result-label">${result?'Approved copy '+(local?'saved':'sent'):item.missing_evidence?.length?'One thing needed':'Claim paperwork ready'}</span><h2>${result?(local?'Your claim email is saved':'Your claim email was sent'):item.missing_evidence?.length?'Your claim needs a receipt':'Your claim pack is ready to review'}</h2>${result?`<p>${local?'The exact copy you approved was saved to the local outbox. Nothing was emailed.':'The exact copy you approved was sent to your configured test inbox.'}</p>`:''}<p>${result?'Your paperwork remains unsigned.':'Your unsigned paperwork is prepared.'} Refund and eligibility are unconfirmed. Signature and bank details stay blank.</p>${action.pdf_url?`<a class="secondary action-link" data-attachment="Unsigned HC5(T) draft" href="${esc(action.pdf_url)}" target="_blank" rel="noopener">View unsigned claim PDF ↗</a>`:''}</section>`;
 }
 return '';
}
function caseRetrievalLabel(item) {
 const retrieval=item.retrieval||{};
 return retrieval.mode==='openai-embeddings'?'Relevant notes matched by meaning using OpenAI. Original source wording retained.':retrieval.mode==='lexical-provider-unavailable'?'Meaning-based matching was unavailable. Saved-word matches were used instead.':retrieval.mode==='lexical-fallback'?'Relevant notes matched using saved words and bounded topics. No meaning-based provider was called.':'';
}
function caseDetails(item) {
 return `<details id="case-details" class="card case-details"><summary>Sources, explanation and history</summary><h3>Source messages and receipt</h3>${(item.events||[]).map(event=>eventSources(item,event.id)).join('')}<h3>Why these steps were taken</h3><p>${esc(item.decision?.summary||'No explanation was recorded.')}</p><p class="muted">${item.decision?.mode==='agents-sdk'?'Prepared using a model decision.':'Prepared using the scripted demo fallback. No model decision was made.'}</p><ol class="case-trail">${(item.decision?.tool_calls||[]).map(call=>`<li><strong>${esc(toolTitle(call.tool))}</strong><p>${esc(call.reason)}</p><span class="muted">${esc(date(call.at,true))} · ${esc(clock(call.at))}</span></li>`).join('')}</ol><h3>Relevant saved notes</h3><p class="muted">${esc(caseRetrievalLabel(item))}</p><p class="muted">Saved context as of ${esc(date(item.updated_at,true))} · ${esc(clock(item.updated_at))}. Notes added later are not claimed to be included.</p>${(item.context||[]).map(source=>`<div class="source-reference">${noteSource(source.note_id,date(source.date,true)+' · '+noteTitle(journal.find(note=>note.id===source.note_id)))}<p class="muted">${esc(source.reason)}</p></div>`).join('')||'<p class="muted">No saved note was selected.</p>'}<h3>Saved history</h3>${(item.runs||[]).map(run=>`<details class="case-run"><summary>${esc(date(run.at,true))} · ${esc(clock(run.at))}</summary><p>${esc(run.decision?.summary||'Saved preparation result.')}</p><p class="muted">${(run.decision?.tool_calls||[]).length} completed steps. Context saved at this time.</p>${eventSources(item,run.event_id)}</details>`).join('')||'<p class="muted">No earlier preparation is recorded.</p>'}<p class="safety-note">These are saved records. Opening them does not run work again or share any information.</p></details>`;
}
function renderCaseTasks() {
 const available=caseUIAvailable(),item=activeCase();
 $('#case-workspace').hidden=!available||!item;$('#legacy-records').hidden=true;
 if(!available)return false;
 $('#mode').textContent='';$('#launch').hidden=true;$('#workspace').hidden=true;$('#progress').hidden=true;
 $('#task-guide').innerHTML=guide(item?.status==='running'?'Working on this case. You can see the completed steps below.':item?.error?'The case paused safely. Check the message below.':item?'Your result is here. You choose what to review or share.':editableMessagesAvailable()?'Send a synthetic message from Demo. Its background progress and result will appear here.':'Open Demo to send an example into Pocket Ally. Your result will appear here.',!!(item?.error||clientError));
 const allIds=new Set([...(state.cases||[]).flatMap(candidate=>candidate.draft_ids||[]),...(item?.draft_ids||[])]);
 const legacy=(state.drafts||[]).filter(draft=>!allIds.has(draft.id));if(legacy.length){$('#legacy-records').hidden=false;$('#legacy-drafts').innerHTML=legacy.map(renderDraftCard).join('');}
 if(!item){$('#task-guide').innerHTML+='<button class="secondary" data-view="demo">Open Demo</button>';return true;}
 if(item.status==='running'){
  $('#case-workspace').innerHTML=`<section id="case-progress" class="card" role="status" aria-live="polite"><h2>Working on this case</h2>${item.active_stage?.label?`<p><strong>${esc(item.active_stage.label)}</strong></p>`:''}<p>No email is being sent. These steps have finished so far:</p>${item.decision?.tool_calls?.length?`<ul class="completed-steps">${item.decision.tool_calls.map(call=>`<li>${icon('check')} ${esc(toolTitle(call.tool))}</li>`).join('')}</ul>`:'<p class="muted">Getting started...</p>'}<p class="muted">Your result will appear here when it is ready.</p></section>`;startCasePolling(item.id);return true;
 }
 const actions=item.actions||[],primary=mainAction(item),ordered=primary?[primary,...actions.filter(action=>action!==primary)]:actions;
 const missing=item.missing_evidence||[],drafts=caseDrafts(item);
 $('#case-workspace').innerHTML=`${savedResultCaseId===item.id?'<p class="saved-result-notice" role="status">Already handled. Here is your current result.</p>':''}${item.error?`<section class="card"><h2>We paused safely</h2><p>${esc(item.error)}</p><p class="muted">${editableMessagesAvailable()?'Open Demo to send this incoming message to Pocket Ally again.':'Open Demo and send this demo message again.'} No outgoing email was sent.</p>${editableMessagesAvailable()?`<button type="button" class="secondary" data-demo-followup="${esc(item.id)}">Compose a follow-up in Demo</button>`:''}</section>`:''}${missing.length?`<section id="case-evidence" class="card"><h2>What to do next</h2>${missing.map(evidence=>`<p><strong>${esc(evidence.label)}</strong></p><p>${esc(evidence.detail)}</p>${evidence.id==='journal-context'?'<button type="button" class="secondary" data-write-note>Add journal observations</button>':''}${evidence.id!=='travel-receipt'&&evidence.id!=='journal-context'&&editableMessagesAvailable()?`<button type="button" class="secondary" data-demo-followup="${esc(item.id)}">Compose a follow-up in Demo</button>`:''}${evidence.id==='travel-receipt'?`<button class="primary" id="add-synthetic-receipt" ${scenarioBusy?'disabled':''}>Add synthetic receipt & continue</button><p class="muted">Uses the demo receipt. Continues this same claim.</p>`:''}`).join('')}</section>`:''}${ordered.map(action=>outcomeCard(action,item)).join('')}${drafts.length?`<div class="section-heading"><h2>${drafts.every(draft=>draft.result)?'Approved copy':'Review before sharing'}</h2></div><div id="case-drafts">${drafts.map(renderDraftCard).join('')}</div>`:''}${caseDetails(item)}`;
 return true;
}
function stopCasePolling(){clearTimeout(casePollTimer);casePollTimer=null;pollingCaseId='';}
function startCasePolling(caseId){if(pollingCaseId===caseId)return;stopCasePolling();pollingCaseId=caseId;const poll=async()=>{try{const result=await api('/api/cases/'+encodeURIComponent(caseId));if(pollingCaseId!==caseId)return;await refresh();if(result.status==='running')casePollTimer=setTimeout(poll,800);else stopCasePolling();}catch(error){stopCasePolling();if(!error.staleAuth&&error.status!==401)showError(error.message);}};casePollTimer=setTimeout(poll,500);}
function stopCaseReplay(){/* Saved results are opened directly, never animated as work. */}
async function runScenario(id,receipt=false) {
 if(receipt){
  if(scenarioBusy)return;scenarioBusy=true;renderTasks();
  try{const result=await api('/api/cases/'+encodeURIComponent(activeCase().id)+'/evidence/receipt',{synthetic:true});savedResultCaseId=result.replayed&&result.status!=='running'?result.case_id:'';await refresh();if(result.status==='running')startCasePolling(result.case_id);}
  catch(error){showError(error.message);}finally{scenarioBusy=false;renderTasks();}return;
 }
 if(demoState.request)return;demoState.request='send';demoState.error='';renderDemo();
 try{const result=await api('/api/scenarios/'+encodeURIComponent(id)+'/run',{});acceptDemoMessage(result);await refresh();if(result.status==='running')startCasePolling(result.case_id);}
 catch(error){demoState.error=error.message;}finally{demoState.request=null;renderDemo();}
}
const demoFields = {'incoming-text':'text','incoming-visit':'visit_id','journey-origin':'origin','journey-destination':'destination','scenario-select':'scenario_id'};
function captureDemoDraft() {
 for(const [id,key] of Object.entries(demoFields)){const input=$('#'+id);if(input)demoState[key]=input.value;}
}
function demoHasDraft(){return !!(demoState.text.trim()||demoState.visit_id||demoState.origin.trim()||demoState.destination.trim());}
function renderIncomingForm() {
 const form=$('#incoming-form');if(!form)return;
 form.hidden=!editableMessagesAvailable();$('#incoming-editor').hidden=form.hidden;if(form.hidden)return;
 const select=$('#incoming-visit'),stories=(state?.cases||[]).filter(item=>item.visit_assignment!=='unassigned');
 select.innerHTML='<option value="">New story context</option>'+stories.map((story,index)=>`<option value="${esc(story.visit_id)}">${story.appointment?'Appointment story · '+esc(date(story.appointment,true))+' at '+esc(clock(story.appointment)):'Saved story context '+(index+1)}</option>`).join('');
 if(demoState.visit_id&&!stories.some(story=>story.visit_id===demoState.visit_id))select.innerHTML+=`<option value="${esc(demoState.visit_id)}">Previously selected story context (currently unavailable)</option>`;
 for(const [id,key] of Object.entries(demoFields)){if(id==='scenario-select')continue;const input=$('#'+id);if(input.value!==demoState[key])input.value=demoState[key];input.disabled=!!demoState.request;}
 $('#run-incoming').disabled=!!demoState.request;$('#run-incoming').textContent=demoState.request==='send'?'Sending...':'Send to Pocket Ally';
 renderDemoStatus();
}
function renderDemoStatus() {
 $('#incoming-help').textContent=demoState.request==='send'?'Sending this synthetic incoming message to Pocket Ally...':demoState.error||demoState.status;
 $('#incoming-help').setAttribute('role',demoState.error?'alert':'status');
 $('#demo-view-activity').hidden=!demoState.accepted_case_id;
 $('#legacy-demo-status').textContent=demoState.error||demoState.status;$('#legacy-demo-activity').hidden=!demoState.accepted_case_id;
 $('#demo-followup-choice').hidden=!demoState.pending_followup;
 $('#keep-demo-draft').disabled=!!demoState.request;$('#replace-demo-draft').disabled=!!demoState.request;
}
function renderExampleStatus() {
 const status=$('#example-status');if(!status)return;
 status.hidden=!generatedExamplesAvailable()||demoState.request!=='generate';status.textContent=demoState.request==='generate'?'Generating a synthetic message...':'';
}
function renderDemo() {
 const available=editableMessagesAvailable()||scenarios.length>0;$('#launch').hidden=available;$('#start').disabled=!!demoState.request;$('#start').textContent=demoState.request==='send'?'Sending...':'Send to Pocket Ally';$('#scenario-panel').hidden=!available||!scenarios.length;$('#demo-unavailable').hidden=available;
 $('#scenario-select').innerHTML=scenarios.map(scenario=>`<option value="${esc(scenario.id)}">${esc(scenario.title)}</option>`).join('');$('#scenario-select').value=demoState.scenario_id;
 $('#scenario-panel label').textContent=generatedExamplesAvailable()?'Example situation':'Try a demo';
 $('#example-provider-notice').hidden=!generatedExamplesAvailable();renderExampleStatus();
 $('#scenario-description').textContent=generatedExamplesAvailable()?'Generate a realistic synthetic message using only the story context you choose. Review and edit it below.':editableMessagesAvailable()?'Fills the message below. You can edit every word before sending to Pocket Ally.':scenarioExplanation(demoState.scenario_id);
 $('#scenario-panel .scenario-help').textContent=generatedExamplesAvailable()?'Generating fills your Demo draft only. Send to Pocket Ally when you are ready.':editableMessagesAvailable()?'Demo examples only fill the visible message. Story context stays as you chose it.':'Send this demo message into Pocket Ally once. Sending it again opens its current result.';
 $('#run-scenario').textContent=demoState.request==='generate'?'Generating...':demoState.request==='send'?'Sending...':generatedExamplesAvailable()?'Generate next message':editableMessagesAvailable()?'Use this message':'Send demo message';
 $('#run-scenario').disabled=!!demoState.request||!scenarios.some(scenario=>scenario.id===demoState.scenario_id);$('#scenario-select').disabled=!!demoState.request;
 renderIncomingForm();renderDemoStatus();
}
function acceptDemoMessage(result) {
 savedResultCaseId=result.replayed&&result.status!=='running'?result.case_id:'';
 demoState.accepted_case_id=result.case_id;
 demoState.status=result.replayed?'Already received by Pocket Ally. You can view the current activity in Tasks.':'Message accepted by Pocket Ally. Background activity is available in Tasks.';
}
async function sendDemoMessage() {
 if(demoState.request)return;captureDemoDraft();if(!demoState.text.trim())return;
 const payload={text:demoState.text.trim(),synthetic:true};
 for(const key of ['visit_id','origin','destination'])if(demoState[key].trim())payload[key]=demoState[key].trim();
 demoState.request='send';demoState.error='';demoState.status='';renderDemo();
 try{const result=await api('/api/events/run',payload);acceptDemoMessage(result);await refresh();if(result.status==='running')startCasePolling(result.case_id);}
 catch(error){demoState.error=error.status===404?'This version does not support editable messages. Reload after the update.':error.message;}
 finally{demoState.request=null;renderDemo();}
}
async function generateExampleMessage() {
 if(!generatedExamplesAvailable()||demoState.request)return;captureDemoDraft();
 const payload={scenario_id:demoState.scenario_id};if(demoState.visit_id)payload.visit_id=demoState.visit_id;
 demoState.request='generate';demoState.error='';demoState.status='';renderDemo();
 try{
  const result=await api('/api/events/example',payload);
  if(result.generation_mode!=='responses'||typeof result.text!=='string'||!result.text.trim()||result.text.length>6000)throw new Error('The example could not be generated. Your existing draft is unchanged. Try again.');
  if(result.visit_id&&!(state.cases||[]).some(item=>item.visit_id===result.visit_id&&item.visit_assignment!=='unassigned'))throw new Error('The example refers to a story context that is unavailable. Your existing draft is unchanged.');
  demoState.text=result.text;if(typeof result.visit_id==='string')demoState.visit_id=result.visit_id;
  if(typeof result.origin==='string')demoState.origin=result.origin;if(typeof result.destination==='string')demoState.destination=result.destination;
  demoState.accepted_case_id='';demoState.status='Generated example ready. Review and edit before sending to Pocket Ally.'+(result.context_summary?' '+result.context_summary:'');$('#incoming-editor').open=true;
 }catch(error){demoState.error=error.message||'Message generation is unavailable. Your existing draft is unchanged.';}
 finally{demoState.request=null;renderDemo();}
}
function applyDemoFollowup(source) {
 for(const key of ['text','visit_id','origin','destination'])demoState[key]=source[key]||'';
 demoState.pending_followup=null;demoState.accepted_case_id='';demoState.error='';demoState.status='Follow-up copied explicitly from activity. Review and edit before sending to Pocket Ally.';
 $('#incoming-editor').open=true;renderDemo();
}
function requestDemoFollowup(item) {
 if(!item)return;captureDemoDraft();const source=item.events?.at(-1)||{};
 const followup={text:source.text||'',visit_id:item.visit_assignment==='unassigned'||needsExistingVisit(item)?'':item.visit_id,origin:source.origin||'',destination:source.destination||''};
 const same=['text','visit_id','origin','destination'].every(key=>demoState[key]===followup[key]);
 if(!demoState.request&&(!demoHasDraft()||same))applyDemoFollowup(followup);else{demoState.pending_followup=followup;renderDemo();}
 navigate('demo',true);
}
function updateDemoField(event) {
 const key=demoFields[event.target.id];if(!key||demoState.request)return;
 demoState[key]=event.target.value;demoState.error='';demoState.accepted_case_id='';demoState.status='Draft changed. These edits have not been sent to Pocket Ally.';
 if(key==='scenario_id')renderDemo();else renderDemoStatus();
}
document.addEventListener('input',updateDemoField);
document.addEventListener('change',updateDemoField);
document.addEventListener('submit',event=>{if(event.target.id==='incoming-form'){event.preventDefault();sendDemoMessage();}});
document.addEventListener('click',event=>{
 const button=event.target.closest('button');if(!button)return;
 if(button.id==='run-scenario'){
  if(generatedExamplesAvailable())generateExampleMessage();
  else if(editableMessagesAvailable()){captureDemoDraft();const preset=scenarios.find(scenario=>scenario.id===demoState.scenario_id);if(preset){demoState.text=demoMessage(preset);demoState.status='Example added to your Demo draft. Review and edit before sending.';demoState.error='';demoState.accepted_case_id='';$('#incoming-editor').open=true;renderDemo();}}
  else runScenario(demoState.scenario_id);
 }
 if(button.id==='add-synthetic-receipt')runScenario('',true);
 if(button.id==='keep-demo-draft'){demoState.pending_followup=null;renderDemo();}
 if(button.id==='replace-demo-draft'&&!demoState.request&&demoState.pending_followup)applyDemoFollowup(demoState.pending_followup);
 if(button.dataset.demoFollowup){const item=(state.cases||[]).find(candidate=>candidate.id===button.dataset.demoFollowup)||(activeCase()?.id===button.dataset.demoFollowup?activeCase():null);requestDemoFollowup(item);}
 if(button.dataset.caseSection){const editor=button.dataset.caseSection==='incoming-form';if(editor)$('#incoming-editor').open=true;navigate(editor?'demo':'tasks',true);$('#'+button.dataset.caseSection)?.scrollIntoView({block:'start',behavior:'smooth'});}
 if(button.dataset.caseEvent){const source=activeCase()?.events?.find(candidate=>candidate.id===button.dataset.caseEvent);if(!source)return;$('#case-source-title').textContent=eventTitle(source);$('#case-source-kind').textContent=source.source_event_id?'SYNTHETIC RECEIPT EVENT':'SYNTHETIC MESSAGE SOURCE';$('#case-source-date').textContent=date(source.timestamp,true)+' · '+clock(source.timestamp);$('#case-source-text').textContent=source.text;$('#case-source-dialog').showModal();}
});
