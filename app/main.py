import asyncio,json,os,secrets,time,re
from ipaddress import ip_address
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote,unquote
from typing import Literal
from fastapi import FastAPI,Request,HTTPException
from fastapi.responses import FileResponse,StreamingResponse,JSONResponse,PlainTextResponse,Response,RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,ConfigDict,Field,field_validator
from dotenv import load_dotenv
load_dotenv()
from app.store import Store
from app.tools import ROOT,status_screen
from app.workflow import run_preparation,approve_and_send
from app import journal,companion,cases

store=Store(ROOT/'data')
CSRF=secrets.token_urlsafe(32)
active_task=None
SESSIONS={}
CASE_TASKS=set()
SESSION_COOKIE='__Host-pocketally-session'

@asynccontextmanager
async def lifespan(app):
    store.migrate_product_copy()
    for case in cases.list_cases(store)['cases']:
        if case['status']=='running':
            case['status']='error';case['error']='Preparation was interrupted. Reopen the same event to resume safely.'
            cases.save_case(store,case)
    with store.connect() as connection: connection.execute("UPDATE case_events SET status='error' WHERE status='running'")
    if store.get('phase')=='running':
        store.put('phase','error'); store.put('mascot','stuck'); store.put('error','Preparation interrupted. Retry preparation; completed drafts are preserved.')
    yield

app=FastAPI(title='Pocket Ally - synthetic paperwork demo',lifespan=lifespan)
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
app.mount('/assets',StaticFiles(directory=ROOT/'assets'),name='assets')

@app.middleware('http')
async def local_only(request:Request,call_next):
    authority=request.headers.get('host','').lower()
    host=authority.split(':')[0]
    public=os.getenv('PUBLIC_DEMO_HOST','').lower()
    if not re.fullmatch(r'[a-z0-9]+(?:[a-z0-9.-]*[a-z0-9])?',public): public=''
    proxied=any(name in request.headers for name in ('forwarded','x-forwarded-for','x-forwarded-host','x-forwarded-proto','tailscale-user-login','tailscale-user-name'))
    local=host in ('127.0.0.1','localhost','testserver') and not proxied
    remote=bool(public and authority==public)
    error=None
    if not local and not remote: error=(403,'This demo host is not allowed')
    mutation=request.method in ('POST','PUT','PATCH','DELETE')
    session_route=request.url.path=='/api/session'
    expected_origin=('https://' if remote else request.url.scheme+'://')+authority
    if not error and mutation:
        origin=request.headers.get('origin')
        if (remote and origin!=expected_origin) or (origin is not None and origin!=expected_origin):
            error=(403,'Actions require the same origin as this demo')
    if not error and remote and request.url.path.startswith('/api/') and not session_route:
        session=request.cookies.get(SESSION_COOKIE,'')
        login=os.getenv('TAILSCALE_ALLOWED_LOGIN','')
        try: loopback_peer=bool(request.client and ip_address(request.client.host).is_loopback)
        except ValueError: loopback_peer=False
        # Opt in only behind private Tailscale Serve with raw peer addresses retained.
        # The operator must use --no-proxy-headers and Serve's stripped identity headers.
        tailscale_identity=bool(login and loopback_peer
            and request.headers.get('x-forwarded-proto')=='https'
            and request.headers.get('x-forwarded-host')==public
            and secrets.compare_digest(request.headers.get('tailscale-user-login','').encode(),login.encode()))
        if not tailscale_identity and SESSIONS.get(session,0)<=time.time(): error=(401,'Open the private demo access link to continue')
    if not error and mutation and not session_route:
        if request.headers.get('x-demo-csrf')!=CSRF: error=(403,'Reload the page before taking actions')
    response=JSONResponse({'detail':error[1]},status_code=error[0]) if error else await call_next(request)
    response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    return response

class SessionInput(BaseModel):
    token:str=Field(max_length=512)

def verify_access_token(token):
    expected=os.getenv('DEMO_ACCESS_TOKEN','')
    if len(expected)<24: raise HTTPException(503,'Private demo access is not configured')
    if not secrets.compare_digest(token.encode(),expected.encode()): raise HTTPException(403,'Access link is invalid')

def attach_session(response):
    session=secrets.token_urlsafe(32)
    current=time.time()
    for id,expiry in list(SESSIONS.items()):
        if expiry<=current: SESSIONS.pop(id,None)
    SESSIONS[session]=current+43200
    response.set_cookie(SESSION_COOKIE,session,max_age=43200,secure=True,httponly=True,samesite='strict',path='/')
    return response

