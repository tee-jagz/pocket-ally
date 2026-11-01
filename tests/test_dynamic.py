import asyncio
from datetime import datetime,timezone
from types import SimpleNamespace
from unittest.mock import MagicMock,AsyncMock
import pytest
from app.store import Store
from app import cases,incoming,retrieval,tfl,journal


def test_input_fingerprints_reopen_and_edits_target_same_visit_without_preset_metadata(tmp_path):
    store=Store(tmp_path)
    original=incoming.source_event(store,'SYNTHETIC appointment confirmed on 11 November 2026 at 14:00.','','',None)
    first=cases.register_event(store,original);asyncio.run(cases.run_registered(store,original['id']))
    duplicate=incoming.source_event(store,original['text'],'','',original['visit_id'])
    assert duplicate==original
    assert cases.register_event(store,duplicate)['replayed']
    edited=incoming.source_event(store,'SYNTHETIC appointment moved to 13 November 2026 at 10:00.','','',original['visit_id'])
    assert edited['id']!=original['id'] and edited['visit_id']==original['visit_id']
    assert 'appointment' not in edited and 'attended' not in edited
    response=cases.register_event(store,edited);asyncio.run(cases.run_registered(store,edited['id']))
    case=cases.get_case(store,response['case_id'])
    assert case['appointment']=='2026-11-13T10:00:00+00:00'
    plan=next(action for action in case['actions'] if action['kind']=='appointment-plan')
    assert plan['is_reschedule'] and plan['previous_appointment']=='2026-11-11T14:00:00+00:00'
    assert case['interpretation']['appointment_quote'] in edited['text']


def test_unvalidated_model_date_and_ambiguous_message_never_make_a_plan(tmp_path):
    store=Store(tmp_path)
    event=incoming.source_event(store,'SYNTHETIC appointment is sometime next week.','','',None)
    forged=incoming.Facts(intent='appointment',intent_quote='appointment',appointment='2026-11-13T10:00:00+00:00',appointment_quote='next week',hospital=None,department=None,receipt_available=False)
    validated=incoming.validate_facts(event,forged,'responses')
    assert validated['appointment'] is None and validated['confidence']=='ambiguous'
    response=cases.register_event(store,event);asyncio.run(cases.run_registered(store,event['id']))
    case=cases.get_case(store,response['case_id'])
    assert case['missing_evidence']
    assert not case.get('appointment') and not case['draft_ids']
    assert not list(tmp_path.rglob('appointment.ics'))


def test_attendance_cannot_replace_contradicting_message_with_fixed_receipt(tmp_path):
    store=Store(tmp_path)
    event=incoming.source_event(store,'SYNTHETIC attended on 30 October 2026 at 10:30. Travel cost £100.00.\nHospital: UCLH\nDepartment: Outpatient services')
    facts=asyncio.run(incoming.extract_facts(event))
    assert 'matching-travel-evidence' in {item['id'] for item in facts['missing_info']}
    event['receipt_fixture_verified']=True
    repeated=asyncio.run(incoming.extract_facts(event))
    assert 'matching-travel-evidence' in {item['id'] for item in repeated['missing_info']}


@pytest.mark.parametrize('quote',['November 2026 at 14:00','2026 at 14:00','03/04/2026 at 14:00','13 November at 14:00'])
def test_incomplete_or_ambiguous_numeric_dates_are_not_filled_by_defaults(quote):
    assert incoming.parsed_date(quote) is None


def test_check_in_with_next_visit_is_not_misclassified_as_appointment():
    event={'text':'SYNTHETIC check-in. Before the next visit, bring a summary of walking and stairs.'}
    facts=asyncio.run(incoming.extract_facts(event))
    assert facts['intent']=='checkup' and facts['appointment'] is None


