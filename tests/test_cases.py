import asyncio,json
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from app.store import Store
from app import cases


def finish(store,scenario):
    event=cases.scenario(scenario)['event']
    response=cases.register_event(store,event)
    if response.pop('_run',False): asyncio.run(cases.run_registered(store,event['id']))
    return cases.get_case(store,response['case_id'])


def test_replay_and_reschedule_keep_same_visit_and_calendar_without_reverting(tmp_path):
    store=Store(tmp_path)
    original=finish(store,'confirmed-visit')
    updated=finish(store,'reschedule')
    assert original['id']==updated['id']
    assert updated['appointment']=='2026-11-13T14:00:00+00:00'
    assert len([action for action in updated['actions'] if action['kind']=='appointment-plan'])==1
    assert finish(store,'confirmed-visit')==updated
    assert len(cases.list_cases(store)['cases'])==1
    assert len(updated['runs'])==2
    assert updated['runs'][0]['actions'][0]['appointment']=='2026-11-11T14:00:00+00:00'


def test_registered_source_ids_are_immutable(tmp_path):
    store=Store(tmp_path);case=finish(store,'checkup-email')
    changed=cases.scenario('checkup-email')['event'];changed['text']='A different source message'
    with pytest.raises(ValueError,match='distinct event identifier'): cases.register_event(store,changed)
    assert cases.get_case(store,case['id'])==case


def test_missing_receipt_resumes_same_case_and_dedupes_exact_draft(tmp_path):
    store=Store(tmp_path);initial=finish(store,'attended-visit')
    assert initial['missing_evidence'][0]['id']=='travel-receipt'
    assert initial['draft_ids']==[]
    event=cases.receipt_event(store,initial['id'])
    response=cases.register_event(store,event)
    asyncio.run(cases.run_registered(store,response['event_id']))
    resumed=cases.get_case(store,initial['id'])
    assert resumed['missing_evidence']==[]
    assert len(resumed['draft_ids'])==1
    draft=store.draft_payload(resumed['draft_ids'][0])
    assert draft['case_id']==initial['id'] and not store.drafts()[0]['approved']
    replay=cases.register_event(store,event)
    assert replay['replayed'] and not replay['_run']
    assert cases.get_case(store,initial['id'])==resumed
    assert finish(store,'attended-visit')==resumed
    draft=store.draft_payload(resumed['draft_ids'][0])
    from app.workflow import approve_and_send
    asyncio.run(approve_and_send(store,draft['id'],draft['digest']))
    delivered=cases.get_case(store,initial['id'])
    assert finish(store,'attended-visit')==delivered
    assert len(list((tmp_path/'outbox').glob('*.eml')))==1
    updated=cases.receipt_event(store,initial['id'])
    updated['id']+='-new-source';updated['text']+=' A separate copy confirms the same attended visit.'
    cases.register_event(store,updated);asyncio.run(cases.run_registered(store,updated['id']))
    reopened=cases.get_case(store,initial['id'])
    assert reopened['draft_ids']==delivered['draft_ids']
    assert len(store.drafts())==1
    assert next(action for action in reopened['actions'] if action['kind']=='claim-pack')['status']=='delivered'


def test_updated_event_revokes_obsolete_pending_approval_preserves_delivered(tmp_path):
    store=Store(tmp_path);case=finish(store,'confirmed-visit')
    pending=store.draft('employer','manager@example.test','Time away','Original appointment',[],case_id=case['id'])
    sent=store.draft('employer','manager@example.test','Time away','Already delivered',[],case_id=case['id'])
    store.approve(pending['id'],pending['digest'])
    with store.connect() as connection: connection.execute('UPDATE drafts SET result=? WHERE id=?',(json.dumps({'delivery':'local outbox only'}),sent['id']))
    finish(store,'reschedule')
    with pytest.raises(PermissionError): store.approve(pending['id'],pending['digest'])
    from app.tools import send_message
    with pytest.raises(PermissionError): send_message(store,pending['id'])
    assert store.draft_payload(sent['id'])==sent
    assert next(draft for draft in store.drafts(include_obsolete=True) if draft['id']==sent['id'])['result']


def test_running_event_is_not_started_twice(tmp_path):
    store=Store(tmp_path);event=cases.scenario('checkup-email')['event']
    assert cases.register_event(store,event)['_run']
    repeated=cases.register_event(store,event)
    assert not repeated['_run'] and repeated['status']=='running'
    with pytest.raises(ValueError,match='already has an event running'):
        cases.register_event(store,cases.scenario('confirmed-visit')['event'])