@app.post('/api/session')
async def create_session(payload:SessionInput):
    verify_access_token(payload.token)
    return attach_session(JSONResponse({'authenticated':True}))

@app.get('/access/{token}')
async def access_link(token:str):
    verify_access_token(token)
    return attach_session(RedirectResponse('/',status_code=303))

@app.get('/')
async def index(): return FileResponse(ROOT/'static/index.html')

@app.get('/sw.js')
async def service_worker():
    return FileResponse(ROOT/'static/sw.js',media_type='application/javascript',headers={'Service-Worker-Allowed':'/'})

@app.get('/manifest.webmanifest')
async def manifest():
    return FileResponse(ROOT/'static/manifest.webmanifest',media_type='application/manifest+json')

@app.get('/api/status')
async def status(): return {**status_screen(store),'csrf':CSRF}

@app.get('/api/scenarios')
async def scenarios(): return cases.catalogue()

@app.get('/api/cases')
async def case_list(): return cases.list_cases(store)

def start_case_event(event):
    try: result=cases.register_event(store,event)
    except ValueError as exc: raise HTTPException(409,str(exc))
    if result.pop('_run'):
        task=asyncio.create_task(cases.run_registered(store,event['id']))
        CASE_TASKS.add(task);task.add_done_callback(CASE_TASKS.discard)
    return result

@app.post('/api/scenarios/{id}/run')
async def run_scenario(id:str):
    try: event=cases.scenario(id)['event']
    except LookupError: raise HTTPException(404,'Scenario not found')
    return start_case_event(event)

class MessageInput(BaseModel):
    text:str=Field(min_length=1,max_length=6000)
    synthetic:Literal[True]
    visit_id:str|None=Field(default=None,max_length=80,pattern=r'^visit-[a-z0-9-]+$')
    origin:str=Field(default='',max_length=40)
    destination:str=Field(default='',max_length=40)
    @field_validator('text')
    @classmethod
    def nonblank(cls,value):
        if not value.strip(): raise ValueError('Write a synthetic incoming message first')
        return value.strip()

@app.post('/api/events/run')
async def run_message(payload:MessageInput):
    from app.incoming import source_event
    try: event=source_event(store,payload.text,payload.origin,payload.destination,payload.visit_id)
    except LookupError: raise HTTPException(422,'Choose an existing visit or start a new one')
    return start_case_event(event)

class ExampleInput(BaseModel):
    scenario_id:Literal['checkup-email','confirmed-visit','attended-visit','reschedule']
    visit_id:str|None=Field(default=None,max_length=80,pattern=r'^visit-[a-z0-9-]+$')

@app.post('/api/events/example')
async def generate_example(payload:ExampleInput):
    from app import examples
    try: return await examples.generate(store,payload.scenario_id,payload.visit_id)
    except (ValueError,LookupError) as exc: raise HTTPException(422,str(exc))
    except examples.GenerationNotConfigured as exc: raise HTTPException(503,str(exc))
    except examples.GenerationUnavailable as exc: raise HTTPException(502,str(exc))

@app.get('/api/cases/{id}')
async def case_detail(id:str):
    try: return cases.get_case(store,id)
    except LookupError: raise HTTPException(404,'Case not found')

class SyntheticReceipt(BaseModel):
    synthetic:Literal[True]

@app.post('/api/cases/{id}/evidence/receipt')
async def add_case_receipt(id:str,payload:SyntheticReceipt):
    try: event=cases.receipt_event(store,id)
    except LookupError: raise HTTPException(404,'Case not found')
    except ValueError as exc: raise HTTPException(409,str(exc))
    return start_case_event(event)

@app.get('/api/cases/{id}/calendar.ics')
async def case_calendar(id:str):
    await case_detail(id)
    path=store.root/'cases'/id/'appointment.ics'
    if not path.exists(): raise HTTPException(404,'No appointment plan is prepared')
    return FileResponse(path,media_type='text/calendar',filename='appointment.ics')

@app.get('/api/cases/{id}/claim.pdf')
async def case_claim(id:str):
    case=await case_detail(id)
    action=next((action for action in case['actions'] if action['kind']=='claim-pack'),None)
    if not action: raise HTTPException(404,'No claim draft is prepared')
    path=store.root/'cases'/id/('revision-'+str(action['event_revision']))/'hc5-draft.pdf'
    if not path.exists(): raise HTTPException(404,'Claim draft is unavailable')
    return FileResponse(path,media_type='application/pdf',filename='hc5-draft.pdf')