def test_standalone_weekly_question_needs_no_appointment_or_clinical_inference(tmp_path):
    store=Store(tmp_path)
    event=incoming.source_event(store,'SYNTHETIC DEMO. How have you been this past week? Have you noticed any changes in how you are feeling or managing day to day?')
    facts=asyncio.run(incoming.extract_facts(event))
    assert facts['intent']=='checkup' and facts['missing_info']==[]
    assert facts['appointment'] is None and facts['hospital'] is None
    response=cases.register_event(store,event);asyncio.run(cases.run_registered(store,event['id']))
    saved=cases.get_case(store,response['case_id'])
    assert saved['status']=='ready' and [action['kind'] for action in saved['actions']]==['clarification']
    assert saved['missing_evidence'][0]['id']=='journal-context'
    assert not saved.get('appointment') and not list(tmp_path.rglob('appointment.ics'))


def test_reschedule_without_verified_target_asks_for_existing_visit_without_another_plan(tmp_path):
    store=Store(tmp_path)
    initial=cases.scenario('confirmed-visit')['event'];cases.register_event(store,initial)
    asyncio.run(cases.run_registered(store,initial['id']))
    text='SYNTHETIC appointment moved to 13 November 2026 at 10:00.'
    event=incoming.source_event(store,text)
    response=cases.register_event(store,event);asyncio.run(cases.run_registered(store,event['id']))
    case=cases.get_case(store,response['case_id'])
    assert case['visit_assignment']=='unassigned' and case['interpretation']['requires_existing_visit']
    assert 'visit-target' in {item['id'] for item in case['missing_evidence']}
    assert not case.get('appointment') and not case['draft_ids']
    assert len(list(tmp_path.rglob('appointment.ics')))==1
    assert 'receipt' not in case['decision']['summary'].lower()
    guarded=cases.CaseRun(store,{**event,'appointment':case['interpretation']['appointment'],'interpretation':case['interpretation']},case)
    guarded.read_event();guarded.context('walking',30)
    with pytest.raises(ValueError,match='missing source facts'): guarded.appointment('A model attempts to bypass missing target validation.')
    assert 'Select the existing visit' in guarded.administrative_summary()
    assert 'receipt' not in guarded.administrative_summary().lower()
    selected=incoming.source_event(store,text,visit_id=initial['visit_id'])
    assert selected['visit_target_verified'] and selected['visit_id']==initial['visit_id']


@pytest.mark.parametrize('text,expected',[
    ('SYNTHETIC appointment on 13 November 2026 at 2pm.','2026-11-13T14:00:00+00:00'),
    ('SYNTHETIC appointment at 2026-07-10T14:00:00Z.','2026-07-10T14:00:00+00:00'),
])
def test_complete_clock_formats_keep_explicit_time_zone(text,expected):
    facts=asyncio.run(incoming.extract_facts({'text':text}))
    assert facts['appointment']==expected


def test_responses_extraction_receives_only_actual_message_and_validates_current_date(tmp_path,monkeypatch):
    import openai
    store=Store(tmp_path);text='SYNTHETIC appointment moved to 13 November 2026 at 10:00.'
    event=incoming.source_event(store,text)
    parsed=incoming.Facts(intent='reschedule',intent_quote='appointment moved',appointment='2026-11-13T10:00:00+00:00',appointment_quote='13 November 2026 at 10:00',hospital=None,department=None,receipt_available=False)
    provider=AsyncMock(return_value=SimpleNamespace(output_parsed=parsed))
    class Client:
        responses=SimpleNamespace(parse=provider)
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
    constructor=MagicMock(return_value=Client())
    monkeypatch.setattr(openai,'AsyncOpenAI',constructor)
    monkeypatch.setenv('OPENAI_API_KEY','synthetic-mocked-key')
    result=asyncio.run(incoming.extract_facts(event))
    assert result['extraction_mode']=='responses' and result['appointment']=='2026-11-13T10:00:00+00:00'
    kwargs=provider.call_args.kwargs
    assert kwargs['input']==text and kwargs['store'] is False and kwargs['text_format'] is incoming.Facts
    assert constructor.call_args.kwargs['max_retries']==0


