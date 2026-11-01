import asyncio,json,os,secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote
from fastapi import FastAPI,Request,HTTPException
from fastapi.responses import FileResponse,StreamingResponse,JSONResponse,PlainTextResponse,Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
load_dotenv()
from app.store import Store
from app.tools import ROOT,status_screen
from app.workflow import run_preparation,approve_and_send

store=Store(ROOT/'data')
CSRF=secrets.token_urlsafe(32)
active_task=None

@asynccontextmanager
async def lifespan(app):
    if store.get('phase')=='running':
        store.put('phase','error'); store.put('mascot','stuck'); store.put('error','Preparation interrupted. Retry preparation; completed drafts are preserved.')
    yield

app=FastAPI(title='Pocket Ally — synthetic paperwork demo',lifespan=lifespan)
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
app.mount('/assets',StaticFiles(directory=ROOT/'assets'),name='assets')

@app.middleware('http')
async def local_only(request:Request,call_next):
    host=request.headers.get('host','').split(':')[0]
    if host not in ('127.0.0.1','localhost','testserver'): return JSONResponse({'detail':'Local demo only'},status_code=403)
    if request.method in ('POST','PUT','DELETE'):
        if request.headers.get('x-demo-csrf')!=CSRF: return JSONResponse({'detail':'Reload the local page before taking actions'},status_code=403)
    response=await call_next(request)
    response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    return response

@app.get('/')
async def index(): return FileResponse(ROOT/'static/index.html')

@app.get('/api/status')
async def status(): return {**status_screen(store),'csrf':CSRF}

@app.post('/api/start')
async def start():
    global active_task
    if active_task and not active_task.done(): raise HTTPException(409,'Preparation already running')
    if store.get('phase') in ('awaiting-approval','complete'): return {'status':'already prepared'}
    active_task=asyncio.create_task(run_preparation(store))
    return {'status':'started'}

class Approval(BaseModel):
    digest:str

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
    if not found: raise HTTPException(404)
    return {**found,'audio_url':'/api/notes/'+id+'/audio'}

@app.get('/api/notes/{id}/audio')
async def audio(id:str):
    found=next((n for n in store.notes() if n['id']==id),None)
    if not found or not Path(found['audio_path']).exists(): raise HTTPException(404,'Synthetic recording unavailable; transcript remains accessible')
    return FileResponse(found['audio_path'],media_type='audio/wav')

@app.get('/api/outbox/{id}')
async def outbox(id:str):
    if not any(d['id']==id and d['result'] for d in store.drafts()): raise HTTPException(404)
    path=store.root/'outbox'/f'{id}.eml'
    if not path.exists(): raise HTTPException(404)
    return FileResponse(path,media_type='message/rfc822',filename=path.name)
