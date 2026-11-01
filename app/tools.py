"""Small auditable tools. Approval is never a model-supplied boolean."""
import hashlib, io, json, os, re
from datetime import datetime, timedelta
from decimal import Decimal
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo
import yaml
from dateutil.relativedelta import relativedelta
from app.store import LOCK, Store, allowed_recipient, now

ROOT=Path(__file__).resolve().parents[1]
PERSONA=json.loads((ROOT/'fixtures/persona.json').read_text())
PRIVATE_WORDS=['cancer','uclh','macmillan','hospital','treatment','chemotherapy','chemo','radiotherapy','oncology','diagnosis','diagnosed','tumour','tumor','nhs','clinic','medical','patient']

def live(): return os.getenv('APP_MODE','local')=='live'

def extract_attendance(text):
    specs={'appointment':('Appointment attended:',True),'hospital':('Hospital:',False),
           'department':('Department:',False),'next_appointment':('Next appointment:',True)}
    result={}
    if 'SYNTHETIC' not in text.upper(): raise ValueError('Synthetic emails only')
    for name,(prefix,is_date) in specs.items():
        matches=[(i,l) for i,l in enumerate(text.splitlines(),1) if l.strip().startswith(prefix)]
        if len(matches)!=1: raise ValueError('Missing or ambiguous '+name)
        line,quote=matches[0]; value=quote.strip()[len(prefix):].strip()
        if is_date: value=datetime.strptime(value,'%Y-%m-%d %H:%M').replace(tzinfo=ZoneInfo('Europe/London')).isoformat()
        if not value: raise ValueError('Empty '+name)
        result[name]={'value':value,'line':line,'quote':quote,'source':'/api/email'}
    if datetime.fromisoformat(result['next_appointment']['value'])<=datetime.fromisoformat(result['appointment']['value']):
        raise ValueError('Next appointment must follow attendance')
    return result

def poll_attendance(store):
    if live():
        from app.integrations import poll_gmail
        text,id=poll_gmail()
    else: text=(ROOT/'fixtures/attendance.txt').read_text(); id='synthetic-attendance-001'
    extracted=extract_attendance(text)
    store.put('email',{'id':id,'text':text}); store.put('attendance',extracted)
    return extracted

def calendar_event(store,attendance):
    uid=hashlib.sha256(attendance['next_appointment']['value'].encode()).hexdigest()[:32]
    if store.get('calendar'): return store.get('calendar')
    appointment=datetime.fromisoformat(attendance['next_appointment']['value'])
    start=appointment-timedelta(minutes=PERSONA['travel_minutes']); end=appointment+timedelta(hours=1)
    if live():
        from app.integrations import calendar_create
        id=calendar_create(uid,start.isoformat(),end.isoformat(),attendance['hospital']['value'])
        result={'mode':'Google Calendar','event_id':id,'travel_minutes':50,'appointment':appointment.isoformat()}
    else:
        fmt=lambda t:t.astimezone(ZoneInfo('UTC')).strftime('%Y%m%dT%H%M%SZ')
        ics='\r\n'.join(['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Pocket Ally//Synthetic Demo//EN','BEGIN:VEVENT',f'UID:{uid}@pocketally.test',f'DTSTAMP:{fmt(datetime.now(ZoneInfo("UTC")))}',f'DTSTART:{fmt(start)}',f'DTEND:{fmt(end)}','SUMMARY:Personal appointment + travel','LOCATION:'+attendance['hospital']['value'],'DESCRIPTION:Planning estimates: 50 minute travel buffer and 60 minute appointment.','END:VEVENT','END:VCALENDAR',''])
        path=store.root/'next-appointment.ics'; path.write_text(ics)
        result={'mode':'ICS export only - not added to Google','path':str(path),'url':'/api/calendar.ics','travel_minutes':50,'appointment':appointment.isoformat()}
    store.put('calendar',result); return result

def claim_deadline(payment_date):
    return (datetime.fromisoformat(payment_date).date()+relativedelta(months=3)).isoformat()