def test_complete_source_date_survives_model_zone_annotation_and_attendance_misclassification(tmp_path):
    store=Store(tmp_path)
    text='SYNTHETIC appointment confirmed for 12 November 2026 at 11:30. Location: UCLH Macmillan Cancer Centre. Please plan my travel to arrive for this appointment.'
    event=incoming.source_event(store,text)
    wrong=incoming.Facts(intent='attendance',intent_quote='Please plan my travel to arrive for this appointment.',appointment='2026-11-12T11:30:00+00:00[Europe/London]',appointment_quote='12 November 2026 at 11:30',hospital='UCLH Macmillan Cancer Centre',department=None,receipt_available=False)
    checked=incoming.validate_facts(event,wrong,'responses')
    assert checked['appointment']=='2026-11-12T11:30:00+00:00'
    assert checked['intent']=='unclear'
    assert 'visit-intent' in {item['id'] for item in checked['missing_info']}
    assert 'attendance-department' not in {item['id'] for item in checked['missing_info']}


def test_completed_attendance_requires_past_completion_source_proof(tmp_path):
    store=Store(tmp_path);text='SYNTHETIC I attended on 28 October 2026 at 10:30. Hospital: UCLH. Department: Outpatient services.'
    event=incoming.source_event(store,text)
    facts=incoming.Facts(intent='attendance',intent_quote='I attended',appointment='2026-10-28T10:30:00+00:00',appointment_quote='28 October 2026 at 10:30',hospital='UCLH',department='Outpatient services',receipt_available=False)
    assert incoming.validate_facts(event,facts,'responses')['intent']=='attendance'


def test_observations_request_with_contextual_appointment_finishes_as_summary(tmp_path,monkeypatch):
    from app import case_agent
    store=Store(tmp_path)
    for name in ('confirmed-visit','reschedule'):
        event=cases.scenario(name)['event'];cases.register_event(store,event);asyncio.run(cases.run_registered(store,event['id']))
    text='SYNTHETIC DEMO. Before your appointment on 13 November 2026 at 14:00, please bring a short account of walking, stairs and getting around.'
    event=incoming.source_event(store,text,visit_id='visit-next-001')
    facts=incoming.Facts(intent='checkup',intent_quote='please bring a short account of walking, stairs and getting around',appointment='2026-11-13T14:00:00+00:00',appointment_quote='13 November 2026 at 14:00',hospital=None,department=None,receipt_available=False)
    validated=incoming.validate_facts(event,facts,'responses')
    monkeypatch.setattr(incoming,'extract_facts',AsyncMock(return_value=validated))
    monkeypatch.setenv('OPENAI_API_KEY','synthetic-mocked-key')
    monkeypatch.setattr(case_agent,'function_tool',lambda function:function)
    monkeypatch.setattr(case_agent,'Agent',lambda **kwargs:SimpleNamespace(**kwargs))
    async def decide(agent,*args,**kwargs):
        tools={tool.__name__:tool for tool in agent.tools}
        await tools['read_source_event']();await tools['retrieve_relevant_context']('walking stairs getting around',30)
        await tools['prepare_wellbeing_summary']('The primary request is to bring personal observations; the visit date is context.',[{'text':'I use the handrail and stop on the landing.','source_ids':['note-1'],'evidence_quotes':['I use the handrail on the stairs at home. I stop on the landing before going up the second flight.']}])
        return SimpleNamespace(final_output='Completed.')
    monkeypatch.setattr(case_agent.Runner,'run',decide)
    response=cases.register_event(store,event);asyncio.run(cases.run_registered(store,event['id']))
    case=cases.get_case(store,response['case_id'])
    assert case['status']=='ready' and case['interpretation']['intent']=='checkup'
    assert [action['kind'] for action in case['actions']]==['wellbeing-summary']
    assert case['missing_evidence']==[] and case['appointment']=='2026-11-13T14:00:00+00:00'
    assert len(list(tmp_path.rglob('appointment.ics')))==1


