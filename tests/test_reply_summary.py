import asyncio,json
from unittest.mock import MagicMock
import pytest
from app import cases,incoming
from app.store import Store


def ready_run(store,text):
    event=incoming.source_event(store,text);response=cases.register_event(store,event)
    facts=asyncio.run(incoming.extract_facts(event))
    case=cases.get_case(store,response['case_id']);case['status']='ready'
    run=cases.CaseRun(store,{**event,'interpretation':facts},case)
    run.read_event();run.context('walking station',7)
    return run


def sentences():
    return [{'text':'Walking to the station took twenty minutes, with two stops and a rest on a bench.','source_ids':['note-2'],'evidence_quotes':['Walking from home to the station took me twenty minutes today. I stopped twice and sat on the bench by the shops.']}]


def test_grounded_question_reply_and_bring_update_have_different_outcomes(tmp_path):
    question=ready_run(Store(tmp_path/'question'),'SYNTHETIC. Please reply with a summary of walking and stairs this past week.')
    result=question.wellbeing('Answer the weekly question from dated observations.',sentences())
    assert result['summary_mode']=='agent-synthesis' and result['reply_required']
    assert result['summary_sentences'][0]['sources'][0]['note_id']=='note-2'
    draft=question.store.draft_payload(result['draft_id'])
    assert draft['kind']=='checkin_reply' and draft['recipient']=='uclh@example.test' and draft['attachments']==[]
    assert sentences()[0]['text'] in draft['body']
    assert not question.store.drafts()[0]['approved'] and not question.store.drafts()[0]['result']
    bring=ready_run(Store(tmp_path/'bring'),'SYNTHETIC. Please bring an update about getting around to the next visit.')
    internal=bring.wellbeing('Bring a generated update to the next visit.',sentences())
    assert not internal['reply_required'] and not internal.get('draft_id') and bring.store.drafts()==[]
    from app.synthesis import reply_required
    assert not reply_required({'text':'How have you been? No email reply needed; bring an update to the next visit.'})
    assert not reply_required({'text':'How have you been? Do not reply to this message.'})
    assert reply_required({'text':'Please reply with an update and bring it to the next visit.'})


@pytest.mark.parametrize('change',['source','quote','invented','advice'])
def test_synthesis_rejects_unretrieved_or_unsupported_claims(tmp_path,change):
    run=ready_run(Store(tmp_path),'SYNTHETIC. Please reply with a summary of walking and stairs this past week.');items=sentences()
    if change=='source': items[0]['source_ids']=['unretrieved-note']
    elif change=='quote': items[0]['evidence_quotes']=['I ran ten miles.']
    elif change=='invented': items[0]['text']='I walked ten miles without help.'
    else: items[0]['text']='You should change your medication.'
    with pytest.raises(ValueError): run.wellbeing('Try a summary.',items)
    assert run.case['actions']==[] and run.store.drafts()==[]


def test_reply_edit_requires_new_exact_approval_and_delivered_copy_is_immutable(tmp_path):
    from app import synthesis,tools
    store=Store(tmp_path);run=ready_run(store,'SYNTHETIC. Please reply with a summary of walking and stairs this past week.')
    result=run.wellbeing('Reply to the question.',sentences());cases.save_case(store,run.case)
    old=store.draft_payload(result['draft_id']);store.approve(old['id'],old['digest'])
    edited=synthesis.edit_reply(store,old['id'],'SYNTHETIC update','My reviewed synthetic reply.')
    new=edited['draft']
    assert new['id']!=old['id'] and new['digest']!=old['digest'] and not new['approved']
    assert edited['case']['draft_ids']==[new['id']]
    assert edited['case']['actions'][0]['draft_id']==new['id']
    persisted=cases.get_case(store,run.case['id'])
    assert persisted['draft_ids']==[new['id']]
    assert persisted['actions'][0]['draft_id']==new['id']
    with pytest.raises(PermissionError): store.approve(old['id'],old['digest'])
    with pytest.raises(PermissionError): tools.send_message(store,old['id'])
    with pytest.raises(PermissionError): store.approve(new['id'],old['digest'])
    store.approve(new['id'],new['digest']);tools.send_message(store,new['id'])
    assert b'My reviewed synthetic reply.' in (store.root/'outbox'/(new['id']+'.eml')).read_bytes()
    with pytest.raises(PermissionError): synthesis.edit_reply(store,new['id'],'Another subject','A changed delivered body.')
    assert store.draft_payload(new['id'])['body']=='My reviewed synthetic reply.'