def load_trust(trust_id=None):
    trust_id=os.getenv('TRUST_ID','uclh') if trust_id is None else trust_id
    if not isinstance(trust_id,str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',trust_id):
        raise ValueError('Invalid trust identifier')
    directory=(ROOT/'config/trusts').resolve()
    path=(directory/f'{trust_id}.yaml').resolve()
    if path.parent!=directory: raise ValueError('Invalid trust path')
    try: adapter=yaml.safe_load(path.read_text())
    except (OSError,yaml.YAMLError) as exc: raise ValueError('Trust configuration unavailable or invalid') from exc
    if not isinstance(adapter,dict) or adapter.get('id')!=trust_id or not isinstance(adapter.get('name'),str):
        raise ValueError('Invalid trust configuration')
    if not isinstance(adapter.get('destination_env'),str) or not re.fullmatch(r'TEST_[A-Z0-9_]+_EMAIL',adapter['destination_env']):
        raise ValueError('Trust destination must use a configured test email variable')
    documents=adapter.get('required_documents')
    supported={'attendance','entitlement','travel','claim_form'}
    if not isinstance(documents,list) or not documents or any(not isinstance(document,str) or document not in supported for document in documents) or len(set(documents))!=len(documents):
        raise ValueError('Invalid trust required_documents')
    return adapter

def evidence_checklist(store,claim_exists=False,trust_id=None):
    adapter=load_trust(trust_id)
    claim_label=adapter.get('claim_form_label',f"HC5(T) draft - {adapter['id'].upper()} form still needs verification")
    return [{'id':k,'label':{'attendance':'Proof of attendance','entitlement':'Proof of entitlement','travel':'Proof of travel','claim_form':claim_label}[k],
             'present':claim_exists if k=='claim_form' else (ROOT/f'fixtures/evidence/{k}.txt').exists(),
             'synthetic':True} for k in adapter['required_documents']]

def fill_claim(store,attendance):
    from pypdf import PdfReader,PdfWriter
    from reportlab.pdfgen.canvas import Canvas
    reader=PdfReader(ROOT/'fixtures/HC5-T.pdf'); writer=PdfWriter(); writer.clone_document_from_reader(reader)
    day=datetime.fromisoformat(attendance['appointment']['value'])
    values={'Surname':PERSONA['surname'],'Other names':PERSONA['first_name'],'Address':PERSONA['address'],
            'Part 1 post code':PERSONA['postcode'],'Email address':PERSONA['email'],
            'Refund amount':str(Decimal(PERSONA['travel_paid'])),'Visit amount 1':PERSONA['travel_paid'],
            'date 1 - day':day.strftime('%d'),'date 1 - month':day.strftime('%m'),'date 1 - year':day.strftime('%Y'),
            'Department attended':attendance['department']['value'],'Name':attendance['hospital']['value']}
    if not set(values)<=set(reader.get_fields()): raise ValueError('Official PDF fields changed; mapping must be reviewed')
    writer.update_page_form_field_values(None,values,auto_regenerate=False)
    for page in writer.pages:
        buf=io.BytesIO(); cv=Canvas(buf,pagesize=(float(page.mediabox.width),float(page.mediabox.height)))
        cv.setFillColorRGB(.55,.12,.12); cv.setFont('Helvetica-Bold',9)
        cv.drawString(28,float(page.mediabox.height)-18,'SYNTHETIC DEMO DRAFT - NOT FOR SUBMISSION - BANK DETAILS LEFT BLANK')
        cv.save(); buf.seek(0); page.merge_page(PdfReader(buf).pages[0])
    path=store.root/'hc5-draft.pdf'
    with path.open('wb') as f: writer.write(f)
    saved=PdfReader(path); reopened=saved.get_fields()
    for k,v in values.items():
        if reopened[k].get('/V')!=v: raise ValueError('PDF field verification failed')
    bank=[k for k in reopened if any(t in k.lower() for t in ['account','sort code','bank'])]
    if any(reopened[k].get('/V') for k in bank): raise ValueError('Bank fields must be empty')
    unsigned=[k for k in reopened if any(term in k.lower() for term in ('signature','signture')) or k in ('Name in capitals','Step 2 Name in capitals','Authorisation')]
    if any(reopened[k].get('/V') for k in unsigned): raise ValueError('Signatures and declarations must be blank')
    if any(field.get('/V') not in (None,'','/Off') for field in reopened.values() if field.get('/FT')=='/Btn'):
        raise ValueError('Eligibility and declaration checkboxes must remain unchecked')
    for page in saved.pages:
        for annotation in page.get('/Annots',[]):
            widget=annotation.get_object()
            if widget.get('/FT')=='/Btn' and widget.get('/AS') not in (None,'/Off'):
                raise ValueError('Eligibility and declaration checkbox appearances must remain unchecked')
    result={'path':str(path),'url':'/api/claim.pdf','deadline':claim_deadline(PERSONA['payment_date']),
            'deadline_basis':'Three calendar months from synthetic payment date '+PERSONA['payment_date'],
            'estimate':f'£{Decimal(PERSONA["travel_paid"]):.2f} estimate - synthetic receipt, subject to verification',
            'fare_estimate':'[estimate pending]','refund_status':'refund not yet confirmed',
            'bank_notice':'Bank details are never collected or stored. UCLH will ask directly.',
            'pending_fields':['Date of birth (ambiguous PDF field names)','Signature and declaration','Eligibility verification','UCLH postal form verification'],
            'checklist':evidence_checklist(store,True),'field_map':{'first_name':'Other names','surname':'Surname'},'bank_fields':bank}
    store.put('claim',result); return result

def prepare_claim_email(store,trust_id=None):
    adapter=load_trust(trust_id)
    claim=store.get('claim')
    if not claim or not all(x['present'] for x in evidence_checklist(store,True,adapter['id'])): raise ValueError('Missing claim evidence')
    attachments=[claim['path']]+[str(ROOT/f'fixtures/evidence/{k}.txt') for k in adapter['required_documents'] if k!='claim_form']
    evidence=', '.join(k for k in adapter['required_documents'] if k!='claim_form')
    description=('synthetic '+evidence+' evidence and ' if evidence else '')+'an unsigned HC5(T) draft'
    return store.draft('claim',os.getenv(adapter['destination_env'],'uclh@example.test'),'SYNTHETIC DEMO - travel claim draft',
                       f'Test inbox only. Attached are {description}. Not a valid claim. Bank details are intentionally omitted. Refund not yet confirmed.',attachments)

def ingest_diary(store):
    notes=json.loads((ROOT/'fixtures/voice/notes.json').read_text())
    if live():
        from app.integrations import transcribe,embed
        from app.vector import VectorStore
        vector=VectorStore()
    for note in notes:
        existing=next((n for n in store.notes() if n['id']==note['id']),None)
        if existing and (not live() or existing.get('transcription_mode')=='gpt-4o-transcribe'): continue
        n=dict(note); path=ROOT/'fixtures/voice'/note['audio']
        n['audio_path']=str(path); n['transcription_mode']='fixture transcript (not live transcription)'
        if live():
            if not path.exists(): raise ValueError('Synthetic recording missing')
            n['transcript']=transcribe(path); n['transcription_mode']='gpt-4o-transcribe'
            vector.upsert(n,embed(n['transcript']))
        store.add_note(n)
    return {'count':len(store.notes()),'mode':'OpenAI transcription + Postgres pgvector' if live() else 'Fixture transcripts + local keyword retrieval'}

def retrieve_diary(store,question):
    if question!='How do you manage stairs and walking?': raise ValueError('This demo supports the single walking/stairs question only')
    if live():
        from app.vector import VectorStore
        from app.integrations import embed
        matches=VectorStore().search(embed(question),2)
        known={note['id']:note for note in store.notes()}
        # A shared database cannot introduce a different person's or stale source.
        return [known[n['id']] for n in matches if isinstance(n,dict) and n.get('id') in known and n==known[n['id']]]
    words={'stairs','walking','walked','handrail','landing','station','bench'}
    ranked=sorted(store.notes(),key=lambda n:len(set(re.findall(r'\w+',n['transcript'].lower()))&words),reverse=True)
    return [n for n in ranked if set(re.findall(r'\w+',n['transcript'].lower()))&words][:2]

def cited_answer(store,question):
    notes=retrieve_diary(store,question)
    if not notes: raise ValueError('No diary evidence found')
    sentences=[]
    for n in notes:
        for text in re.findall(r'[^.!?]+[.!?]?',n['transcript']):
            text=text.strip()
            if text: sentences.append({'text':text,'note_id':n['id'],'date':n['timestamp'][:10],'source':'/api/notes/'+n['id']})
    result={'question':question,'sentences':sentences,'method':'Extractive draft - source wording retained; review before using on a form.'}
    store.put('answer',result); return result

def assert_private(text):
    if any(re.search(r'\b'+re.escape(term)+r'\b',text,re.I) for term in PRIVATE_WORDS):
        raise ValueError('Employer draft contains a forbidden disclosure term')

def draft_employer(store,attendance):
    note=next((n for n in store.notes() if 'personal appointments' in n['transcript'].lower() and 'manager' in n['transcript'].lower()),None)
    if not note: raise ValueError('No verified manager disclosure fact in diary')
    date=datetime.fromisoformat(attendance['next_appointment']['value']).strftime('%A %d %B at %H:%M')
    subject='Time away for a personal appointment'
    body=f'Hi Sam,\n\nAs I mentioned, I need time away for personal appointments. My next appointment is on {date}. Could we arrange cover for that afternoon?\n\nThanks,\nAde'
    assert_private(subject+' '+body)
    return store.draft('employer',os.getenv('TEST_EMPLOYER_EMAIL','manager@example.test'),subject,body,[],source_note=note['id'])

def send_message(store,id):
    with LOCK:
        with store.connect() as c:
            row=c.execute('SELECT payload,approved,result,sending,obsolete FROM drafts WHERE id=?',(id,)).fetchone()
            if not row: raise ValueError('Unknown draft')
            if row[4]: raise PermissionError('This draft was superseded; review the current case draft')
            p=json.loads(row[0]); allowed_recipient(p['recipient'])
            if row[2]: return json.loads(row[2])
            if row[3]: raise PermissionError('Delivery uncertain or in progress; inspect mailbox before retrying')
            if row[1]!=p['digest']: raise PermissionError('Explicit approval of the unchanged draft is required')
            try: attachment_bytes=Store.attachment_bytes(p)
            except OSError as exc: raise PermissionError('Attachment unavailable; review the draft again') from exc
            if Store.digest(p,attachment_bytes)!=p['digest']: raise PermissionError('Explicit approval of the unchanged draft is required')
            if p['kind']=='employer': assert_private(p['subject']+' '+p['body'])
            changed=c.execute('UPDATE drafts SET sending=1 WHERE id=? AND sending=0 AND result IS NULL',(id,)).rowcount
            if changed!=1: raise PermissionError('Delivery already claimed; inspect mailbox before retrying')
        msg=EmailMessage(); msg['To']=p['recipient']; msg['From']=os.getenv('TEST_INBOX_EMAIL') if live() else 'ade@example.test'; msg['Subject']=p['subject']
        msg['Message-ID']=f'<{id}@pocketally.test>'; msg.set_content(p['body'])
        for filename,content in zip(p['attachments'],attachment_bytes):
            path=Path(filename)
            msg.add_attachment(content,maintype='application',subtype='pdf' if path.suffix=='.pdf' else 'octet-stream',filename=path.name)
        if live():
            from app.integrations import gmail_send
            result={'delivery':'Gmail test inbox','message_id':gmail_send(msg),'at':now()}
        else:
            outbox=store.root/'outbox'; outbox.mkdir(exist_ok=True); (outbox/(id+'.eml')).write_bytes(msg.as_bytes())
            result={'delivery':'local outbox only','download':'/api/outbox/'+id,'at':now()}
        with store.connect() as c: c.execute('UPDATE drafts SET result=?,sending=0 WHERE id=?',(json.dumps(result),id))
        store.event('sent',p['kind'],'done',result['delivery']); return result

def status_screen(store):
    from app import journal,companion,cases
    drafts=store.drafts();notes=journal.entries(store)
    appointment=store.get('attendance',{}).get('next_appointment')
    dashboard={'journal_count':len(notes),'pending_transcripts':sum(note['transcript_pending'] for note in notes),
               'drafts_awaiting_review':sum(not draft['result'] for draft in drafts),
               'completed_tasks':sum(bool(draft['result']) for draft in drafts),
               'next_appointment':appointment,'summary':'Your synthetic paperwork and journal are saved on this demo server.'}
    registry=cases.list_cases(store)
    current=next((case for case in registry['cases'] if case['id']==registry['current_case_id']),None)
    if current and current.get('appointment'): dashboard['next_appointment']={'value':current['appointment'],'source':'/api/cases/'+current['id']}
    return {'mode':'live integrations' if live() else 'synthetic task demo',
            'delivery_mode':'gmail-test' if live() else 'local-outbox','refund_status':'refund not yet confirmed',
            'attendance':store.get('attendance'),'calendar':store.get('calendar'),'claim':store.get('claim'),
            'diary':store.get('diary'),'answer':store.get('answer'),'drafts':store.drafts(),'events':store.events(),
            'phase':store.get('phase','ready'),'error':store.get('error'),'mascot':store.get('mascot','idle'),
            'dashboard':dashboard,'journal_count':len(notes),'companion':companion.state(store),
            'current_case_id':registry['current_case_id'],'current_case':current,'cases':registry['cases'],
            'capabilities':{'editable_messages':True,'semantic_retrieval':True,'tfl_journey_planning':True,'generated_examples':True}}
