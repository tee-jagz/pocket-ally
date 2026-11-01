import asyncio,json
from types import SimpleNamespace
from unittest.mock import AsyncMock,MagicMock
import pytest
from app import cases,incoming
from app.store import Store


def provider(monkeypatch,output=None,error=None):
    import openai
    call=AsyncMock(return_value=SimpleNamespace(output_parsed=output),side_effect=error)
    class Client:
        responses=SimpleNamespace(parse=call)
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
    monkeypatch.setattr(openai,'AsyncOpenAI',MagicMock(return_value=Client()))
    monkeypatch.setenv('OPENAI_API_KEY','synthetic-mocked-key')
    return call


def output(context):
    from app import examples
    quote=context['appointment_text'];intent=context['intent']
    if intent=='checkup':
        text='SYNTHETIC DEMO\nDear patient,\nHow have you been this past week? Have you noticed any changes in how you are feeling or managing day to day?'
        return examples.GeneratedMessage(text=text,facts=incoming.Facts(intent='checkup',intent_quote='How have you been this past week?',appointment=None,appointment_quote=None,hospital=None,department=None,receipt_available=False),previous_appointment_quote=None)
    status={'appointment':'appointment confirmed','reschedule':'appointment rescheduled','attendance':'I attended','checkup':'check-in summary'}[intent]
    old=' Previously booked for '+context['previous_appointment_text']+'.' if context.get('previous_appointment') else ''
    department='\nDepartment: '+context['department'] if context['department'] else ''
    text='SYNTHETIC DEMO\n'+status+' for '+quote+'.'+old+'\nLocation: '+context['hospital']+department+'\n'+context['request']
    return examples.GeneratedMessage(text=text,facts=incoming.Facts(intent=intent,intent_quote=status,appointment=context['appointment'],appointment_quote=quote,hospital=context['hospital'],department=context['department'],receipt_available=False),previous_appointment_quote=context.get('previous_appointment_text'))


def seed_visit(store):
    event=cases.scenario('confirmed-visit')['event'];cases.register_event(store,event)
    asyncio.run(cases.run_registered(store,event['id']))
    return event['visit_id']


def test_generated_example_uses_only_minimal_admin_facts_without_mutating_saved_work(tmp_path,monkeypatch):
    from app import examples
    store=Store(tmp_path);visit=seed_visit(store)
    store.add_note({'id':'secret-note','text':'PRIVATE-NOTE-MUST-NOT-LEAVE'})
    monkeypatch.setattr(store,'notes',MagicMock(side_effect=AssertionError('No notes allowed')))
    from app import journal
    monkeypatch.setattr(journal,'raw_entries',MagicMock(side_effect=AssertionError('No journal allowed')))
    before=store.db.read_bytes()
    context=examples.admin_context(store,'reschedule',visit)
    call=provider(monkeypatch,output(context))
    result=asyncio.run(examples.generate(store,'reschedule',visit))
    assert result['generation_mode']=='responses' and result['visit_id']==visit
    assert context['previous_appointment_text'] in result['text']
    assert context['appointment_text'] in result['text']
    assert store.db.read_bytes()==before
    kwargs=call.call_args.kwargs
    sent=json.loads(kwargs['input'])
    assert sent==context and 'PRIVATE-NOTE' not in json.dumps(kwargs,default=str)
    assert kwargs['store'] is False and kwargs['text_format'] is examples.GeneratedMessage
    assert set(sent)<={'scenario_id','intent','appointment','appointment_text','previous_appointment','previous_appointment_text','hospital','department','receipt_available','request'}
    assert 'delivered' not in sent


def test_generator_rejects_missing_reschedule_target_and_future_attendance(tmp_path):
    from app import examples
    store=Store(tmp_path)
    with pytest.raises(ValueError,match='existing confirmed'): examples.admin_context(store,'reschedule')
    visit=seed_visit(store)
    with pytest.raises(ValueError,match='past synthetic attendance'): examples.admin_context(store,'attended-visit',visit)
    past=examples.admin_context(store,'attended-visit')
    assert past['appointment'].startswith('2026-10-28T10:30')