def test_reply_patch_api_keeps_csrf_and_recipient_immutable(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    store=Store(tmp_path);run=ready_run(store,'SYNTHETIC. Please reply with a summary of walking and stairs this past week.')
    action=run.wellbeing('Reply.',sentences());cases.save_case(store,run.case)
    monkeypatch.setattr(main,'store',store)
    with TestClient(main.app) as client:
        csrf={'x-demo-csrf':client.get('/api/status').json()['csrf']}
        path='/api/drafts/'+action['draft_id']
        assert client.patch(path,json={'subject':'Subject','body':'Body'}).status_code==403
        assert client.patch(path,json={'subject':'Subject','body':'Body','recipient':'other@example.test'},headers=csrf).status_code==422
        response=client.patch(path,json={'subject':'Subject','body':'Body'},headers=csrf)
        assert response.status_code==200 and response.json()['draft']['recipient']=='uclh@example.test'


def test_empty_weekly_context_can_finish_with_actionable_missing_notes(tmp_path):
    store=Store(tmp_path);run=ready_run(store,'SYNTHETIC. Please reply with a summary of walking and stairs this past week.')
    run.case['context']=[]
    action=run.clarify('No relevant dated notes were found; an update cannot be invented.')
    assert action['status']=='needs-information'
    assert run.case['missing_evidence'][0]['id']=='journal-context'
    assert run.is_complete() and store.drafts()==[]
    run.case['context']=[{'note_id':'note-2','text':'An available observation.'}]
    assert not run.is_complete()


def test_composed_paraphrase_can_combine_supported_pauses_and_partner_help(tmp_path):
    run=ready_run(Store(tmp_path),'SYNTHETIC. Please reply with a summary of walking and stairs this past week.')
    run.context('walking stairs',7)
    items=[{'text':'I needed pauses while walking and using the stairs, with help from my partner.','source_ids':['note-1','note-2'],'evidence_quotes':['I use the handrail on the stairs at home. I stop on the landing before going up the second flight. My partner carries the shopping upstairs.','Walking from home to the station took me twenty minutes today. I stopped twice and sat on the bench by the shops. My partner walked with me.']}]
    result=run.wellbeing('Compose the supported observations.',items)
    assert result['summary_sentences'][0]['text']==items[0]['text']


def test_historical_today_cannot_be_presented_as_current(tmp_path):
    run=ready_run(Store(tmp_path),'SYNTHETIC. Please reply with a summary of walking and stairs this past week.');items=sentences()
    items[0]['text']='Walking to the station took twenty minutes today.'
    with pytest.raises(ValueError,match='relative'): run.wellbeing('A stale relative-time phrase.',items)
    assert run.store.drafts()==[]


def test_general_weekly_question_with_function_only_notes_reports_partial_gap(tmp_path):
    run=ready_run(Store(tmp_path),'SYNTHETIC. How have you been this past week? Have you noticed changes in how you feel or manage day to day?')
    assert run.case['context']
    action=run.wellbeing('Answer the general weekly question.',sentences())
    assert action['kind']=='clarification' and action['status']=='needs-information'
    assert run.case['missing_evidence'][0]['id']=='journal-context'
    assert 'partial' in run.case['missing_evidence'][0]['detail'].lower()
    assert run.is_complete() and run.store.drafts()==[]
    assert 'Journal' in run.administrative_summary()


def test_actual_self_reported_wellbeing_evidence_allows_a_cited_reply(tmp_path):
    run=ready_run(Store(tmp_path),'SYNTHETIC. How have you been this past week?')
    run.case['context']=[{'note_id':'wellbeing-synthetic','date':'2026-10-30','text':'I felt tired this week. I enjoyed a quiet afternoon with my family.','source':'/api/notes/wellbeing-synthetic'}]
    items=[{'text':'I felt tired and enjoyed a quiet afternoon with my family.','source_ids':['wellbeing-synthetic'],'evidence_quotes':['I felt tired this week. I enjoyed a quiet afternoon with my family.']}]
    action=run.wellbeing('Answer from the actual wellbeing observations.',items)
    assert action['kind']=='wellbeing-summary' and action['reply_required']
    assert action['summary_sentences'][0]['text']==items[0]['text']
    assert len(run.store.drafts())==1


def test_bench_rest_is_not_wellbeing_and_appointment_missing_facts_are_preserved():
    from app.synthesis import reports_wellbeing,wellbeing_gap
    assert not reports_wellbeing('I stopped and rested on a bench.')
    assert reports_wellbeing('I felt rested after sleeping well.')
    event={'text':'How have you been? Your appointment will be sometime next week.','interpretation':{'intent':'appointment','missing_info':[{'id':'appointment-date'}]}}
    assert wellbeing_gap(event,[]) is None


def test_historical_last_night_is_never_carried_into_generated_reply(tmp_path):
    run=ready_run(Store(tmp_path),'SYNTHETIC. How have you been this past week?')
    run.case['context']=[{'note_id':'wellbeing-synthetic','date':'2026-10-31','text':'I slept well last night. I felt calm after a quiet afternoon.','source':'/api/notes/wellbeing-synthetic'}]
    items=[{'text':'I slept well last night.','source_ids':['wellbeing-synthetic'],'evidence_quotes':['I slept well last night.']}]
    with pytest.raises(ValueError,match='relative'): run.wellbeing('Answer with the dated observation.',items)
    assert run.store.drafts()==[]
