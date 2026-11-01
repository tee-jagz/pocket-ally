import hashlib, json, os, re, sqlite3, threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

LOCK=threading.RLock()

def now(): return datetime.now(timezone.utc).isoformat()

def allowed_recipient(recipient):
    allowed={os.getenv('TEST_UCLH_EMAIL','uclh@example.test'),os.getenv('TEST_EMPLOYER_EMAIL','manager@example.test')}
    # A configured value must still be exactly one plain address, never a header/list.
    mailbox=r"[A-Za-z0-9][A-Za-z0-9._+-]*@(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,63}"
    domain=recipient.lower().rsplit('@',1)[-1] if isinstance(recipient,str) else ''
    nhs=any(domain==suffix or domain.endswith('.'+suffix) for suffix in ('nhs.net','nhs.uk','nhs.scot'))
    if not isinstance(recipient,str) or not re.fullmatch(mailbox,recipient) or recipient not in allowed or nhs:
        raise ValueError('Only exact throwaway test destinations are allowed; NHS addresses are blocked')
    if os.getenv('APP_MODE','local')=='live' and (os.getenv('CONFIRM_THROWAWAY_ACCOUNTS')!='true' or domain.endswith('.test')):
        raise ValueError('Live delivery requires explicitly confirmed throwaway accounts')