@app.post('/api/start')
async def start():
    global active_task
    if active_task and not active_task.done(): raise HTTPException(409,'Preparation already running')
    if store.get('phase') in ('awaiting-approval','complete'): return {'status':'already prepared'}
    active_task=asyncio.create_task(run_preparation(store))
    return {'status':'started'}

class Approval(BaseModel):
    digest:str

class ReplyEdit(BaseModel):
    model_config=ConfigDict(extra='forbid')
    subject:str=Field(min_length=1,max_length=160)
    body:str=Field(min_length=1,max_length=6000)

@app.patch('/api/drafts/{id}')
async def edit_reply_draft(id:str,payload:ReplyEdit):
    from app.synthesis import edit_reply
    try: return edit_reply(store,id,payload.subject,payload.body)
    except LookupError as exc: raise HTTPException(404,str(exc))
    except PermissionError as exc: raise HTTPException(409,str(exc))
    except ValueError as exc: raise HTTPException(422,str(exc))

@app.post('/api/drafts/{id}/approve-send')
async def approve_send(id:str,approval:Approval):
    try: await approve_and_send(store,id,approval.digest)
    except (ValueError,PermissionError) as exc: raise HTTPException(403,str(exc))
    except Exception:
        store.put('mascot','stuck'); store.event('tool-error','Send approved draft','stuck','Delivery uncertain. Inspect the test mailbox before retrying.')
        raise HTTPException(502,'Delivery uncertain. Inspect the test mailbox before retrying; automatic retries are blocked.')
    return {'status':'done'}

@app.get('/api/events')
async def events(request:Request,after:int=0):
    async def stream():
        cursor=after
        try: cursor=max(cursor,int(request.headers.get('last-event-id','0')))
        except ValueError: pass
        while not await request.is_disconnected():
            rows=store.events(cursor)
            for row in rows:
                cursor=row['id']; yield f'id: {cursor}\ndata: {json.dumps(row)}\n\n'
            if not rows: yield ': keepalive\n\n'
            await asyncio.sleep(.4)
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'X-Accel-Buffering':'no'})

@app.get('/api/email')
async def email(): return PlainTextResponse(store.get('email',{}).get('text','No email processed yet'))

@app.get('/api/calendar.ics')
async def calendar():
    path=store.root/'next-appointment.ics'
    if not path.exists(): raise HTTPException(404)
    return FileResponse(path,media_type='text/calendar',filename=path.name)

@app.get('/api/claim.pdf')
async def claim():
    path=store.root/'hc5-draft.pdf'
    if not path.exists(): raise HTTPException(404)
    return FileResponse(path,media_type='application/pdf',filename=path.name)

@app.get('/api/drafts/{id}/attachments/{index}')
async def draft_attachment(id:str,index:int):
    payload=store.draft_payload(id)
    if not payload or index<0 or index>=len(payload['attachments']): raise HTTPException(404)
    try:
        content=Store.attachment_bytes(payload)
        if Store.digest(payload,content)!=payload['digest']: raise ValueError('Changed attachment')
    except (OSError,ValueError):
        raise HTTPException(409,'Draft attachments changed or are unavailable; prepare and review again')
    path=Path(payload['attachments'][index])
    media_type={'.pdf':'application/pdf','.txt':'text/plain'}.get(path.suffix.lower(),'application/octet-stream')
    return Response(content[index],media_type=media_type,
                    headers={'Content-Disposition':"inline; filename*=UTF-8''"+quote(path.name,safe='')})

@app.get('/api/notes/{id}')
async def note(id:str):
    found=next((n for n in store.notes() if n['id']==id),None)
    if not found:
        try: return journal.entry(store,id)
        except LookupError: raise HTTPException(404)
    return {**found,'audio_url':'/api/notes/'+id+'/audio'}

@app.get('/api/notes/{id}/audio')
async def audio(id:str):
    found=next((n for n in store.notes() if n['id']==id),None)
    if not found: found=next((note for note in journal.raw_entries(store) if note['id']==id),None)
    if not found or not found.get('audio_path') or not Path(found['audio_path']).exists(): raise HTTPException(404,'Synthetic recording unavailable; transcript remains accessible')
    return FileResponse(found['audio_path'],media_type=found.get('audio_mime','audio/wav'))

