"""Bounded cited synthesis and exact-review edits, without sending authority."""
import json,re
from pydantic import BaseModel,ConfigDict,Field
from app.store import LOCK,allowed_recipient,now


class SummarySentence(BaseModel):
    model_config=ConfigDict(extra='forbid')
    text:str=Field(min_length=5,max_length=500,description='One short first-person paraphrased/composed observation grounded only in the cited exact evidence. No advice, diagnosis, new symptom, number, frequency or improvement claim.')
    source_ids:list[str]=Field(min_length=1,max_length=4,description='IDs returned by retrieve_relevant_context supporting this sentence.')
    evidence_quotes:list[str]=Field(min_length=1,max_length=4,description='Exact verbatim supporting quote for each corresponding source ID, in the same order. Not a paraphrase.')


def asks_general_wellbeing(event):
    return bool(re.search(r'how have you been|how (?:are |have |you |have you |are you )?.{0,15}feel|\bwellbeing\b|\bmood\b',event['text'],re.I))


def reports_wellbeing(text):
    # This conservative coverage check recognises explicit self-report, not
    # feelings inferred from walking speed, pauses, stairs or practical help.
    return bool(re.search(r'\b(?:i|my|we)\b.{0,70}\b(?:feel|felt|feeling|tired|exhausted|energy|sleep|slept|mood|worried|anxious|calm|happy|sad|enjoyed|overwhelmed|unwell|well|okay|ok|sore|pain)\b|\b(?:good|difficult|rough|quiet)\s+week\b',text,re.I))


def wellbeing_gap(event,context):
    intent=event.get('interpretation',{}).get('intent')
    if intent!='checkup' and not (intent is None and event.get('type')=='checkup-email'): return None
    if not asks_general_wellbeing(event) or any(reports_wellbeing(source['text']) for source in context): return None
    detail=('The retrieved notes provide partial context about activities, but do not establish how you felt over the week. ' if context else 'No relevant self-reported wellbeing observations were found for the requested period. ')
    return {'id':'journal-context','label':'How have you felt over the past week?','detail':detail+'How have you felt over the past week? Add your own answer in Journal, then send a follow-up. No complete reply has been invented.'}


def reply_required(event):
    text=event['text']
    if re.search(r'\bno\s+(?:email\s+)?reply\b|\bdo not\s+(?:email|reply|respond)\b|\breply\s+(?:is\s+)?not\s+(?:needed|required)\b',text,re.I): return False
    if re.search(r'\b(?:please\s+)?(?:reply|respond)\s+(?:with|to\s+(?:me|us))\b|\bsend\s+(?:me|us)\s+(?:an?\s+|your\s+)?(?:update|summary)',text,re.I): return True
    if re.search(r'\b(?:bring|take)\b.{0,100}\b(?:summary|account|update|observations)\b',text,re.I|re.S): return False
    routing=event.get('routing',{})
    if event.get('interpretation',{}).get('intent')=='checkup' and routing.get('status')=='accepted' and routing.get('applied_route') in ('reply_draft','visit_summary'):
        return routing['applied_route']=='reply_draft'
    if re.search(r'how have you been|how (?:are|have) you (?:been )?feel|how you are feeling|managing day to day|\b(?:reply|respond)\b|\bsend\s+(?:me|us)\s+(?:an?\s+|your\s+)?(?:update|summary)',text,re.I): return True
    facts=event.get('interpretation',{})
    quote=facts.get('response_quote')
    return bool(facts.get('response_mode')=='reply' and quote and quote in text and '?' in quote)