class Store:
    def __init__(self, root=Path('data')):
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
        self.db=self.root/'state.sqlite3'
        with self.connect() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY, payload TEXT NOT NULL, approved TEXT, result TEXT, sending INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS notes(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS journal(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS journal_links(note_id TEXT NOT NULL, task TEXT NOT NULL, PRIMARY KEY(note_id,task));
            CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS case_events(id TEXT PRIMARY KEY, case_id TEXT NOT NULL, fingerprint TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS embedding_cache(digest TEXT PRIMARY KEY, model TEXT NOT NULL, vector TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, kind TEXT, tool TEXT, state TEXT, detail TEXT);
            ''')
            if 'obsolete' not in {row[1] for row in c.execute('PRAGMA table_info(drafts)')}:
                c.execute('ALTER TABLE drafts ADD COLUMN obsolete INTEGER NOT NULL DEFAULT 0')
    @contextmanager
    def connect(self):
        conn=sqlite3.connect(self.db,timeout=20)
        try:
            with conn: yield conn
        finally: conn.close()
    def put(self,k,v):
        with self.connect() as c: c.execute('INSERT OR REPLACE INTO state VALUES (?,?)',(k,json.dumps(v)))
    def get(self,k,default=None):
        with self.connect() as c: r=c.execute('SELECT value FROM state WHERE key=?',(k,)).fetchone()
        return json.loads(r[0]) if r else default
    def event(self,kind,tool,state,detail=''):
        with self.connect() as c: c.execute('INSERT INTO events(time,kind,tool,state,detail) VALUES (?,?,?,?,?)',(now(),kind,tool,state,detail))
    def events(self,after=0):
        with self.connect() as c:
            c.row_factory=sqlite3.Row
            return [dict(r) for r in c.execute('SELECT * FROM events WHERE id>? ORDER BY id',(after,))]
    def add_note(self,n):
        with self.connect() as c: c.execute('INSERT OR REPLACE INTO notes VALUES (?,?)',(n['id'],json.dumps(n)))
    def notes(self):
        with self.connect() as c: return [json.loads(r[0]) for r in c.execute('SELECT payload FROM notes ORDER BY id')]
    @staticmethod
    def attachment_bytes(payload):
        return [Path(filename).read_bytes() for filename in payload['attachments']]
    @staticmethod
    def digest(payload,attachment_bytes=None):
        p=dict(payload)
        p.pop('id',None); p.pop('digest',None)
        content=Store.attachment_bytes(p) if attachment_bytes is None else attachment_bytes
        if len(content)!=len(p['attachments']): raise ValueError('Attachment snapshot is incomplete')
        p['attachment_hashes']=[hashlib.sha256(data).hexdigest() for data in content]
        return hashlib.sha256(json.dumps(p,sort_keys=True).encode()).hexdigest()
    def draft_payload(self,id):
        with self.connect() as c: row=c.execute('SELECT payload FROM drafts WHERE id=?',(id,)).fetchone()
        return json.loads(row[0]) if row else None
    def draft(self,kind,recipient,subject,body,attachments,**extra):
        allowed_recipient(recipient)
        payload=dict(kind=kind,recipient=recipient,subject=subject,body=body,attachments=attachments,**extra)
        digest=self.digest(payload)
        payload.update(id=digest[:24],digest=digest)
        with self.connect() as c: c.execute('INSERT OR IGNORE INTO drafts(id,payload) VALUES (?,?)',(payload['id'],json.dumps(payload)))
        return payload
    def drafts(self,include_obsolete=False):
        with self.connect() as c:
            query='SELECT payload,approved,result,sending,obsolete FROM drafts'+('' if include_obsolete else ' WHERE obsolete=0')
            return [{**json.loads(r[0]),'approved':r[1] is not None,'result':json.loads(r[2]) if r[2] else None,'sending':bool(r[3]),'obsolete':bool(r[4])} for r in c.execute(query)]
    def approve(self,id,digest):
        with LOCK,self.connect() as c:
            row=c.execute('SELECT payload,obsolete FROM drafts WHERE id=?',(id,)).fetchone()
            if not row: raise ValueError('Unknown draft')
            if row[1]: raise PermissionError('This draft was superseded; review the current case draft')
            p=json.loads(row[0])
            try: current_digest=self.digest(p)
            except OSError as exc: raise PermissionError('Attachment unavailable; review the draft again') from exc
            if digest!=p['digest'] or current_digest!=digest: raise PermissionError('Draft changed; review again')
            c.execute('UPDATE drafts SET approved=? WHERE id=?',(digest,id))
        self.event('approval',p['kind'],'waiting','Exact draft approved by user')

    def invalidate_case_drafts(self,case_id):
        with LOCK,self.connect() as connection:
            for id,raw in connection.execute('SELECT id,payload FROM drafts WHERE result IS NULL AND sending=0 AND obsolete=0').fetchall():
                if json.loads(raw).get('case_id')==case_id:
                    connection.execute('UPDATE drafts SET obsolete=1,approved=NULL WHERE id=?',(id,))

    def migrate_product_copy(self):
        """Refresh only verified old generated drafts that have never been approved."""
        old=chr(0x2014)
        def normalise(value):
            if isinstance(value,str): return value.replace(old,'-')
            if isinstance(value,list): return [normalise(item) for item in value]
            if isinstance(value,dict): return {key:normalise(item) for key,item in value.items()}
            return value
        with LOCK,self.connect() as connection:
            for key in ('calendar','claim'):
                row=connection.execute('SELECT value FROM state WHERE key=?',(key,)).fetchone()
                if row:
                    value=json.loads(row[0]);connection.execute('UPDATE state SET value=? WHERE key=?',(json.dumps(normalise(value)),key))
            row=connection.execute("SELECT value FROM state WHERE key='answer'").fetchone()
            if row:
                value=json.loads(row[0]);value['method']=normalise(value.get('method',''))
                connection.execute("UPDATE state SET value=? WHERE key='answer'",(json.dumps(value),))
            for id,raw in connection.execute('SELECT id,payload FROM drafts WHERE approved IS NULL AND result IS NULL AND sending=0').fetchall():
                payload=json.loads(raw)
                if payload.get('kind')!='claim' or payload.get('subject')!='SYNTHETIC DEMO '+old+' travel claim draft': continue
                try:
                    current=self.attachment_bytes(payload)
                    previous=[content.replace(b'SYNTHETIC DEMO EVIDENCE ONLY - not valid proof.',('SYNTHETIC DEMO EVIDENCE ONLY '+old+' not valid proof.').encode()) if Path(filename).name in ('attendance.txt','entitlement.txt','travel.txt') else content for filename,content in zip(payload['attachments'],current)]
                    if self.digest(payload,previous)!=payload['digest']: continue
                    payload['subject']=normalise(payload['subject']);payload['body']=normalise(payload['body'])
                    digest=self.digest(payload,current);payload.update(id=digest[:24],digest=digest)
                    connection.execute('INSERT OR IGNORE INTO drafts(id,payload) VALUES (?,?)',(payload['id'],json.dumps(payload)))
                    connection.execute('DELETE FROM drafts WHERE id=?',(id,))
                except OSError: continue