def test_model_selects_tools_from_changed_source_not_scenario_type(tmp_path,monkeypatch):
    from app import case_agent
    calls=[]
    monkeypatch.setenv('OPENAI_API_KEY','synthetic-key-for-mocked-provider')
    monkeypatch.setattr(case_agent,'function_tool',lambda function:function)
    monkeypatch.setattr(case_agent,'Agent',lambda **kwargs:SimpleNamespace(**kwargs))
    async def decide(agent,*args,**kwargs):
        tools={tool.__name__:tool for tool in agent.tools}
        event=json.loads(await tools['read_source_event']())
        await tools['retrieve_relevant_context']('walking stairs personal appointments manager',30)
        if 'appointment confirmed' in event['text'].lower():
            await tools['prepare_appointment_plan']('The message confirms an appointment date.')
            calls.append('appointment')
        else:
            await tools['prepare_wellbeing_summary']('The message asks for a sourced check-in summary.',[{'text':'I use the handrail and stop on the landing.','source_ids':['note-1'],'evidence_quotes':['I use the handrail on the stairs at home. I stop on the landing before going up the second flight.']}])
            calls.append('summary')
        assert not any('send' in name or 'approv' in name for name in tools)
        return SimpleNamespace(final_output='I will send this tomorrow and assess your clinical recovery. '*100)
    monkeypatch.setattr(case_agent.Runner,'run',decide)
    store=Store(tmp_path)
    event=cases.scenario('checkup-email')['event']
    event.update(text='SYNTHETIC appointment confirmed for the supplied date.',appointment='2026-11-11T14:00:00+00:00')
    response=cases.register_event(store,event);asyncio.run(cases.run_registered(store,event['id']))
    case=cases.get_case(store,response['case_id'])
    assert calls==['appointment']
    assert case['decision']['mode']=='agents-sdk'
    assert 'prepare_appointment_plan' in {call['tool'] for call in case['decision']['tool_calls']}
    assert 'I will' not in case['decision']['summary']
    assert 'clinical recovery' not in case['decision']['summary']
    assert case['decision']['summary'].endswith('.')
    assert all(source['text'] in next(note for note in __import__('app.journal',fromlist=['raw_entries']).raw_entries(store) if note['id']==source['note_id'])['transcript'] for source in case['context'])


def test_provider_failure_is_error_and_retry_can_resume(tmp_path,monkeypatch):
    from app import case_agent
    monkeypatch.setenv('OPENAI_API_KEY','synthetic-key-for-mocked-provider')
    async def fail(run): raise TimeoutError('synthetic provider failure')
    monkeypatch.setattr(case_agent,'interpret',fail)
    store=Store(tmp_path);case=finish(store,'checkup-email')
    assert case['status']=='error' and case['decision']['mode']=='agents-sdk'
    assert case['decision']['summary']!='Completed'
    assert cases.register_event(store,cases.scenario('checkup-email')['event'])['_run']


def test_old_actions_do_not_make_a_no_action_model_run_successful(tmp_path,monkeypatch):
    from app import case_agent
    store=Store(tmp_path);finish(store,'confirmed-visit')
    monkeypatch.setenv('OPENAI_API_KEY','synthetic-key-for-mocked-provider')
    async def no_action(run):
        run.read_event();run.context('walking stairs',30)
        run.case['decision']['summary']='No action called'
    monkeypatch.setattr(case_agent,'interpret',no_action)
    updated=finish(store,'reschedule')
    assert updated['status']=='error'
    assert updated['appointment']=='2026-11-11T14:00:00+00:00'


def test_partial_claim_retry_reuses_immutable_pdf_and_exact_draft(tmp_path,monkeypatch):
    from app import case_agent
    monkeypatch.setenv('OPENAI_API_KEY','synthetic-key-for-mocked-provider')
    attempts=[]
    async def interrupted(run):
        run.read_event();run.context('travel walking',30)
        first=run.claim('Attendance supports preparing unsigned paperwork.')
        assert run.claim('Reopen the same preparation result.')==first
        attempts.append(first)
        if len(attempts)==1: raise TimeoutError('Synthetic interruption after preparation')
        run.case['decision']['summary']='Prepared the claim for exact review.'
    monkeypatch.setattr(case_agent,'interpret',interrupted)
    store=Store(tmp_path);event=cases.scenario('attended-visit')['event'];event['receipt_available']=True
    first=cases.register_event(store,event);asyncio.run(cases.run_registered(store,event['id']))
    assert cases.get_case(store,first['case_id'])['status']=='error'
    drafts=store.drafts();assert len(drafts)==1
    pdf=Path(drafts[0]['attachments'][0]);content=pdf.read_bytes()
    assert cases.register_event(store,event)['_run']
    asyncio.run(cases.run_registered(store,event['id']))
    assert cases.get_case(store,first['case_id'])['status']=='ready'
    assert store.drafts()==drafts and pdf.read_bytes()==content


