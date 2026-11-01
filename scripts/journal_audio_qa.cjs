/* Source-level playback checks using a fake media element, not browser automation. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const instances=[],listeners={},notes=[{id:'note-1',title:'First synthetic note',transcript:'Words',audio_url:'/api/notes/note-1/audio'},{id:'note-2',title:'Second synthetic note',transcript:'Other words',audio_url:'/api/notes/note-2/audio'},{id:'text-only',title:'Typed note',transcript:'Text'}];
const buttons=notes.map(note=>({dataset:{journalPlay:note.id},attributes:{},setAttribute(key,value){this.attributes[key]=value}}));
const statuses=notes.map(note=>({dataset:{journalAudioStatus:note.id},textContent:''}));
let playMode='normal',lateResolve;
class FakeAudio{
 constructor(url){this.src=url;this.paused=true;this.ended=false;instances.push(this)}
 play(){this.paused=false;if(playMode==='reject')return Promise.reject(Error('Media unavailable'));if(playMode==='deferred')return new Promise(resolve=>{lateResolve=resolve});this.onplaying?.();return Promise.resolve()}
 pause(){this.paused=true;this.onpause?.()}
 removeAttribute(name){if(name==='src')this.src=''}load(){}
}
const context=vm.createContext({Audio:FakeAudio,journal:notes,noteText:note=>note.transcript||'',noteTitle:note=>note.title,esc:value=>String(value??'').replaceAll('"','&quot;'),$:()=>({pause(){}}),document:{querySelectorAll(selector){return selector==='[data-journal-play]'?buttons:statuses},addEventListener(type,callback){listeners[type]=callback}},window:{addEventListener(type,callback){listeners[type]=callback}}});
vm.runInContext(fs.readFileSync('static/journal_audio.js','utf8'),context);
(async()=>{
 const markup=vm.runInContext('journalAudioControls(journal[0])',context);assert.match(markup,/<button[^>]+data-journal-play/);assert.match(markup,/aria-label="Play recording: First synthetic note"/);
 await context.toggleJournalAudio('note-1');assert.equal(instances[0].src,notes[0].audio_url);assert.equal(buttons[0].attributes['aria-pressed'],'true');assert.equal(statuses[0].textContent,'Playing recording');
 await context.toggleJournalAudio('note-1');assert.equal(instances[0].paused,true);assert.equal(statuses[0].textContent,'Recording paused');assert.equal(buttons[0].attributes['aria-pressed'],'false');
 await context.toggleJournalAudio('note-1');assert.equal(instances.length,1);assert.equal(instances[0].paused,false);
 await context.toggleJournalAudio('note-2');assert.equal(instances[0].paused,true);assert.equal(instances[0].src,'');assert.equal(buttons[1].attributes['aria-pressed'],'true');
 instances[1].ended=true;instances[1].onended();assert.equal(statuses[1].textContent,'Recording finished');assert.equal(buttons[1].attributes['aria-pressed'],'false');
 context.stopJournalAudio();assert.equal(instances[1].paused,true);assert.equal(buttons[1].attributes['aria-pressed'],'false');
 playMode='reject';await context.toggleJournalAudio('note-1');assert.match(statuses[0].textContent,/Recording could not play/);assert.match(buttons[0].attributes['aria-label'],/^Play recording/);
 context.stopJournalAudio();playMode='deferred';const pending=context.toggleJournalAudio('note-1');const last=instances.at(-1);context.stopJournalAudio();lateResolve();await pending;assert.equal(last.paused,true);assert.equal(buttons[0].attributes['aria-pressed'],'false');
 const count=instances.length;await context.toggleJournalAudio('text-only');assert.equal(instances.length,count);assert.match(vm.runInContext('journalAudioControls(journal[2])',context),/disabled/);
 assert.equal(typeof listeners.pagehide,'function');
 const app=fs.readFileSync('static/app.js','utf8');for(const name of ['navigate','openNote','openWrite','lockAccess','startRecording'])assert.match(app,new RegExp('function '+name+'\\([^)]*\\) \\{\\s*(?:clearNoteNotice\\(\\);\\s*)?stopJournalAudio\\(\\)'));
 const result={source_checks_passed:10,browser_execution:false,checks:['accessible real button','play actual audio URL','pause and resume one source','stop prior recording on next play','ended state','stop lifecycle cleanup','inline playback failure and retry control','late-play race cancelled','typed note has no playback','navigation dialog access recording and pagehide hooks']};fs.mkdirSync('data/journal-audio-qa',{recursive:true});fs.writeFileSync('data/journal-audio-qa/source-results.json',JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result));
})().catch(error=>{console.error(error);process.exitCode=1});
