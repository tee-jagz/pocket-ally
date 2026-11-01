"""Synthetic journal data stays separate from task evidence and send authority."""
import json,os,re,secrets
from datetime import datetime,timezone
from pathlib import Path
from app.store import now
from app.tools import ROOT

MAX_AUDIO_BYTES=10*1024*1024
AUDIO_TYPES={'audio/webm':'.webm','audio/mp4':'.mp4','audio/wav':'.wav','audio/ogg':'.ogg'}

def fixture_entries(store):
    rows=json.loads((ROOT/'fixtures/voice/notes.json').read_text())
    known={note['id']:note for note in store.notes()}
    rows=[{**note,'transcript':known.get(note['id'],note)['transcript'],
           'timestamp':known.get(note['id'],note)['timestamp']} for note in rows]
    return [{**note,'title':'Synthetic diary '+note['id'].split('-')[-1],
             'audio_path':str(ROOT/'fixtures/voice'/note['audio']),
             'audio_mime':'audio/wav','source':'fixture',
             'transcription_mode':'fixture transcript','transcript_pending':False} for note in rows]

def raw_entries(store):
    with store.connect() as connection:
        rows=[json.loads(row[0]) for row in connection.execute('SELECT payload FROM journal ORDER BY id')]
    return fixture_entries(store)+rows

def entry(store,id):
    found=next((note for note in raw_entries(store) if note['id']==id),None)
    if not found: raise LookupError('Journal entry not found')
    with store.connect() as connection:
        links=[row[0] for row in connection.execute('SELECT task FROM journal_links WHERE note_id=? ORDER BY task',(id,))]
    return {key:value for key,value in found.items() if key not in ('audio_path','audio_mime','audio')} | {
        'audio_url':'/api/notes/'+id+'/audio' if found.get('audio_path') else None,
        'linked_tasks':links}

def entries(store):
    return sorted((entry(store,note['id']) for note in raw_entries(store)),key=lambda note:note['timestamp'],reverse=True)

def save(store,note):
    with store.connect() as connection:
        connection.execute('INSERT OR REPLACE INTO journal VALUES (?,?)',(note['id'],json.dumps(note)))
    return entry(store,note['id'])

def create_text(store,transcript,title=''):
    note={'id':'journal-'+secrets.token_hex(12),'title':title.strip() or 'Synthetic journal note',
          'timestamp':now(),'transcript':transcript.strip(),'source':'journal',
          'transcription_mode':'typed note','transcript_pending':False}
    return save(store,note)

def validate_audio(content,mime):
    if len(content)>MAX_AUDIO_BYTES: raise OverflowError('Recording must be 10 MiB or smaller')
    valid={'audio/webm':content.startswith(b'\x1aE\xdf\xa3'),
           'audio/mp4':len(content)>=12 and content[4:8]==b'ftyp',
           'audio/wav':content.startswith(b'RIFF') and content[8:12]==b'WAVE',
           'audio/ogg':content.startswith(b'OggS')}
    if mime not in AUDIO_TYPES or not valid.get(mime): raise ValueError('Supported audio container required')

def create_audio(store,content,mime,duration,title=''):
    validate_audio(content,mime)
    id='journal-'+secrets.token_hex(12)
    directory=store.root/'journal';directory.mkdir(exist_ok=True)
    path=directory/(id+AUDIO_TYPES[mime]);path.write_bytes(content);path.chmod(0o600)
    note={'id':id,'title':title.strip() or 'Synthetic voice note','timestamp':now(),
          'transcript':'','source':'journal','audio_path':str(path),'audio_mime':mime,
          'duration_seconds':duration,'transcription_mode':'transcript pending: add a typed transcript',
          'transcript_pending':True}
    if os.getenv('OPENAI_API_KEY'):
        try:
            from app.integrations import transcribe
            text=transcribe(path).strip()
            if not text: raise ValueError('Empty transcription')
            note.update(transcript=text,transcription_mode='gpt-4o-transcribe',transcript_pending=False)
        except Exception:
            note['transcription_mode']='transcript pending: provider unavailable; add a typed transcript'
    return save(store,note)

def update_transcript(store,id,transcript):
    note=next((note for note in raw_entries(store) if note['id']==id),None)
    if not note: raise LookupError('Journal entry not found')
    if note['source']=='fixture': raise PermissionError('Synthetic fixture sources are read-only')
    note.update(transcript=transcript.strip(),transcript_pending=False,transcription_mode='manual transcript')
    return save(store,note)

def link(store,id,task):
    entry(store,id)
    with store.connect() as connection:
        connection.execute('INSERT OR IGNORE INTO journal_links VALUES (?,?)',(id,task))
    return entry(store,id)

def recall(store,question):
    stop={'a','an','and','are','at','did','do','for','from','how','i','in','is','it','me','my','of','on','the','to','was','what','when','where','with','you'}
    words=set(re.findall(r'\w+',question.lower()))-stop
    # This is evidence retrieval, never a medical answering model.
    clinical=bool(re.search(r'\b(diagnos\w*|prescrib\w*|dosage|medication|medicine|treat\w*|cure|cancer)\b',question,re.I))
    result={'question':question,'sentences':[],'method':'Extractive journal recall. Source wording retained; no advice or new facts.','clinical_advice':False}
    if clinical:
        result['method']='Journal recall cannot provide clinical advice. Ask about something recorded in your synthetic notes.'
        return result
    from app import retrieval
    notes=[note for note in raw_entries(store) if note.get('transcript') and datetime.fromisoformat(note['timestamp'])<=datetime.now(timezone.utc)]
    ranked,metadata=retrieval.rank(store,question,notes,limit=3)
    result['retrieval']=metadata
    matched=[]
    for row in ranked:
        note=row['note']
        for sentence in re.findall(r'[^.!?]+[.!?]?',note['transcript']):
            sentence=sentence.strip();score=len(words & set(re.findall(r'\w+',sentence.lower())))
            if score or metadata['mode']=='openai-embeddings':
                matched.append((row['score'],note['timestamp'],{'text':sentence,'note_id':note['id'],'date':note['timestamp'][:10],'source':'/api/notes/'+note['id']}))
    result['sentences']=[row[2] for row in sorted(matched,key=lambda row:(row[0],row[1]),reverse=True)[:6]]
    if not result['sentences']: result['method']='No matching journal evidence found. Try words used in a saved transcript.'
    return result
