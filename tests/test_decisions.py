import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock,MagicMock
import pytest


def mock_decision(monkeypatch,answer=None,error=None):
    from app import decisions
    create=AsyncMock(return_value=SimpleNamespace(answers=[answer]),side_effect=error)
    class Client:
        decisions=SimpleNamespace(create=create)
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
    monkeypatch.setattr(decisions,'_client',MagicMock(return_value=Client()))
    monkeypatch.setenv('OPENAI_API_KEY','synthetic-mocked-key')
    return create


def test_actual_decisions_contract_contains_only_incoming_message(monkeypatch):
    from app import decisions
    create=mock_decision(monkeypatch,SimpleNamespace(type='choice',name='route',choice='reply_draft',confidence=.93))
    text='SYNTHETIC. How have you been this past week?'
    result=asyncio.run(decisions.route_message(text))
    assert result['status']=='accepted' and result['route']=='reply_draft' and result['latency_ms']>=0
    kwargs=create.call_args.kwargs
    assert kwargs['model']=='gpt-6-luna' and kwargs['input']==text
    assert kwargs['questions'][0]['type']=='choice' and kwargs['questions'][0]['name']=='route'
    assert {choice['value'] for choice in kwargs['questions'][0]['choices']}=={'reply_draft','visit_summary','appointment_update','clarification'}
    assert set(kwargs)=={'model','input','questions'}


@pytest.mark.parametrize('answer,status',[(SimpleNamespace(type='refusal',name='route'),'refusal-fallback'),(SimpleNamespace(type='choice',name='route',choice='reply_draft',confidence=.2),'low-confidence-fallback')])
def test_uncertain_decision_never_claims_an_accepted_route(monkeypatch,answer,status):
    from app import decisions
    mock_decision(monkeypatch,answer)
    result=asyncio.run(decisions.route_message('SYNTHETIC update.'))
    assert result['status']==status and result['applied_route'] is None


def test_provider_failure_is_honest_and_accepted_route_affects_reply_branch(monkeypatch):
    from app import decisions,synthesis
    mock_decision(monkeypatch,error=TimeoutError('SECRET diagnostics'))
    result=asyncio.run(decisions.route_message('SYNTHETIC update.'))
    assert result['status']=='provider-unavailable-fallback' and 'SECRET' not in str(result)
    event={'text':'SYNTHETIC weekly observations update.','interpretation':{'intent':'checkup','missing_info':[]}}
    assert not synthesis.reply_required(event)
    event['routing']={'status':'accepted','route':'reply_draft','applied_route':'reply_draft'}
    assert synthesis.reply_required(event)
    event['routing']['route']='visit_summary';event['routing']['applied_route']='visit_summary'
    assert not synthesis.reply_required(event)
    event['text']='No email reply needed; bring an update to the next visit.'
    event['routing']['route']='reply_draft';event['routing']['applied_route']='reply_draft'
    assert not synthesis.reply_required(event)


def test_decisions_cannot_invent_appointment_or_interfere_with_attendance():
    from app import decisions
    route={'status':'accepted','route':'appointment_update','applied_route':'appointment_update'}
    result=decisions.constrain(route,{'intent':'checkup','appointment':None,'missing_info':[]})
    assert result['status']=='validated-source-fallback' and result['applied_route'] is None
    result=decisions.constrain(route,{'intent':'attendance','appointment':'2026-10-28T10:30:00+00:00','missing_info':[]})
    assert result['applied_route'] is None


def test_accepted_route_controls_actual_reply_draft_creation(tmp_path):
    from app import incoming,cases
    from app.store import Store
    for route in ('reply_draft','visit_summary'):
        store=Store(tmp_path/route)
        event=incoming.source_event(store,'SYNTHETIC weekly observations update.')
        facts=asyncio.run(incoming.extract_facts(event))
        result=cases.register_event(store,event);case=cases.get_case(store,result['case_id'])
        event.update(interpretation=facts,routing={'status':'accepted','route':route,'applied_route':route})
        run=cases.CaseRun(store,event,case);run.read_event();run.context('walking station',7)
        action=run.wellbeing('Use the accepted bounded route.',[{'text':'Walking to the station took twenty minutes, with two stops.','source_ids':['note-2'],'evidence_quotes':['Walking from home to the station took me twenty minutes today. I stopped twice and sat on the bench by the shops.']}])
        assert action['reply_required']==(route=='reply_draft')
        assert len(store.drafts())==int(route=='reply_draft')
        if store.drafts(): assert store.drafts()[0]['kind']=='checkin_reply' and not store.drafts()[0]['approved']
