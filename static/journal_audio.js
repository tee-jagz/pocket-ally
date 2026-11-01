/* One journal recording at a time. Playback stays separate from transcript review. */
let journalAudio = null, journalAudioNote = null, journalAudioState = 'idle', journalAudioError = '', journalAudioAttempt = 0;
function journalAudioURL(note) {
 const url=note?.audio_url||(note?.audio_path?'/api/notes/'+encodeURIComponent(note.id)+'/audio':'');
 return /^\/api\/notes\/[^/?#]+\/audio$/.test(url)?url:'';
}
function journalAudioMessage(note) {
 if(journalAudioNote?.id===note.id){
  if(journalAudioError)return journalAudioError;
  if(journalAudioState==='loading')return 'Loading recording...';
  if(journalAudioState==='playing')return 'Playing recording';
  if(journalAudioState==='paused')return 'Recording paused';
  if(journalAudioState==='ended')return 'Recording finished';
 }
 return journalAudioURL(note)?'Recording available. '+(noteText(note)?'Transcript available.':'Add a transcript for recall.'):'Recording unavailable. You can still review the saved text.';
}
function journalAudioControls(note) {
 const active=journalAudioNote?.id===note.id,playing=active&&journalAudioState==='playing',loading=active&&journalAudioState==='loading';
 return `<div class="entry-meta"><button type="button" class="play-badge" data-journal-play="${esc(note.id)}" aria-label="${esc((playing?'Pause':loading?'Cancel loading':'Play')+' recording: '+noteTitle(note))}" aria-pressed="${playing}" ${journalAudioURL(note)?'':'disabled'}>${playing?'❚❚':loading?'×':'▶'}</button><span class="waveform" aria-hidden="true"></span><span class="entry-audio-status" data-journal-audio-status="${esc(note.id)}" role="status" aria-live="polite">${esc(journalAudioMessage(note))}</span></div>`;
}
function syncJournalAudioControls() {
 document.querySelectorAll('[data-journal-play]').forEach(button=>{
  const note=journal.find(item=>item.id===button.dataset.journalPlay);if(!note)return;
  const active=journalAudioNote?.id===note.id,playing=active&&journalAudioState==='playing',loading=active&&journalAudioState==='loading';
  button.textContent=playing?'❚❚':loading?'×':'▶';button.setAttribute('aria-pressed',String(playing));
  button.setAttribute('aria-label',(playing?'Pause':loading?'Cancel loading':'Play')+' recording: '+noteTitle(note));
 });
 document.querySelectorAll('[data-journal-audio-status]').forEach(status=>{const note=journal.find(item=>item.id===status.dataset.journalAudioStatus);if(note)status.textContent=journalAudioMessage(note);});
}
function stopJournalAudio() {
 journalAudioAttempt++;
 if(journalAudio){journalAudio.onplaying=null;journalAudio.onpause=null;journalAudio.onended=null;journalAudio.onerror=null;journalAudio.pause();journalAudio.removeAttribute('src');journalAudio.load();}
 journalAudio=null;journalAudioNote=null;journalAudioState='idle';journalAudioError='';syncJournalAudioControls();
}
async function toggleJournalAudio(id) {
 const note=journal.find(item=>item.id===id),url=journalAudioURL(note);if(!note||!url)return;
 if(journalAudioNote?.id===id&&['playing','loading'].includes(journalAudioState)){
  if(journalAudioState==='loading')stopJournalAudio();else journalAudio.pause();return;
 }
 if(journalAudioNote?.id!==id||journalAudioError){
  stopJournalAudio();journalAudioNote=note;journalAudio=new Audio(url);journalAudio.preload='metadata';
 }
 const audio=journalAudio,attempt=++journalAudioAttempt;
 const current=()=>journalAudio===audio&&journalAudioAttempt===attempt;
 const failed=()=>{if(!current())return;journalAudioState='error';journalAudioError='Recording could not play. Try again, or open the entry to review its transcript.';syncJournalAudioControls();};
 audio.onplaying=()=>{if(!current())return;journalAudioState='playing';syncJournalAudioControls();};
 audio.onpause=()=>{if(!current()||audio.ended)return;journalAudioState='paused';syncJournalAudioControls();};
 audio.onended=()=>{if(!current())return;journalAudioState='ended';syncJournalAudioControls();};
 audio.onerror=failed;
 if(audio.ended)audio.currentTime=0;
 $('#note-audio')?.pause();$('#record-preview')?.pause();
 journalAudioError='';journalAudioState='loading';syncJournalAudioControls();
 try{await audio.play();if(!current())audio.pause();}catch(error){failed();}
}
document.addEventListener('click',event=>{const button=event.target.closest('[data-journal-play]');if(button){event.preventDefault();toggleJournalAudio(button.dataset.journalPlay);}});
window.addEventListener('pagehide',stopJournalAudio);
