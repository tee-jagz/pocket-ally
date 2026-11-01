"""Ordered workflow: prepare freely, send only from an explicit UI approval."""
import asyncio, os
from app import tools as t
from app.store import LOCK

async def step(store,name,state,fn):
    store.put('mascot',state); store.event('tool-start',name,state)
    try:
        result=await asyncio.to_thread(fn)
        store.event('tool-end',name,'planning','Completed')
        return result
    except Exception:
        store.put('mascot','stuck'); store.event('tool-error',name,'stuck','Stopped safely; inspect configuration and retry')
        raise

async def run_preparation(store):
    store.put('phase','running'); store.put('error',None)
    try:
        a=await step(store,'Read attendance email','reading',lambda:t.poll_attendance(store))
        await step(store,'Plan next appointment','planning',lambda:t.calendar_event(store,a))
        await step(store,'Fill claim draft','filling',lambda:t.fill_claim(store,a))
        await step(store,'Prepare claim email','filling',lambda:t.prepare_claim_email(store))
        diary=await step(store,'Read voice diary','reading',lambda:t.ingest_diary(store)); store.put('diary',diary)
        if t.live():
            # Model tools can only prepare a safe employer draft and extract cited evidence.
            # No approval or send operation exists in the agent's tool set.
            from app.agent import prepare_with_agent
            await prepare_with_agent(store)
        else:
            await step(store,'Draft manager email','planning',lambda:t.draft_employer(store,a))
            await step(store,'Find cited diary evidence','reading',lambda:t.cited_answer(store,'How do you manage stairs and walking?'))
        store.put('phase','awaiting-approval'); store.put('mascot','waiting')
        store.event('ready','Review your drafts','waiting','Nothing has been sent. Two separate approvals are required.')
    except Exception as exc:
        store.put('phase','error'); store.put('mascot','stuck')
        store.put('error',f'{type(exc).__name__}: preparation stopped. Check service configuration; no automatic send retry.')

async def approve_and_send(store,id,digest):
    payload=store.draft_payload(id)
    case_id=payload.get('case_id') if payload else None
    if case_id:
        from app.cases import get_case,save_case
        case=get_case(store,case_id)
        if case['status'] not in ('ready','complete') or id not in case['draft_ids']: raise ValueError('Review the current prepared case before approving')
        approved_revision=case['revision']
    elif store.get('phase') not in ('awaiting-approval','complete'): raise ValueError('Finish preparation before approving')
    store.approve(id,digest)
    await step(store,'Send approved draft','sending',lambda:t.send_message(store,id))
    if case_id:
        with LOCK:
            case=get_case(store,case_id)
            if case['revision']==approved_revision and case['status'] in ('ready','complete'):
                if all(draft['result'] for draft in store.drafts() if draft['id'] in case['draft_ids']): case['status']='complete'
                save_case(store,case)
        return
    done=all(x['result'] for x in store.drafts())
    store.put('mascot','done' if done else 'waiting'); store.put('phase','complete' if done else 'awaiting-approval')