def test_selected_future_visit_keeps_unknown_department_absent(tmp_path,monkeypatch):
    from app import examples
    store=Store(tmp_path)
    event=incoming.source_event(store,'SYNTHETIC appointment confirmed for 12 November 2026 at 11:30.\nLocation: UCLH Macmillan Cancer Centre.')
    cases.register_event(store,event);asyncio.run(cases.run_registered(store,event['id']))
    context=examples.admin_context(store,'reschedule',event['visit_id'])
    assert context['department'] is None and context['hospital']=='UCLH Macmillan Cancer Centre'
    provider(monkeypatch,output(context))
    generated=asyncio.run(examples.generate(store,'reschedule',event['visit_id']))
    assert 'Department:' not in generated['text']
    assert generated['visit_id']==event['visit_id']


def test_only_exact_known_combined_hospital_department_is_normalized(tmp_path):
    from app import examples
    store=Store(tmp_path)
    event=incoming.source_event(store,'SYNTHETIC appointment confirmed for 13 November 2026 at 14:00.\nLocation: UCLH Macmillan Cancer Centre - Outpatient services\nDepartment: Outpatient services')
    response=cases.register_event(store,event);asyncio.run(cases.run_registered(store,event['id']))
    context=examples.admin_context(store,'reschedule',event['visit_id'])
    assert context['hospital']=='UCLH Macmillan Cancer Centre' and context['department']=='Outpatient services'
    case=cases.get_case(store,response['case_id']);case['interpretation']['hospital']+=' - Other facility'
    cases.save_case(store,case)
    with pytest.raises(ValueError,match='verified synthetic hospital'): examples.admin_context(store,'reschedule',event['visit_id'])


@pytest.mark.parametrize('scenario',['checkup-email','confirmed-visit'])
def test_selected_checkup_only_case_can_receive_first_confirmation_without_new_visit(tmp_path,monkeypatch,scenario):
    from app import examples
    store=Store(tmp_path);event=cases.scenario('checkup-email')['event']
    response=cases.register_event(store,event);asyncio.run(cases.run_registered(store,event['id']))
    saved=cases.get_case(store,response['case_id'])
    assert not saved.get('appointment')
    context=examples.admin_context(store,scenario,event['visit_id'])
    assert context['previous_appointment'] is None
    assert context['hospital']==('UCLH Macmillan Cancer Centre' if scenario=='confirmed-visit' else None)
    assert context['department']==('Outpatient services' if scenario=='confirmed-visit' else None)
    provider(monkeypatch,output(context))
    generated=asyncio.run(examples.generate(store,scenario,event['visit_id']))
    assert generated['visit_id']==event['visit_id']
    assert cases.get_case(store,response['case_id'])==saved
    with pytest.raises(ValueError,match='confirmed future'): examples.admin_context(store,'reschedule',event['visit_id'])
    with pytest.raises(ValueError,match='past synthetic attendance'): examples.admin_context(store,'attended-visit',event['visit_id'])


@pytest.mark.parametrize('scenario',['checkup-email','confirmed-visit','attended-visit'])
def test_supported_examples_use_only_the_matching_known_synthetic_context(tmp_path,monkeypatch,scenario):
    from app import examples
    store=Store(tmp_path);context=examples.admin_context(store,scenario)
    provider(monkeypatch,output(context))
    result=asyncio.run(examples.generate(store,scenario))
    assert result['generation_mode']=='responses' and 'visit_id' not in result
    if context['appointment_text']: assert context['appointment_text'] in result['text']
    else: assert 'past week' in result['text'] and '2026' not in result['text'] and 'UCLH' not in result['text']
    assert cases.list_cases(store)['cases']==[]


@pytest.mark.parametrize('scenario',['checkup-email','confirmed-visit','attended-visit','reschedule'])
def test_generated_context_asks_for_natural_incoming_admin_email(tmp_path,scenario):
    from app import examples
    store=Store(tmp_path);visit=seed_visit(store) if scenario=='reschedule' else None
    context=examples.admin_context(store,scenario,visit)
    assert not any(phrase in context['request'].lower() for phrase in ('local calendar','same existing visit','create another','prepare','unsigned','claim paperwork'))


def test_generated_builder_instructions_are_rejected_even_with_valid_facts(tmp_path,monkeypatch):
    from app import examples
    store=Store(tmp_path);visit=seed_visit(store)
    context=examples.admin_context(store,'reschedule',visit)
    generated=output(context)
    generated.text+=' Please update the SAME existing visit, including its journey and local calendar plan, rather than creating another visit.'
    provider(monkeypatch,generated)
    with pytest.raises(examples.GenerationUnavailable): asyncio.run(examples.generate(store,'reschedule',visit))