def test_semantic_cosine_cache_is_real_and_note_edits_use_new_content_hash(tmp_path,monkeypatch):
    from app import integrations
    store=Store(tmp_path);monkeypatch.setenv('OPENAI_API_KEY','synthetic-mocked-key')
    vectors={'getting around':[1.,0.,0.],'Walking slowly to the station.':[.9,.1,0.],'My manager knows about appointments.':[0.,1.,0.],'I stayed indoors.':[0.,0.,1.]}
    provider=MagicMock(side_effect=lambda text:vectors[text]);monkeypatch.setattr(integrations,'embed_many',lambda texts:[provider(text) for text in texts])
    notes=[{'id':'mobility','transcript':'Walking slowly to the station.'},{'id':'manager','transcript':'My manager knows about appointments.'}]
    ranked,meta=retrieval.rank(store,'getting around',notes,limit=2)
    assert [row['note']['id'] for row in ranked]==['mobility']
    assert meta['mode']=='openai-embeddings' and ranked[0]['score']>.9
    retrieval.rank(store,'getting around',notes,limit=2)
    assert provider.call_count==3
    notes[0]['transcript']='I stayed indoors.'
    updated,no_match=retrieval.rank(store,'getting around',notes,limit=2)
    assert updated==[] and provider.call_count==4
    assert no_match['mode']=='openai-embeddings' and 'threshold' in no_match['notice']
    provider.side_effect=TimeoutError()
    _,failed=retrieval.rank(store,'new query',notes,limit=2)
    assert failed['mode']=='lexical-provider-unavailable'


def test_semantic_search_bounds_sources_and_batches_uncached_vectors(tmp_path,monkeypatch):
    from app import integrations
    store=Store(tmp_path);monkeypatch.setenv('OPENAI_API_KEY','synthetic-mocked-key')
    provider=MagicMock(side_effect=lambda texts:[[1.,0.] for text in texts])
    monkeypatch.setattr(integrations,'embed_many',provider)
    notes=[{'id':str(index),'timestamp':f'2026-10-{index%28+1:02d}T10:00:00+00:00','transcript':str(index)+' '+('synthetic '*400)} for index in range(40)]
    _,metadata=retrieval.rank(store,'A paraphrased synthetic question',notes)
    assert provider.call_count==1
    inputs=provider.call_args.args[0]
    assert len(inputs)<=33 and all(len(text)<=2000 for text in inputs)
    assert metadata['searched_sources']==32 and metadata['eligible_sources']==40


def test_journal_recall_uses_semantics_for_paraphrase_and_keeps_exact_sources(tmp_path,monkeypatch):
    from app import integrations
    store=Store(tmp_path);monkeypatch.setenv('OPENAI_API_KEY','synthetic-mocked-key')
    def embedding(text):
        return [1.,0.] if 'getting around' in text or 'Walking from home' in text else [0.,1.]
    monkeypatch.setattr(integrations,'embed_many',lambda texts:[embedding(text) for text in texts])
    result=journal.recall(store,'What did I record about getting around?')
    assert result['retrieval']['mode']=='openai-embeddings'
    assert result['sentences'] and {sentence['note_id'] for sentence in result['sentences']}=={'note-2'}
    assert all(sentence['text'] in next(note for note in journal.raw_entries(store) if note['id']=='note-2')['transcript'] for sentence in result['sentences'])


def test_tfl_contract_uses_fixed_host_arrival_time_and_never_claims_step_free(monkeypatch):
    response=SimpleNamespace(status_code=200,json=lambda:{'journeys':[{'duration':43,'startDateTime':'2026-11-11T12:50:00','arrivalDateTime':'2026-11-11T13:33:00','legs':[{'duration':5,'mode':{'id':'walking'},'instruction':{'summary':'Walk to the station'},'departureTime':'2026-11-11T12:50:00','arrivalTime':'2026-11-11T12:55:00','distance':250}]}]})
    response.raise_for_status=lambda:None
    provider=MagicMock(return_value=response);monkeypatch.setattr(tfl.httpx,'get',provider)
    result=tfl.plan('E15 1AA','WC1E 6AG','2026-11-11T14:00:00+00:00',avoid_stairs=True)
    args=provider.call_args
    assert args.args[0]=='https://api.tfl.gov.uk/Journey/JourneyResults/E15%201AA/to/WC1E%206AG'
    assert args.kwargs['params']['timeIs']=='Arriving'
    assert args.kwargs['params']['journeyPreference']=='LeastWalking'
    assert result['journeys'][0]['walking_minutes']==5
    assert result['query']['accessibilityPreference']==['NoSolidStairs']
    assert result['journeys'][0]['departure'].endswith('+00:00')
    assert 'not' in result['notice'].lower() and 'guarantee' in result['notice'].lower()
    with pytest.raises(ValueError): tfl.plan('https://evil.test','WC1E 6AG','2026-11-11T14:00:00+00:00')
    assert provider.call_count==1


