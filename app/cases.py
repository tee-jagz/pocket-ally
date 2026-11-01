"""Replayable synthetic source events, bounded preparation tools and durable cases."""
import asyncio,copy,hashlib,json,os,re
from datetime import datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from app.store import Store,LOCK,now
from app import journal,tools as t

SCENARIOS=[
 {'id':'checkup-email','title':'A check-in email','description':'Prepare a nonclinical summary from dated notes.',
  'event':{'id':'synthetic-checkup-001','visit_id':'visit-next-001','type':'checkup-email','timestamp':'2026-11-01T10:00:00+00:00','synthetic':True,
           'text':'SYNTHETIC DEMO. Dear patient, how have you been this past week? Have you noticed any changes in how you are feeling or managing day to day?'}},
 {'id':'confirmed-visit','title':'An appointment is confirmed','description':'Plan the visit using relevant diary context.',
  'event':{'id':'synthetic-confirmed-001','visit_id':'visit-next-001','type':'confirmed-visit','timestamp':'2026-11-01T11:00:00+00:00','synthetic':True,
           'appointment':'2026-11-11T14:00:00+00:00','hospital':'UCLH Macmillan Cancer Centre','department':'Outpatient services',
           'text':'SYNTHETIC appointment confirmed: 11 November 2026 at 14:00 at UCLH Macmillan Cancer Centre, Outpatient services. Plan travel and bring your own observations about walking and stairs. Keep employer details private.'}},
 {'id':'attended-visit','title':'A visit has been attended','description':'Prepare claim evidence and find the missing travel receipt.',
  'event':{'id':'synthetic-attended-001','visit_id':'visit-attended-001','type':'attended-visit','timestamp':'2026-10-28T12:00:00+00:00','synthetic':True,
           'appointment':'2026-10-28T10:30:00+00:00','hospital':'UCLH Macmillan Cancer Centre','department':'Outpatient services','attended':True,'receipt_available':False,
           'text':'SYNTHETIC attendance confirmation: attended on 28 October 2026 at 10:30. Attendance and entitlement evidence are available. A travel receipt is still missing. Please prepare the unsigned claim paperwork and explain what is missing; no refund or eligibility is confirmed.'}},
 {'id':'reschedule','title':'The same appointment changes','description':'Update the existing visit instead of creating a duplicate.',
  'event':{'id':'synthetic-reschedule-001','visit_id':'visit-next-001','type':'reschedule','timestamp':'2026-11-02T09:00:00+00:00','synthetic':True,
           'appointment':'2026-11-13T14:00:00+00:00','hospital':'UCLH Macmillan Cancer Centre','department':'Outpatient services',
           'text':'SYNTHETIC appointment rescheduled. The SAME visit previously booked for 11 November is now 13 November 2026 at 14:00. Replace the old plan, do not create another visit. Review relevant travel and day-to-day notes again.'}}
]

def catalogue(): return {'scenarios':copy.deepcopy(SCENARIOS)}

def scenario(id):
    found=next((row for row in SCENARIOS if row['id']==id),None)
    if not found: raise LookupError('Scenario not found')
    return copy.deepcopy(found)

def get_case(store,id):
    with store.connect() as connection: row=connection.execute('SELECT payload FROM cases WHERE id=?',(id,)).fetchone()
    if not row: raise LookupError('Case not found')
    return json.loads(row[0])

def save_case(store,case):
    case['updated_at']=now()
    with store.connect() as connection:
        connection.execute('INSERT OR REPLACE INTO cases VALUES (?,?)',(case['id'],json.dumps(case)))

def list_cases(store):
    with store.connect() as connection: rows=[json.loads(row[0]) for row in connection.execute('SELECT payload FROM cases')]
    return {'cases':sorted(rows,key=lambda row:row['updated_at'],reverse=True),'current_case_id':store.get('current_case_id')}

