"""Postgres persistence includes timestamps and source audio paths."""
import json,os
import psycopg
from pgvector.psycopg import register_vector

class VectorStore:
    def __init__(self):
        self.url=os.environ['DATABASE_URL']
        with psycopg.connect(self.url,connect_timeout=5) as c:
            c.execute('CREATE EXTENSION IF NOT EXISTS vector')
            c.execute('CREATE TABLE IF NOT EXISTS diary (id TEXT PRIMARY KEY, timestamp TIMESTAMPTZ NOT NULL, audio_path TEXT NOT NULL, transcript TEXT NOT NULL, payload JSONB NOT NULL, embedding vector(1536) NOT NULL)')
    def upsert(self,n,embedding):
        with psycopg.connect(self.url,connect_timeout=5) as c:
            register_vector(c)
            import numpy as np
            c.execute('INSERT INTO diary VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET timestamp=EXCLUDED.timestamp,audio_path=EXCLUDED.audio_path,transcript=EXCLUDED.transcript,payload=EXCLUDED.payload,embedding=EXCLUDED.embedding',
                      (n['id'],n['timestamp'],n['audio_path'],n['transcript'],json.dumps(n),np.array(embedding)))
    def search(self,embedding,limit):
        with psycopg.connect(self.url,connect_timeout=5) as c:
            register_vector(c)
            import numpy as np
            return [r[0] for r in c.execute('SELECT payload FROM diary ORDER BY embedding <=> %s LIMIT %s',(np.array(embedding),limit))]
