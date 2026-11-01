"""Ordered workflow: prepare freely, send only from an explicit UI approval."""
import asyncio, os
from app import tools as t

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
    if store.get('phase') not in ('awaiting-approval','complete'): raise ValueError('Finish preparation before approving')
    store.approve(id,digest)
    await step(store,'Send approved draft','sending',lambda:t.send_message(store,id))
    done=all(x['result'] for x in store.drafts())
    store.put('mascot','done' if done else 'waiting'); store.put('phase','complete' if done else 'awaiting-approval')