def register_event(store,event):
    if event.get('synthetic') is not True or not re.fullmatch(r'[a-z0-9-]+',event['visit_id']): raise ValueError('A synthetic visit identifier is required')
    if datetime.fromisoformat(event['timestamp']).tzinfo is None: raise ValueError('Source timestamp requires an explicit timezone')
    if event.get('appointment') and datetime.fromisoformat(event['appointment']).tzinfo is None: raise ValueError('Appointment requires an explicit timezone')
    fingerprint=hashlib.sha256(json.dumps(event,sort_keys=True).encode()).hexdigest()
    id='case-'+event['visit_id']
    with LOCK:
        with store.connect() as connection:
            old=connection.execute('SELECT fingerprint,status FROM case_events WHERE id=?',(event['id'],)).fetchone()
        try: case=get_case(store,id)
        except LookupError:
            case={'id':id,'visit_id':event['visit_id'],'status':'ready','revision':0,'events':[],
                  'decision':{'mode':'agents-sdk' if os.getenv('OPENAI_API_KEY') else 'offline-scripted','summary':'','tool_calls':[]},
                  'context':[],'actions':[],'missing_evidence':[],'draft_ids':[],'runs':[],'updated_at':now()}
        store.put('current_case_id',id)
        if old and old[0]!=fingerprint: raise ValueError('Source event changed; use a distinct event identifier')
        if old and (old[1]=='running' or (old[0]==fingerprint and old[1]=='ready')):
            return {'case_id':id,'event_id':event['id'],'status':case['status'],'replayed':True,'_run':False}
        if case['status']=='running': raise ValueError('This visit already has an event running; reopen it first')
        if not old or old[0]!=fingerprint:
            store.invalidate_case_drafts(id)
            case['revision']+=1
            case['events'].append({**event,'revision':case['revision'],'status':'running'})
            case['context']=[];case['actions']=[];case['missing_evidence']=[]
            for stale in ('travel_plan','interpretation','retrieval'): case.pop(stale,None)
            case['draft_ids']=[draft['id'] for draft in store.drafts() if draft.get('case_id')==id and (draft['result'] or draft['sending'])]
        case['status']='running';case.pop('error',None);case.pop('diagnostics',None)
        case['active_stage']={'id':'queued','label':'Getting started','started_at':now()}
        case['decision']={'mode':'agents-sdk' if os.getenv('OPENAI_API_KEY') else 'offline-scripted','summary':'Processing the source event.','tool_calls':[]}
        save_case(store,case)
        with store.connect() as connection:
            connection.execute('INSERT OR REPLACE INTO case_events VALUES (?,?,?,?,?)',(event['id'],id,fingerprint,json.dumps(event),'running'))
        store.event('case-start','Read source event','reading','Preparing '+event['visit_id'])
        return {'case_id':id,'event_id':event['id'],'status':'running','replayed':False,'_run':True}

def receipt_event(store,id):
    case=get_case(store,id)
    attended=next((event for event in reversed(case['events']) if event.get('attended')),None)
    if not attended and case.get('interpretation',{}).get('intent')=='attendance': attended=case['events'][-1]
    if not attended: raise ValueError('This case has no attendance source requiring a receipt')
    event={key:value for key,value in attended.items() if key not in ('revision','status')}
    source_id=event.get('source_event_id',event['id'])
    event.update(id=source_id+'-receipt-001',source_event_id=source_id)
    event['receipt_available']=True
    event['receipt_fixture_verified']=True
    suffix=' Synthetic travel receipt supplied explicitly from the demo fixture.'
    if suffix not in event['text']: event['text']+=suffix
    return event