def validate_sentences(items,context):
    if not 1<=len(items)<=4: raise ValueError('Provide one to four short cited synthesis sentences')
    known={source['note_id']:source for source in context};result=[]
    stop=set('i my me we our the a an and or to from at on in of for with by as was were is am are it this that has have had been week during while about described reported noted use used using need needed'.split())
    aliases={'walking':'walk','walked':'walk','walks':'walk','stopped':'stop','stops':'stop','stopping':'stop','pauses':'stop','paused':'stop','pause':'stop','twice':'two','rested':'rest','rests':'rest','resting':'rest','sat':'rest','sitting':'rest','breaks':'rest','minutes':'minute','stairs':'stair','carries':'carry','carried':'carry','helped':'help','helping':'help','supported':'help','support':'help'}
    def words(value): return {aliases.get(word,word) for word in re.findall(r'[a-z]+|\d+',value.lower()) if word not in stop}
    for item in items:
        row=item.model_dump() if isinstance(item,SummarySentence) else SummarySentence.model_validate(item).model_dump()
        ids=row['source_ids'];quotes=row['evidence_quotes'];text=row['text'].strip()
        if len(ids)!=len(quotes) or len(set(ids))!=len(ids) or any(id not in known for id in ids): raise ValueError('Cite only retrieved source IDs with corresponding exact quotes')
        if any(not quote.strip() or quote not in known[id]['text'] for id,quote in zip(ids,quotes)): raise ValueError('Evidence quotes must match the cited source exactly')
        if re.search(r'\blast night\b',text,re.I): raise ValueError('Omit source-relative last night wording; do not infer its date')
        if re.search(r'\b(?:today|yesterday|tonight|tomorrow)\b',text,re.I) and any(known[id]['date'] not in text for id in ids): raise ValueError('Historical relative-time wording needs an explicit source date anchor')
        if chr(0x2014) in text or re.search(r'\b(?:should|recommend|diagnos\w*|treatment|medication|prognosis|eligible|refund|clinical|cancer|worsen\w*|improv\w*)\b|https?://|@',text,re.I): raise ValueError('No advice, clinical interpretation or unsupported outcome claims')
        supported=words(' '.join(quotes));claim=words(text)
        supported.update(words(' '.join(known[id]['date'] for id in ids)))
        if 'stop' in supported: supported.add('rest')
        if 'partner' in supported and ('carry' in supported or 'walk' in supported): supported.add('help')
        if claim-supported: raise ValueError('Use simple grounded wording; unsupported content needs revision')
        if any(text==known[id]['text'].strip() for id in ids): raise ValueError('Compose a short synthesis instead of pasting an entire source note')
        result.append({'text':text,'source_ids':ids,'sources':[{'note_id':id,'date':known[id]['date'],'source':known[id]['source']} for id in ids]})
    return result


def edit_reply(store,id,subject,body):
    subject=subject.strip();body=body.strip()
    if not 1<=len(subject)<=160 or not 1<=len(body)<=6000 or re.search(r'[\r\n\x00-\x1f\x7f]',subject) or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]',body) or chr(0x2014) in subject+body:
        raise ValueError('Use a short single-line subject and plain-text body without control characters or em dashes')
    with LOCK,store.connect() as connection:
        row=connection.execute('SELECT payload,result,sending,obsolete FROM drafts WHERE id=?',(id,)).fetchone()
        if not row: raise LookupError('Draft not found')
        old=json.loads(row[0])
        if old['kind']!='checkin_reply': raise ValueError('Only check-in reply drafts can be edited here')
        if row[1] or row[2] or row[3]: raise PermissionError('Delivered, sending or superseded drafts cannot be edited')
        allowed_recipient(old['recipient'])
        if store.digest(old)!=old['digest']: raise PermissionError('Draft attachments changed; prepare and review again')
        found=connection.execute('SELECT payload FROM cases WHERE id=?',(old.get('case_id'),)).fetchone()
        case=json.loads(found[0]) if found else None
        if case and (case['status'] not in ('ready','complete') or id not in case['draft_ids']): raise PermissionError('Review the current prepared case before editing')
        if subject==old['subject'] and body==old['body']:
            public=next(draft for draft in store.drafts() if draft['id']==id)
            return {'draft':public,'previous_draft_id':id,'case':case}
        new={key:value for key,value in old.items() if key not in ('id','digest')}
        new.update(subject=subject,body=body,edited_from=id,edit_revision=old.get('edit_revision',0)+1)
        digest=store.digest(new);new.update(id=digest[:24],digest=digest)
        connection.execute('INSERT INTO drafts(id,payload) VALUES (?,?)',(new['id'],json.dumps(new)))
        connection.execute('UPDATE drafts SET obsolete=1,approved=NULL WHERE id=?',(id,))
        if case:
            case['draft_ids']=[new['id'] if draft_id==id else draft_id for draft_id in case['draft_ids']]
            for action in case['actions']:
                if action.get('draft_id')==id: action['draft_id']=new['id']
            case['status']='ready';case['updated_at']=now()
            connection.execute('UPDATE cases SET payload=? WHERE id=?',(json.dumps(case),case['id']))
        return {'draft':{**new,'approved':False,'result':None,'sending':False,'obsolete':False},'previous_draft_id':id,'case':case}