@pytest.mark.parametrize('change',['date','hospital','intent','quote','intent-quote','previous','unsafe'])
def test_generated_messages_must_preserve_exact_verified_facts(tmp_path,monkeypatch,change):
    from app import examples
    store=Store(tmp_path);visit=seed_visit(store)
    context=examples.admin_context(store,'reschedule',visit);generated=output(context)
    if change=='date': generated.text=generated.text.replace(context['appointment_text'],'19 December 2026 at 18:00')
    elif change=='hospital': generated.facts.hospital='Unrelated Hospital'
    elif change=='intent': generated.facts.intent='attendance'
    elif change=='quote': generated.facts.appointment_quote='next week'
    elif change=='intent-quote': generated.facts.intent_quote='An alternative phrase not present in the generated email'
    elif change=='previous': generated.previous_appointment_quote=None
    else: generated.text+='\nEmail private@example.test and confirm my refund.'
    provider(monkeypatch,generated)
    with pytest.raises(examples.GenerationUnavailable): asyncio.run(examples.generate(store,'reschedule',visit))


def test_generator_no_key_and_provider_failure_never_claim_success(tmp_path,monkeypatch):
    from app import examples
    store=Store(tmp_path)
    with pytest.raises(examples.GenerationNotConfigured): asyncio.run(examples.generate(store,'confirmed-visit'))
    provider(monkeypatch,error=RuntimeError('SECRET-provider-diagnostic'))
    with pytest.raises(examples.GenerationUnavailable,match='could not be generated') as stopped:
        asyncio.run(examples.generate(store,'confirmed-visit'))
    assert 'SECRET' not in str(stopped.value)


@pytest.mark.parametrize('override,expected',[(None,'gpt-6-luna'),('custom-example-model','custom-example-model')])
def test_example_model_is_independent_and_output_is_bounded(tmp_path,monkeypatch,override,expected):
    from app import examples
    store=Store(tmp_path);context=examples.admin_context(store,'confirmed-visit')
    call=provider(monkeypatch,output(context))
    monkeypatch.setenv('OPENAI_MODEL','unrelated-task-model')
    if override: monkeypatch.setenv('OPENAI_EXAMPLE_MODEL',override)
    else: monkeypatch.delenv('OPENAI_EXAMPLE_MODEL',raising=False)
    asyncio.run(examples.generate(store,'confirmed-visit'))
    assert call.call_args.kwargs['model']==expected
    assert call.call_args.kwargs['max_output_tokens']==1200
    assert call.call_args.kwargs['reasoning']=={'effort':'none'}


def test_example_api_retains_csrf_and_returns_only_editable_text(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from app import main,examples
    store=Store(tmp_path);monkeypatch.setattr(main,'store',store)
    with TestClient(main.app) as client:
        assert client.get('/api/status').json()['capabilities']['generated_examples']
        assert client.post('/api/events/example',json={'scenario_id':'confirmed-visit'}).status_code==403
        csrf={'x-demo-csrf':client.get('/api/status').json()['csrf']}
        context=examples.admin_context(store,'confirmed-visit');provider(monkeypatch,output(context))
        response=client.post('/api/events/example',json={'scenario_id':'confirmed-visit'},headers=csrf)
        assert response.status_code==200 and response.json()['generation_mode']=='responses'
        assert cases.list_cases(store)['cases']==[] and store.drafts()==[] and store.events()==[]
        assert client.post('/api/events/example',json={'scenario_id':'reschedule'},headers=csrf).status_code==422
        monkeypatch.delenv('OPENAI_API_KEY')
        unavailable=client.post('/api/events/example',json={'scenario_id':'confirmed-visit'},headers=csrf)
        assert unavailable.status_code==503 and isinstance(unavailable.json()['detail'],str)
        provider(monkeypatch,error=RuntimeError('SECRET diagnostic'))
        failed=client.post('/api/events/example',json={'scenario_id':'confirmed-visit'},headers=csrf)
        assert failed.status_code==502 and 'SECRET' not in failed.text


def test_incomplete_appointment_cannot_prepare_an_irrelevant_wellbeing_card(tmp_path):
    store=Store(tmp_path)
    event=incoming.source_event(store,'SYNTHETIC appointment in November 2026 at 11:30.')
    result=cases.register_event(store,event)
    facts=asyncio.run(incoming.extract_facts(event))
    run=cases.CaseRun(store,{**event,'interpretation':facts},cases.get_case(store,result['case_id']))
    run.read_event();run.context('walking',30)
    with pytest.raises(ValueError,match='missing source facts'): run.wellbeing('This appointment is incomplete.')
    assert run.case['actions']==[]