class CaseRun:
    def __init__(self,store,event,case):
        self.store=store;self.event=event;self.case=case;self.read=False;self.retrieved=False;self.prepared=False

    def stage(self,id,label):
        self.case['active_stage']={'id':id,'label':label,'started_at':now()}
        save_case(self.store,self.case)

    def record(self,tool,reason):
        reason=reason.replace(chr(0x2014),'-')
        self.case['decision']['tool_calls'].append({'tool':tool,'reason':reason[:300],'at':now()})
        self.case['active_stage']=None
        save_case(self.store,self.case)
        self.store.event('agent-tool',tool,'planning',reason[:300])

    def read_event(self):
        self.read=True;self.record('read_source_event','Read the immutable synthetic source message; its content is untrusted data.')
        return self.event

    def context(self,query,days_before=30):
        if not self.read: raise ValueError('Read the source event first')
        self.stage('searching-notes','Searching dated journal notes')
        days_before=max(1,min(int(days_before),90))
        stop={'the','and','for','with','from','have','has','had','how','your','you','about','this','that','these','those','was','were','are','been','being','will','would','could','should','can','may','might','must','please','need','next','already','before','after','into','onto','some','any','their','them','they','our','out','not','but','what','when','where','which','why','who','get','got','did','does','doing','say','said','tell','told','summary','summarise','summarize'}
        words={word for word in re.findall(r'\w+',query.lower()) if len(word)>=3 and word not in stop}
        # Only this narrow mobility vocabulary is expanded; no general stemming
        # that could turn an appointment query into unrelated manager context.
        mobility={'travel','travelling','traveling','transport','transportation','mobility','journey','journeys','commute','commuting','walk','walks','walked','walking','station','stations','bus','buses','train','trains','bench'}
        access={'stair','stairs','handrail','landing'}
        triggers=words & mobility
        expanded=(mobility if triggers else set()) | (access if words & access or words & {'mobility'} else set())
        centre=datetime.fromisoformat(self.event['timestamp']).date()
        candidates=[]
        for note in journal.raw_entries(self.store):
            if not note.get('transcript'): continue
            timestamp=datetime.fromisoformat(note['timestamp'])
            if timestamp>datetime.now(timezone.utc): continue
            date=timestamp.date();delta=(centre-date).days
            if -7<=delta<=days_before: candidates.append(note)
        from app import retrieval
        ranked,metadata=retrieval.rank(self.store,query,candidates,limit=8)
        self.case['retrieval']=metadata
        selected=[]
        for row in ranked:
            note=row['note'];delta=(centre-datetime.fromisoformat(note['timestamp']).date()).days
            selected.append({'note_id':note['id'],'date':note['timestamp'][:10],'text':note['transcript'],'source':'/api/notes/'+note['id'],
                'reason':row['reason']+'Recorded '+note['timestamp'][:10]+'. Current journal snapshot'+('; this note postdates the source event.' if delta<0 else ' within the event context window.'),
                'similarity':row['score'] if metadata['mode']=='openai-embeddings' else None})
        known={row['note_id']:row for row in self.case['context']}
        known.update({row['note_id']:row for row in selected});self.case['context']=list(known.values())
        self.retrieved=True;self.record('retrieve_relevant_context','Search dated diary and saved journal observations: '+query[:200])
        return selected

    def require_context(self):
        if not self.read or not self.retrieved: raise ValueError('Read the event and retrieve relevant context before preparing anything')

    def is_complete(self):
        if not (self.read and self.retrieved and self.prepared): return False
        current=[action for action in self.case['actions'] if action['source_event_id']==self.event['id'] and action['event_revision']==self.case['revision']]
        kinds={action['kind'] for action in current}
        facts=self.event.get('interpretation')
        if not facts: return True
        if facts['missing_info']: return 'clarification' in kinds
        if facts['intent'] in ('appointment','reschedule'):
            travel=bool(re.search(r'\b(travel|journey|route|transport)\b',self.event['text'],re.I))
            return 'appointment-plan' in kinds and (not travel or 'journey-plan' in kinds)
        if facts['intent']=='attendance': return 'claim-pack' in kinds
        if facts['intent']=='checkup':
            from app.synthesis import wellbeing_gap
            gap=wellbeing_gap(self.event,self.case['context'])
            return 'wellbeing-summary' in kinds or (not self.case['context'] or gap is not None) and 'clarification' in kinds
        return 'clarification' in kinds

    def administrative_summary(self):
        facts=[]
        for action in self.case['actions']:
            if action['source_event_id']!=self.event['id'] or action['event_revision']!=self.case['revision']: continue
            if action['kind']=='wellbeing-summary': facts.append('Prepared an observations summary from '+str(len(action.get('observations',[])))+' dated journal sources.')
            elif action['kind']=='appointment-plan':
                date=datetime.fromisoformat(action['appointment']).strftime('%d %B %Y at %H:%M')
                facts.append('Prepared the same visit plan for '+date+'; a local calendar export is ready.')
            elif action['kind']=='claim-pack':
                if action['status']=='delivered': facts.append('Reopened this visit\'s delivered claim copy without creating another message.')
                else: facts.append('Prepared unsigned claim paperwork; refund and eligibility remain unconfirmed.')
            elif action['kind']=='employer-draft': facts.append('Prepared a private date-only manager draft for exact review.')
            elif action['kind']=='clarification': facts.append('More source details are needed before preparing the requested paperwork.')
            elif action['kind']=='journey-plan' and action['status']=='prepared': facts.append('Fetched TfL journey planning options for the supplied postcodes and arrival time; recheck before travelling.')
            elif action['kind']=='journey-plan': facts.append('A journey could not be confirmed; no route or departure time was invented.')
        if self.case['missing_evidence']:
            facts.append('Missing: '+', '.join(item['label'] for item in self.case['missing_evidence'])+'.')
            ids={item['id'] for item in self.case['missing_evidence']}
            if 'visit-target' in ids: facts.append('Select the existing visit and prepare the edited message again.')
            elif 'journal-context' in ids: facts.append('Add the missing observations in Journal, then send a follow-up.')
            elif ids=={'travel-receipt'}: facts.append('Add the synthetic receipt to resume this case.')
            else: facts.append('Complete the missing source or journey details and prepare again.')
        facts.append('Nothing was sent by this preparation run.')
        return ' '.join(facts)

    def action(self,kind,title,detail,reason,**extra):
        self.require_context()
        self.prepared=True
        item={'kind':kind,'title':title,'status':'prepared','detail':detail,'source_event_id':self.event['id'],
              'event_revision':self.case['revision'],**extra}
        self.case['actions']=[action for action in self.case['actions'] if action['kind']!=kind]+[item]
        self.record({'wellbeing-summary':'prepare_wellbeing_summary','appointment-plan':'prepare_appointment_plan','claim-pack':'prepare_claim_pack','employer-draft':'prepare_employer_email','clarification':'request_missing_information','journey-plan':'plan_tfl_journey'}[kind],reason)
        return item

    def cached_action(self,kind,tool,reason):
        cached=next((action for action in self.case['actions'] if action['kind']==kind and action['source_event_id']==self.event['id'] and action['event_revision']==self.case['revision']),None)
        if cached:
            self.prepared=True;self.record(tool,reason+' Reused the existing prepared result for this exact event revision.')
        return cached

    def wellbeing(self,reason,sentences=None):
        self.require_context()
        facts=self.event.get('interpretation',{})
        if facts.get('missing_info') and facts.get('intent')!='checkup': raise ValueError('Clarify missing source facts before preparing a wellbeing summary')
        cached=self.cached_action('wellbeing-summary','prepare_wellbeing_summary',reason)
        if cached: return cached
        observations=[{'text':source['text'],'date':source['date'],'source':source['source']} for source in self.case['context']]
        from app import synthesis
        gap=synthesis.wellbeing_gap(self.event,self.case['context'])
        if gap:
            self.case['missing_evidence']=[gap]
            return self.clarify('The retrieved sources do not cover how you felt over the requested week; a complete reply cannot be inferred from activities.')
        if sentences is not None:
            summary=synthesis.validate_sentences(sentences,self.case['context']);mode='agent-synthesis'
            if synthesis.asks_general_wellbeing(self.event) and not any(synthesis.reports_wellbeing(row['text']) for row in summary): raise ValueError('Answer the wellbeing question from explicit self-reports, not only a list of activities')
        else:
            summary=[{'text':source['text'],'source_ids':[source['note_id']],'sources':[{'note_id':source['note_id'],'date':source['date'],'source':source['source']}]} for source in self.case['context']]
            mode='offline-source-extract'
        reply=synthesis.reply_required(self.event);extra={}
        if reply and summary:
            draft=self.store.draft('checkin_reply',os.getenv('TEST_UCLH_EMAIL','uclh@example.test'),'SYNTHETIC DEMO - weekly update','Hello,\n\n'+('\n\n'.join(row['text'] for row in summary))+'\n\nSynthetic demonstration only.',[],case_id=self.case['id'],visit_id=self.case['visit_id'],event_id=self.event['id'],event_revision=self.case['revision'])
            self.add_draft(draft);extra['draft_id']=draft['id']
        return self.action('wellbeing-summary','Your check-in reply' if reply else 'Your check-in summary','A short cited synthesis for your review; no clinical interpretation.' if mode=='agent-synthesis' else 'Offline source extracts only. No model synthesis was generated.',reason,observations=observations,summary_mode=mode,summary_sentences=summary,reply_required=reply,**extra)

    def clarify(self,reason):
        self.require_context()
        from app.synthesis import wellbeing_gap
        gap=wellbeing_gap(self.event,self.case['context'])
        if gap: self.case['missing_evidence']=[gap]
        if not self.case['missing_evidence']:
            if self.event.get('interpretation',{}).get('intent')=='checkup' and not self.case['context']:
                self.case['missing_evidence']=[{'id':'journal-context','label':'Relevant dated notes needed','detail':'No matching notes were found in the requested time window. Add your own observations before preparing a grounded update; no reply was invented.'}]
            else: self.case['missing_evidence']=[{'id':'visit-intent','label':'Clarify the message','detail':'Edit the source message to explain what administrative help is needed.'}]
        missing_notes=any(item['id']=='journal-context' for item in self.case['missing_evidence'])
        return self.action('clarification','Add your journal observations' if missing_notes else 'A little more detail is needed','Add your own dated observations in Journal before preparing a grounded update.' if missing_notes else 'Edit this same source message with the missing information and prepare again for this visit.',reason,status='needs-information')

    def journey(self,reason):
        self.require_context()
        from app import tfl
        missing=[]
        for key,label in [('origin','Starting postcode needed'),('destination','Destination postcode needed')]:
            try: tfl.postcode(self.event.get(key,''))
            except ValueError: missing.append({'id':'route-'+key,'label':label,'detail':'Supply a complete synthetic UK postcode; no location will be invented.'})
        if not self.event.get('appointment'): missing.append({'id':'appointment-date','label':'Arrival date and time needed','detail':'Include a full date, year and time in the source message.'})
        if missing:
            known={item['id']:item for item in self.case['missing_evidence']};known.update({item['id']:item for item in missing});self.case['missing_evidence']=list(known.values())
            journey={'mode':'needs-information','source':'https://api.tfl.gov.uk','checked_at':now(),'query':{},'journeys':[],'notice':'Missing route details. No route or time was invented.'}
        else:
            self.stage('checking-travel','Checking TfL journey options')
            avoid=any(re.search(r'\b(stairs|handrail|step.free)\b',source['text'],re.I) for source in self.case['context'])
            journey=tfl.plan(self.event['origin'],self.event['destination'],self.event['appointment'],avoid_stairs=avoid)
            if journey['mode']=='tfl-live-response': self.case['travel_plan']=journey
            else: self.case.pop('travel_plan',None)
            if any(action['kind']=='appointment-plan' for action in self.case['actions']): self.appointment('Updated the same visit calendar from the current travel check; unavailable routes retain only a labelled travel estimate.')
        status='prepared' if journey['mode']=='tfl-live-response' else 'needs-information' if missing else 'unavailable'
        return self.action('journey-plan','Your journey options',journey['notice'],reason,status=status,journey=journey)

    def appointment(self,reason):
        self.require_context()
        if self.event.get('interpretation',{}).get('missing_info'): raise ValueError('Clarify missing source facts before preparing an appointment plan')
        previous=next((action for action in self.case['actions'] if action['kind']=='appointment-plan'),None)
        travel=self.case.get('travel_plan')
        appointment_date=datetime.fromisoformat(self.event.get('appointment','1900-01-01'))
        if travel and (travel.get('query',{}).get('date')!=appointment_date.strftime('%Y%m%d') or travel.get('query',{}).get('time')!=appointment_date.strftime('%H%M')): travel=None
        cache_matches=previous and previous.get('travel_checked_at')==(travel['checked_at'] if travel else None)
        cached=self.cached_action('appointment-plan','prepare_appointment_plan',reason) if cache_matches else None
        if cached: return cached
        if not self.event.get('appointment') or self.event.get('attended'): raise ValueError('A future appointment source is required')
        date=datetime.fromisoformat(self.event['appointment'])
        previous_appointment=previous.get('previous_appointment') if previous and previous.get('event_revision')==self.case['revision'] else self.case.get('appointment')
        is_reschedule=bool(self.event.get('interpretation',{}).get('intent')=='reschedule' or self.event.get('type')=='reschedule' or previous_appointment and previous_appointment!=date.isoformat())
        latest=max([event for event in self.case['events'] if event.get('appointment') and not event.get('attended')]+[self.event],key=lambda event:event['timestamp'])
        if latest['timestamp']>self.event['timestamp']: raise ValueError('An older source cannot overwrite the newer appointment')
        if self.case.get('appointment_source_timestamp','')>self.event['timestamp']: raise ValueError('An older source cannot overwrite the newer appointment')
        self.case['appointment']=date.isoformat()
        self.case['appointment_source_timestamp']=self.event['timestamp']
        uid=hashlib.sha256(self.case['visit_id'].encode()).hexdigest()[:32]
        start=date-timedelta(minutes=t.PERSONA['travel_minutes']);end=date+timedelta(hours=1)
        description='Unverified travel estimate: 50 minute travel buffer (no verified route selected). Appointment duration is a 60 minute estimate.'
        if travel and travel.get('journeys'):
            option=travel['journeys'][travel.get('selected_index',0)]
            departure=datetime.fromisoformat(option['departure'])
            if departure<date:
                start=departure
                description='Travel starts at the selected freshly fetched TfL planning departure; recheck before travelling. Appointment duration is a 60 minute estimate.'
        fmt=lambda value:value.astimezone(ZoneInfo('UTC')).strftime('%Y%m%dT%H%M%SZ')
        directory=self.store.root/'cases'/self.case['id'];directory.mkdir(parents=True,exist_ok=True)
        text='\r\n'.join(['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Pocket Ally//Synthetic Demo//EN','BEGIN:VEVENT','UID:'+uid+'@pocketally.test','DTSTAMP:'+fmt(datetime.now(ZoneInfo('UTC'))),'DTSTART:'+fmt(start),'DTEND:'+fmt(end),'SUMMARY:Personal appointment + travel','DESCRIPTION:'+description,'END:VEVENT','END:VCALENDAR',''])
        (directory/'appointment.ics').write_text(text)
        return self.action('appointment-plan','Your appointment plan',date.isoformat()+'. '+description+' This updates the same visit; export is not a Google Calendar booking.',reason,calendar_uid=uid,calendar_url='/api/cases/'+self.case['id']+'/calendar.ics',appointment=date.isoformat(),travel_checked_at=travel['checked_at'] if travel else None,travel_departure=start.isoformat(),is_reschedule=is_reschedule,previous_appointment=previous_appointment)

    def add_draft(self,draft):
        if draft['id'] not in self.case['draft_ids']: self.case['draft_ids'].append(draft['id'])
        return draft

    def employer(self,reason):
        self.require_context()
        cached=self.cached_action('employer-draft','prepare_employer_email',reason)
        if cached: return cached
        if not self.event.get('appointment') or self.event.get('attended'): raise ValueError('An appointment source is required')
        proof=next((source for source in self.case['context'] if 'personal appointments' in source['text'].lower() and 'manager' in source['text'].lower()),None)
        if not proof: raise ValueError('Retrieve the explicit manager disclosure fact first')
        date=datetime.fromisoformat(self.event['appointment']).strftime('%A %d %B at %H:%M')
        body=f'Hi Sam,\n\nAs I mentioned, I need time away for personal appointments. My next appointment is on {date}. Could we arrange cover for that afternoon?\n\nThanks,\nAde'
        subject='Time away for a personal appointment';t.assert_private(subject+' '+body)
        old=next((draft for draft in self.store.drafts() if draft.get('case_id')==self.case['id'] and draft['result'] and draft['subject']==subject and draft['body']==body),None)
        draft=old or self.store.draft('employer',os.getenv('TEST_EMPLOYER_EMAIL','manager@example.test'),subject,body,[],case_id=self.case['id'],visit_id=self.case['visit_id'],event_id=self.event['id'],event_revision=self.case['revision'],source_note=proof['note_id'])
        self.add_draft(draft)
        return self.action('employer-draft','A private manager note','Prepared only for exact user review; no medical details shared and nothing sent.',reason,draft_id=draft['id'])

    def claim(self,reason):
        self.require_context()
        if self.event.get('interpretation',{}).get('missing_info'): raise ValueError('Clarify missing source facts before preparing claim paperwork')
        self.stage('filling-paperwork','Preparing unsigned claim paperwork')
        cached=self.cached_action('claim-pack','prepare_claim_pack',reason)
        if cached: return cached
        if not self.event.get('attended') or not self.event.get('appointment'): raise ValueError('An explicit attendance source is required')
        delivered=next((draft for draft in self.store.drafts() if draft.get('case_id')==self.case['id'] and draft['kind']=='claim' and draft['result']),None)
        if delivered:
            self.add_draft(delivered);self.case['missing_evidence']=[]
            return self.action('claim-pack','Your existing delivered claim copy','This visit already has a delivered claim copy. Reopened that record without preparing another message. Refund and eligibility remain unconfirmed; corrections need separate review.',reason,status='delivered',draft_id=delivered['id'])
        directory=self.store.root/'cases'/self.case['id']/('revision-'+str(self.case['revision']))
        workspace=Store(directory)
        attendance={key:{'value':value} for key,value in {'appointment':self.event['appointment'],'hospital':self.event.get('hospital',''),'department':self.event.get('department','')}.items()}
        claim=workspace.get('claim')
        if not claim or not Path(claim['path']).exists(): claim=t.fill_claim(workspace,attendance)
        missing=[] if self.event.get('receipt_available') else [{'id':'travel-receipt','label':'Travel receipt missing','detail':'Add the synthetic receipt fixture to resume this same claim. No claim email is prepared while evidence is missing.'}]
        self.case['missing_evidence']=missing
        if not missing:
            adapter=t.load_trust();attachments=[claim['path']]+[str(t.ROOT/'fixtures/evidence'/f'{key}.txt') for key in adapter['required_documents'] if key!='claim_form']
            draft=self.store.draft('claim',os.getenv(adapter['destination_env'],'uclh@example.test'),'SYNTHETIC DEMO - travel claim draft','Test inbox only. Attached are synthetic evidence and an unsigned HC5(T) draft. Not a valid claim. Bank details are intentionally omitted. Refund not yet confirmed.',attachments,case_id=self.case['id'],visit_id=self.case['visit_id'],event_id=self.event['id'],event_revision=self.case['revision'])
            self.add_draft(draft)
        return self.action('claim-pack','Your unsigned claim paperwork','Refund and eligibility are unconfirmed. Signature and bank details remain blank.',reason,status='needs-information' if missing else 'prepared',pdf_url='/api/cases/'+self.case['id']+'/claim.pdf',workspace=str(directory))

