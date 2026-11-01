"""Content-addressed embeddings and cosine ranking, with honest lexical fallback."""
import hashlib,json,math,os,re

MODEL='text-embedding-3-small'
STOP=set('the and for with from have has had how your you about this that these those was were are been being will would could should can may might must please need next already before after into onto some any their them they our out not but what when where which why who get got did does doing say said tell told summary summarise summarize'.split())
MOBILITY=set('travel travelling traveling transport transportation mobility journey journeys commute commuting walk walks walked walking station stations bus buses train trains bench'.split())
ACCESS={'stair','stairs','handrail','landing'}

def lexical(query,note):
    words={word for word in re.findall(r'\w+',query.lower()) if len(word)>=3 and word not in STOP}
    triggers=words & MOBILITY
    expanded=(MOBILITY if triggers else set()) | (ACCESS if words & ACCESS or 'mobility' in words else set())
    source=set(re.findall(r'\w+',note['transcript'].lower()))
    literal=words & source;topic=(expanded-words) & source
    reason=('Literal matches: '+', '.join(sorted(literal)[:6])+'. ' if literal else '')
    if topic: reason+='Topic match: travel/mobility via '+', '.join(sorted(topic)[:6])+' (expanded from '+', '.join(sorted(triggers or words & ACCESS or words & {'mobility'})[:6])+'). '
    return len(literal|topic),reason

def vector(store,text):
    digest=hashlib.sha256((MODEL+'\n'+text).encode()).hexdigest()
    with store.connect() as connection:
        row=connection.execute('SELECT vector FROM embedding_cache WHERE digest=?',(digest,)).fetchone()
    if row: return json.loads(row[0]),True
    from app.integrations import embed
    values=[float(value) for value in embed(text)]
    if not values or any(not math.isfinite(value) for value in values) or not any(values): raise ValueError('Invalid embedding vector')
    with store.connect() as connection: connection.execute('INSERT OR REPLACE INTO embedding_cache VALUES (?,?,?)',(digest,MODEL,json.dumps(values)))
    return values,False

def batch_vectors(store,texts):
    digests=[hashlib.sha256((MODEL+'\n'+text).encode()).hexdigest() for text in texts]
    found={};missing={}
    with store.connect() as connection:
        for digest,text in zip(digests,texts):
            row=connection.execute('SELECT vector FROM embedding_cache WHERE digest=?',(digest,)).fetchone()
            if row: found[digest]=json.loads(row[0])
            else: missing[digest]=text
    hits=len(texts)-sum(digest in missing for digest in digests)
    if missing:
        from app.integrations import embed_many
        generated=embed_many([text[:2000] for text in missing.values()])
        if len(generated)!=len(missing): raise ValueError('Incomplete embedding batch')
        with store.connect() as connection:
            for digest,values in zip(missing,generated):
                values=[float(value) for value in values]
                if not values or any(not math.isfinite(value) for value in values) or not any(values): raise ValueError('Invalid embedding vector')
                found[digest]=values
                connection.execute('INSERT OR REPLACE INTO embedding_cache VALUES (?,?,?)',(digest,MODEL,json.dumps(values)))
    return [found[digest] for digest in digests],hits

def cosine(left,right):
    if len(left)!=len(right): raise ValueError('Embedding dimensions changed')
    return sum(a*b for a,b in zip(left,right))/(math.sqrt(sum(a*a for a in left))*math.sqrt(sum(b*b for b in right)))

def rank(store,query,notes,limit=6):
    eligible=[note for note in notes if note.get('transcript')]
    notes=sorted(eligible,key=lambda note:note.get('timestamp',''),reverse=True)[:32]
    bounds={'searched_sources':len(notes),'eligible_sources':len(eligible),'embedded_character_limit':2000}
    metadata={'mode':'lexical-fallback','notice':'Keyword and bounded topic matching; no semantic provider was called.'}
    if os.getenv('OPENAI_API_KEY') and notes:
        try:
            vectors,hits=batch_vectors(store,[query[:1000]]+[note['transcript'] for note in notes]);query_vector=vectors[0];scored=[]
            for note,values in zip(notes,vectors[1:]):
                score=cosine(query_vector,values)
                scored.append({'note':note,'score':score,'reason':f'Semantic cosine similarity {score:.3f} from {MODEL}; source wording retained. '})
            scored.sort(key=lambda row:row['score'],reverse=True)
            cutoff=max(.24,(scored[0]['score']-.10) if scored else .24)
            matched=[row for row in scored if row['score']>=cutoff][:limit]
            metadata={'mode':'openai-embeddings','model':MODEL,'cache_hits':hits,'minimum_similarity':cutoff,**bounds}
            if not matched: metadata['notice']='No eligible dated source exceeded the semantic relevance threshold.'
            return matched,metadata
        except Exception:
            metadata={'mode':'lexical-provider-unavailable','notice':'Semantic retrieval was unavailable. Showing keyword/topic matches instead; this is not a semantic no-match result.'}
    scored=[]
    for note in notes:
        score,reason=lexical(query,note)
        if score: scored.append({'note':note,'score':score,'reason':reason})
    return sorted(scored,key=lambda row:(row['score'],row['note'].get('timestamp','')),reverse=True)[:limit],{**metadata,**bounds}
