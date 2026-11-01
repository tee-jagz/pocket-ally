import asyncio
from email import policy
from email.parser import BytesParser
from pathlib import Path
import pytest
from app.store import Store
from app.tools import poll_attendance,prepare_claim_email,fill_claim
from app.workflow import run_preparation,approve_and_send

def test_poll_inbox_and_claim_pack(tmp_path):
    store=Store(tmp_path)
    a=poll_attendance(store)
    assert store.get('email')['id']=='synthetic-attendance-001'
    fill_claim(store,a)
    d=prepare_claim_email(store)
    assert len(d['attachments'])==4

def test_complete_core_journey_and_separate_approvals(tmp_path):
    store=Store(tmp_path)
    asyncio.run(run_preparation(store))
    assert store.get('phase')=='awaiting-approval'
    assert len(store.drafts())==2
    assert not list(tmp_path.glob('outbox/*'))
    claim=next(d for d in store.drafts() if d['kind']=='claim')
    asyncio.run(approve_and_send(store,claim['id'],claim['digest']))
    assert store.get('phase')=='awaiting-approval'
    assert not next(d for d in store.drafts() if d['kind']=='employer')['approved']
    message=BytesParser(policy=policy.default).parsebytes(next((tmp_path/'outbox').glob('*.eml')).read_bytes())
    assert len(list(message.iter_attachments()))==4
    employer=next(d for d in store.drafts() if d['kind']=='employer')
    asyncio.run(approve_and_send(store,employer['id'],employer['digest']))
    assert store.get('phase')=='complete'
    assert all(d['approved'] and d['result'] for d in store.drafts())
    assert store.get('answer')['sentences']
    events=store.events()
    assert any(e['kind']=='tool-start' for e in events)
    assert any(e['kind']=='tool-end' for e in events)
    assert sum(e['kind']=='approval' for e in events)==2

def test_error_is_stuck_and_not_cheerful(tmp_path,monkeypatch):
    from app import tools
    monkeypatch.setattr(tools,'poll_attendance',lambda s: (_ for _ in ()).throw(ValueError('bad email')))
    store=Store(tmp_path)
    asyncio.run(run_preparation(store))
    assert store.get('phase')=='error'
    assert store.get('mascot')=='stuck'
    assert not store.drafts()