async def run_registered(store,event_id):
    with store.connect() as connection: row=connection.execute('SELECT case_id,payload FROM case_events WHERE id=?',(event_id,)).fetchone()
    case=get_case(store,row[0]);event=json.loads(row[1]);run=CaseRun(store,event,case)
    try:
        if event['type']=='incoming-message':
            from app import incoming
            run.stage('extracting-message','Reading dates and intent from your message')
            facts=await incoming.extract_facts(event)
            case['interpretation']=facts;case['missing_evidence']=facts['missing_info']
            case['visit_assignment']='unassigned' if facts['requires_existing_visit'] else 'assigned'
            run.event={**event,'interpretation':facts,'hospital':facts['hospital'] or '', 'department':facts['department'] or '',
                       'attended':facts['intent']=='attendance','receipt_available':facts['receipt_available']}
            if facts['appointment']: run.event['appointment']=facts['appointment']
            run.record('extract_message_facts','Extracted source-quoted administrative facts using '+facts['extraction_mode']+'. No preset date or intent was retained.')
            from app import decisions,synthesis
            run.stage('deciding-route','Choosing the action supported by your message')
            routing=decisions.constrain(await decisions.route_message(event['text']),facts)
            run.event['routing']=routing
            if routing['status']=='accepted' and routing['applied_route'] in ('reply_draft','visit_summary'):
                actual='reply_draft' if synthesis.reply_required(run.event) else 'visit_summary'
                if actual!=routing['applied_route']: routing.update(status='explicit-source-fallback',applied_route=None)
            case['decision']['routing']=routing
            run.record('route_incoming_message','OpenAI Decisions '+routing['model']+': '+routing['status']+'; choice '+str(routing['route'])+'; applied '+str(routing['applied_route'])+'; confidence '+str(routing['confidence'])+'; '+str(routing['latency_ms'])+' ms. No send or approval authority.')
        if os.getenv('OPENAI_API_KEY'):
            from app.case_agent import interpret
            await interpret(run)
        else:
            run.read_event();run.context('walking stairs travel personal appointments manager',30)
            text=event['text'].lower()
            if case['missing_evidence']: run.clarify('Offline lexical extraction found missing source details.')
            elif run.event.get('attended'): run.claim('Offline scripted fallback: attendance source supports claim preparation.')
            elif run.event.get('appointment'):
                if event['type']=='incoming-message' and re.search(r'\b(travel|journey|route|transport)\b',text): await asyncio.to_thread(run.journey,'Offline scripted fallback: the message explicitly requests journey planning.')
                run.appointment('Offline scripted fallback: source supplies an appointment date.')
            else: run.wellbeing('Offline scripted fallback: source asks for day-to-day observations.')
            case['decision']['summary']='Offline scripted preparation completed. No model decision was made.'
        if not run.is_complete(): raise ValueError('Interpretation did not prepare a sourced action for this run')
        case['status']='ready'
        case['active_stage']=None
        for source in case['events']:
            if source['id']==event_id and source['revision']==case['revision']: source['status']='ready'
        case.setdefault('runs',[]).append({'event_id':event_id,'revision':case['revision'],'status':'ready','decision':copy.deepcopy(case['decision']),'context':copy.deepcopy(case['context']),'actions':copy.deepcopy(case['actions']),'draft_ids':list(case['draft_ids']),'at':now()})
        save_case(store,case)
        with store.connect() as connection: connection.execute("UPDATE case_events SET status='ready' WHERE id=?",(event_id,))
        store.event('case-ready','Case ready for review','waiting','Nothing has been sent.')
    except Exception as exc:
        stage='read-source' if not run.read else 'retrieve-context' if not run.retrieved else 'prepare-action' if not run.prepared else 'complete'
        case['status']='error';case['error']='Preparation stopped at '+stage+' ('+type(exc).__name__+'). Reopen this event to retry; no message was sent.'
        case['active_stage']=None
        incomplete=isinstance(exc,ValueError) and str(exc)=='Interpretation did not prepare a sourced action for this run'
        case['diagnostics']={'exception_type':type(exc).__name__,'code':'incomplete-agent-run' if incomplete else 'preparation-error','stage':stage,'source_read':run.read,'context_retrieved':run.retrieved,'action_prepared':run.prepared}
        case['decision']['summary']='Interpretation did not complete. Any prepared work remains available for review.'
        for source in case['events']:
            if source['id']==event_id and source['revision']==case['revision']: source['status']='error'
        case.setdefault('runs',[]).append({'event_id':event_id,'revision':case['revision'],'status':'error','decision':copy.deepcopy(case['decision']),'context':copy.deepcopy(case['context']),'actions':copy.deepcopy(case['actions']),'draft_ids':list(case['draft_ids']),'at':now()})
        save_case(store,case)
        with store.connect() as connection: connection.execute("UPDATE case_events SET status='error' WHERE id=?",(event_id,))
        store.event('case-error','Case preparation stopped','stuck',case['error'])
