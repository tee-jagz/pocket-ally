"""Optional live adapters. No silent fallback after a live side effect."""
import base64, os
from pathlib import Path

def google_service(name):
    token = Path(os.getenv('GOOGLE_TOKEN_FILE','data/google-token.json'))
    if not token.exists(): raise RuntimeError('Google OAuth token missing')
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    import httplib2, google_auth_httplib2
    creds = Credentials.from_authorized_user_file(str(token))
    if creds.expired and creds.refresh_token: creds.refresh(Request())
    http=google_auth_httplib2.AuthorizedHttp(creds,http=httplib2.Http(timeout=15))
    return build(name, 'v1' if name=='gmail' else 'v3',http=http,cache_discovery=False)

def poll_gmail():
    from email import policy
    from email.parser import BytesParser
    service=google_service('gmail')
    hits=service.users().messages().list(userId='me',q='in:inbox subject:UCLH subject:SYNTHETIC',maxResults=1).execute().get('messages',[])
    if not hits: raise ValueError('No synthetic UCLH attendance email found')
    msg=service.users().messages().get(userId='me',id=hits[0]['id'],format='raw').execute()
    raw=msg['raw']
    parsed=BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw+'='*(-len(raw)%4)))
    body=parsed.get_body(preferencelist=('plain',)) if parsed.is_multipart() else parsed
    if body is None or body.get_content_type()!='text/plain': raise ValueError('A plain text forwarded email is required')
    return str(body.get_content()), hits[0]['id']

def gmail_send(message):
    raw=base64.urlsafe_b64encode(message.as_bytes()).decode()
    return google_service('gmail').users().messages().send(userId='me',body={'raw':raw}).execute()['id']

def calendar_create(uid,start,end,location):
    svc=google_service('calendar')
    body={'id':uid,'summary':'Personal appointment + travel','location':location,
          'start':{'dateTime':start,'timeZone':'Europe/London'},
          'end':{'dateTime':end,'timeZone':'Europe/London'},
          'description':'Planning estimates: 50 minute travel buffer and 60 minute appointment.'}
    try: return svc.events().insert(calendarId='primary',body=body,sendUpdates='none').execute()['id']
    except Exception as exc:
        if getattr(getattr(exc,'resp',None),'status',None)==409:
            return svc.events().get(calendarId='primary',eventId=uid).execute()['id']
        raise

def embed(text):
    from openai import OpenAI
    return OpenAI(timeout=20,max_retries=0).embeddings.create(model='text-embedding-3-small',input=text).data[0].embedding

def transcribe(path):
    from openai import OpenAI
    with Path(path).open('rb') as f:
        return OpenAI(timeout=30,max_retries=0).audio.transcriptions.create(model='gpt-4o-transcribe',file=f).text