class JournalInput(BaseModel):
    title:str=Field(default='',max_length=120)
    transcript:str=Field(min_length=1,max_length=10000)
    synthetic:Literal[True]
    @field_validator('transcript')
    @classmethod
    def nonblank(cls,value):
        if not value.strip(): raise ValueError('Write a synthetic transcript first')
        return value

class RecallInput(BaseModel):
    question:str=Field(min_length=1,max_length=400)

class LinkInput(BaseModel):
    task:Literal['claim','employer']

@app.get('/api/journal')
async def journal_list(): return {'entries':journal.entries(store),'mode':'synthetic journal'}

@app.post('/api/journal')
async def journal_create(payload:JournalInput):
    return {'entry':journal.create_text(store,payload.transcript,payload.title)}

@app.post('/api/journal/audio')
async def journal_audio(request:Request):
    mime=request.headers.get('content-type','').split(';')[0].strip().lower()
    if mime not in journal.AUDIO_TYPES or request.headers.get('x-synthetic')!='true':
        raise HTTPException(422,'Supported synthetic audio recording required')
    try:
        duration=float(request.headers.get('x-audio-duration','0'))
        size=int(request.headers.get('content-length','0'))
    except ValueError: raise HTTPException(422,'Invalid audio metadata')
    if not 0<duration<=120: raise HTTPException(422,'Recordings must be at most two minutes')
    if size>journal.MAX_AUDIO_BYTES: raise HTTPException(413,'Recording must be 10 MiB or smaller')
    content=bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content)>journal.MAX_AUDIO_BYTES: raise HTTPException(413,'Recording must be 10 MiB or smaller')
    title=unquote(request.headers.get('x-audio-title','')).strip()
    if len(title)>120: raise HTTPException(422,'Title must be 120 characters or fewer')
    try: result=await asyncio.to_thread(journal.create_audio,store,bytes(content),mime,duration,title)
    except ValueError as exc: raise HTTPException(422,str(exc))
    return {'entry':result}

@app.patch('/api/journal/{id}')
async def journal_patch(id:str,payload:JournalInput):
    try: return {'entry':journal.update_transcript(store,id,payload.transcript)}
    except LookupError: raise HTTPException(404,'Journal entry not found')
    except PermissionError as exc: raise HTTPException(403,str(exc))

@app.post('/api/journal/recall')
async def journal_recall(payload:RecallInput): return await asyncio.to_thread(journal.recall,store,payload.question)

@app.post('/api/journal/{id}/link')
async def journal_link(id:str,payload:LinkInput):
    try: return {'entry':journal.link(store,id,payload.task)}
    except LookupError: raise HTTPException(404,'Journal entry not found')

class CompanionInput(BaseModel):
    prompt:str=Field(min_length=1,max_length=400)
    style:Literal['soft','playful','minimal']
    @field_validator('prompt')
    @classmethod
    def nonblank(cls,value):
        if not value.strip(): raise ValueError('Describe your fictional companion first')
        return value.strip()

class CompanionSelect(BaseModel):
    preview_id:str=Field(min_length=1,max_length=64)

@app.get('/api/companion')
async def companion_status(): return companion.state(store)

@app.post('/api/companion/preview')
async def companion_preview(payload:CompanionInput):
    try: return {'preview':await asyncio.to_thread(companion.preview,store,payload.prompt,payload.style)}
    except Exception: raise HTTPException(502,'The preview could not be saved. Your selected companion has not changed.')

@app.post('/api/companion/select')
async def companion_select(payload:CompanionSelect):
    try: return {'saved':companion.select(store,payload.preview_id)}
    except LookupError: raise HTTPException(404,'Companion preview not found')

@app.get('/api/companion/images/{id}')
async def companion_image(id:str):
    state=companion.state(store)
    known=state['previews']+([state['saved']] if state['saved'] else [])
    if not re.fullmatch(r'[a-f0-9]{24}',id) or not any(item['id']==id and item['mode']=='openai-generated' for item in known): raise HTTPException(404)
    path=store.root/'companions'/(id+'.png')
    if not path.exists(): raise HTTPException(404)
    return FileResponse(path,media_type='image/png')

@app.get('/api/outbox/{id}')
async def outbox(id:str):
    if not any(d['id']==id and d['result'] for d in store.drafts()): raise HTTPException(404)
    path=store.root/'outbox'/f'{id}.eml'
    if not path.exists(): raise HTTPException(404)
    return FileResponse(path,media_type='message/rfc822',filename=path.name)