def test_tfl_london_time_has_bst_offset_and_selected_route_updates_same_calendar(tmp_path,monkeypatch):
    assert tfl.london_time('2026-07-10T12:50:00')=='2026-07-10T12:50:00+01:00'
    store=Store(tmp_path);event=cases.scenario('confirmed-visit')['event']
    event.update(origin='E15 1AA',destination='WC1E 6AG')
    response=cases.register_event(store,event);run=cases.CaseRun(store,event,cases.get_case(store,response['case_id']))
    run.read_event();run.context('walking stairs',30);initial=run.appointment('Source confirms a visit date.')
    file=tmp_path/'cases'/response['case_id']/'appointment.ics';first=file.read_text()
    journey={'mode':'tfl-live-response','checked_at':'2026-11-01T16:00:00+00:00','source':'https://api.tfl.gov.uk/Journey/JourneyResults/E15%201AA/to/WC1E%206AG',
             'query':{'date':'20261111','time':'1400'},'notice':tfl.NOTICE,'selected_index':0,
             'journeys':[{'departure':'2026-11-11T12:50:00+00:00','arrival':'2026-11-11T13:33:00+00:00','duration_minutes':43,'walking_minutes':5}]}
    monkeypatch.setattr(tfl,'plan',lambda *args,**kwargs:journey)
    run.journey('The message supplies postcodes for travel planning.')
    assert 'DTSTART:20261111T125000Z' in file.read_text()
    assert next(line for line in first.splitlines() if line.startswith('UID:')) in file.read_text()
    assert len([action for action in run.case['actions'] if action['kind']=='appointment-plan'])==1
    monkeypatch.setattr(tfl,'plan',lambda *args,**kwargs:{**journey,'mode':'unavailable','journeys':[]})
    run.journey('A repeat check is unavailable.')
    assert 'DTSTART:20261111T131000Z' in file.read_text()
    assert '50 minute travel buffer' in file.read_text()


def test_editable_message_api_returns_during_extraction_and_preserves_actual_source(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from app import main,case_agent
    import threading,time
    store=Store(tmp_path);monkeypatch.setattr(main,'store',store)
    release=threading.Event()
    original=incoming.extract_facts
    async def slow_extract(event):
        while not release.is_set(): await asyncio.sleep(.005)
        return await original(event)
    monkeypatch.setattr(incoming,'extract_facts',slow_extract)
    with TestClient(main.app) as client:
        status=client.get('/api/status').json();headers={'x-demo-csrf':status['csrf']}
        assert status['capabilities']['editable_messages']
        text='SYNTHETIC appointment confirmed on 11 November 2026 at 14:00.'
        response=client.post('/api/events/run',json={'text':text,'synthetic':True},headers=headers)
        assert response.status_code==200 and response.json()['status']=='running'
        id=response.json()['case_id']
        active=client.get('/api/cases/'+id).json()
        assert active['active_stage']['id']=='extracting-message'
        assert active['events'][-1]['text']==text
        release.set()
        for attempt in range(100):
            case=client.get('/api/cases/'+id).json()
            if case['status']!='running': break
            time.sleep(.01)
        assert case['status']=='ready' and case['active_stage'] is None
        assert case['interpretation']['appointment']=='2026-11-11T14:00:00+00:00'
        assert client.post('/api/events/run',json={'text':text,'synthetic':True,'visit_id':case['visit_id']},headers=headers).json()['replayed']
        assert client.post('/api/events/run',json={'text':text,'synthetic':False},headers=headers).status_code==422