def test_context_uses_current_journal_snapshot_but_excludes_future_entries(tmp_path):
    from datetime import datetime,timedelta,timezone
    from app import journal
    store=Store(tmp_path);current=datetime.now(timezone.utc)
    for id,timestamp in [('recent',current),('future',current+timedelta(days=2))]:
        journal.save(store,{'id':'journal-'+id,'title':'Synthetic walking','timestamp':timestamp.isoformat(),'transcript':'Walking with a handrail helped me pause.','source':'journal','transcription_mode':'typed note','transcript_pending':False})
    event=cases.scenario('checkup-email')['event'];event['timestamp']=(current-timedelta(days=2)).isoformat()
    response=cases.register_event(store,event);run=cases.CaseRun(store,event,cases.get_case(store,response['case_id']))
    run.read_event();context=run.context('walking handrail',30)
    assert 'journal-recent' in {source['note_id'] for source in context}
    assert 'journal-future' not in {source['note_id'] for source in context}
    assert 'postdates' in next(source['reason'] for source in context if source['note_id']=='journal-recent')


def test_context_does_not_select_manager_note_for_common_function_words(tmp_path):
    store=Store(tmp_path);event=cases.scenario('checkup-email')['event']
    response=cases.register_event(store,event);run=cases.CaseRun(store,event,cases.get_case(store,response['case_id']))
    run.read_event();context=run.context('Please summarise how to get to the stairs and walking',30)
    assert {source['note_id'] for source in context}=={'note-1','note-2'}


def test_travel_transport_context_matches_walking_source_with_honest_topic_reason(tmp_path):
    store=Store(tmp_path);event=cases.scenario('reschedule')['event']
    response=cases.register_event(store,event);run=cases.CaseRun(store,event,cases.get_case(store,response['case_id']))
    run.read_event()
    context=run.context('travel transport day-to-day notes appointment 11 November 2026 13 November 2026 UCLH Macmillan Cancer Centre',30)
    assert 'note-2' in {source['note_id'] for source in context}
    assert 'note-3' not in {source['note_id'] for source in context}
    walking=next(source for source in context if source['note_id']=='note-2')
    assert 'Topic match' in walking['reason']
    assert 'walking' in walking['reason'] and 'travel' in walking['reason']
    assert walking['text'] in next(note for note in __import__('app.journal',fromlist=['raw_entries']).raw_entries(store) if note['id']=='note-2')['transcript']
    assert 'Matched travel' not in walking['reason']


def test_one_bounded_model_continuation_finishes_an_early_read_only_stop(tmp_path,monkeypatch):
    from app import case_agent
    monkeypatch.setenv('OPENAI_API_KEY','synthetic-key-for-mocked-provider')
    monkeypatch.setattr(case_agent,'function_tool',lambda function:function)
    monkeypatch.setattr(case_agent,'Agent',lambda **kwargs:SimpleNamespace(**kwargs))
    attempts=[]
    async def decide(agent,input,**kwargs):
        tools={tool.__name__:tool for tool in agent.tools};attempts.append((input,kwargs))
        if len(attempts)==1:
            await tools['read_source_event']()
            return SimpleNamespace(final_output='Read the email.',to_input_list=lambda:[{'role':'assistant','content':'Read the email.'}])
        await tools['retrieve_relevant_context']('walking stairs',30)
        await tools['prepare_wellbeing_summary']('The email requests a sourced observations summary.',[{'text':'I use the handrail and stop on the landing.','source_ids':['note-1'],'evidence_quotes':['I use the handrail on the stairs at home. I stop on the landing before going up the second flight.']}])
        return SimpleNamespace(final_output='Completed.')
    monkeypatch.setattr(case_agent.Runner,'run',decide)
    store=Store(tmp_path);case=finish(store,'checkup-email')
    assert case['status']=='ready' and len(attempts)==2
    assert sum(kwargs['max_turns'] for _,kwargs in attempts)<=12
    assert 'incomplete' in attempts[1][0][-1]['content']


