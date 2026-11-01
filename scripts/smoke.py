"""Read-only connectivity checks; never sends mail or creates events."""
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

def run():
    checks = {}
    for name in ('OpenAI','Gmail','Calendar','pgvector'):
        try:
            if name == 'OpenAI':
                if not os.getenv('OPENAI_API_KEY'): raise RuntimeError('OPENAI_API_KEY missing')
                from openai import OpenAI
                c = OpenAI(timeout=12, max_retries=0)
                c.responses.create(model=os.getenv('OPENAI_MODEL','gpt-5-mini'),input='Reply OK.',max_output_tokens=64,store=False)
                assert len(c.embeddings.create(model='text-embedding-3-small',input='synthetic demo').data[0].embedding) == 1536
            elif name in ('Gmail','Calendar'):
                from app.integrations import google_service
                svc=google_service('gmail' if name=='Gmail' else 'calendar')
                if name=='Gmail':
                    profile=svc.users().getProfile(userId='me').execute()
                    if not os.getenv('TEST_INBOX_EMAIL'): raise RuntimeError('TEST_INBOX_EMAIL missing')
                    if profile['emailAddress'].lower()!=os.environ['TEST_INBOX_EMAIL'].lower(): raise RuntimeError('OAuth account differs from configured test inbox')
                else: svc.calendarList().list(maxResults=1).execute()
            else:
                if not os.getenv('DATABASE_URL'): raise RuntimeError('DATABASE_URL missing')
                import psycopg
                with psycopg.connect(os.environ['DATABASE_URL'],connect_timeout=5) as conn:
                    assert conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()
                    conn.execute("SELECT '[1,0]'::vector <=> '[1,0]'::vector").fetchone()
            checks[name]={'ok':True}
        except Exception as exc:
            # Only exception class and known configuration errors; never dump OAuth/API responses.
            reason = str(exc) if type(exc) is RuntimeError else type(exc).__name__
            checks[name]={'ok':False,'reason':reason}
    print(json.dumps(checks,indent=2))
    return all(c['ok'] for c in checks.values())
if __name__=='__main__': sys.exit(0 if run() else 1)