@pytest.mark.parametrize('prepare_calendar',[False,True])
def test_turn_exhaustion_requires_both_requested_travel_and_appointment(tmp_path,monkeypatch,prepare_calendar):
    from app import case_agent,incoming
    from agents.exceptions import MaxTurnsExceeded
    from unittest.mock import AsyncMock
    store=Store(tmp_path)
    event=incoming.source_event(store,'SYNTHETIC appointment confirmed for 12 November 2026 at 11:30. Please plan my travel to arrive for this appointment.')
    facts=asyncio.run(incoming.extract_facts(event))
    monkeypatch.setattr(incoming,'extract_facts',AsyncMock(return_value=facts))
    monkeypatch.setenv('OPENAI_API_KEY','synthetic-key-for-mocked-provider')
    monkeypatch.setattr(case_agent,'function_tool',lambda function:function)
    monkeypatch.setattr(case_agent,'Agent',lambda **kwargs:SimpleNamespace(**kwargs))
    async def exhaust(agent,*args,**kwargs):
        tools={tool.__name__:tool for tool in agent.tools}
        await tools['read_source_event']()
        await tools['retrieve_relevant_context']('walking getting around pausing travel',30)
        await tools['plan_tfl_journey']('Travel was requested; missing postcodes must remain explicit.')
        if prepare_calendar:
            await tools['prepare_appointment_plan']('The confirmed date supports a plan with an explicitly unverified travel buffer.')
        raise MaxTurnsExceeded('Synthetic bounded-turn exhaustion')
    monkeypatch.setattr(case_agent.Runner,'run',exhaust)
    response=cases.register_event(store,event)
    asyncio.run(cases.run_registered(store,event['id']))
    case=cases.get_case(store,response['case_id'])
    assert case['status']==('ready' if prepare_calendar else 'error')
    assert len(list(tmp_path.rglob('appointment.ics')))==int(prepare_calendar)
    assert case['actions'][0]['kind']=='journey-plan'
    assert case['actions'][0]['status']=='needs-information'
    if prepare_calendar:
        assert 'Nothing was sent' in case['decision']['summary']
        assert case['actions'][1]['travel_checked_at'] is None
    else:
        assert case['diagnostics']['exception_type']=='MaxTurnsExceeded'


def test_case_api_and_interrupted_startup_recovery(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    import time
    store=Store(tmp_path);monkeypatch.setattr(main,'store',store)
    event=cases.scenario('checkup-email')['event'];response=cases.register_event(store,event)
    with TestClient(main.app) as client:
        assert client.get('/api/cases/'+response['case_id']).json()['status']=='error'
        assert len(client.get('/api/scenarios').json()['scenarios'])==4
        csrf=client.get('/api/status').json()['csrf'];headers={'x-demo-csrf':csrf}
        started=client.post('/api/scenarios/checkup-email/run',json={},headers=headers).json()
        assert started['case_id']==response['case_id']
        for attempt in range(100):
            case=client.get('/api/cases/'+response['case_id']).json()
            if case['status']!='running': break
            time.sleep(.01)
        assert case['status']=='ready'
        assert client.get('/api/status').json()['current_case_id']==response['case_id']
        replay=client.post('/api/scenarios/checkup-email/run',json={},headers=headers).json()
        assert replay['replayed'] and replay['status']=='ready'
        assert client.post('/api/cases/'+response['case_id']+'/evidence/receipt',json={'synthetic':True},headers=headers).status_code==409


def test_delivery_completion_does_not_overwrite_a_newer_running_case(tmp_path,monkeypatch):
    from app import tools
    from app.workflow import approve_and_send
    store=Store(tmp_path);case=finish(store,'attended-visit')
    event=cases.receipt_event(store,case['id']);cases.register_event(store,event)
    asyncio.run(cases.run_registered(store,event['id']))
    case=cases.get_case(store,case['id']);draft=store.draft_payload(case['draft_ids'][0])
    original=tools.send_message
    def finish_then_start_new_event(target,id):
        result=original(target,id)
        updated=cases.get_case(target,case['id']);updated['revision']+=1;updated['status']='running';cases.save_case(target,updated)
        return result
    monkeypatch.setattr(tools,'send_message',finish_then_start_new_event)
    asyncio.run(approve_and_send(store,draft['id'],draft['digest']))
    assert cases.get_case(store,case['id'])['status']=='running'
