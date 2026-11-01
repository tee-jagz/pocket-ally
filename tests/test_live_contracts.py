"""Mocked adapter contracts; these are not live connectivity verification."""
import asyncio
import base64
from email.message import EmailMessage
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from app.store import Store
from app.tools import send_message


def test_live_send_requires_confirmed_throwaway(monkeypatch,tmp_path):
    monkeypatch.setenv('APP_MODE','live')
    with pytest.raises(ValueError):
        Store(tmp_path).draft('claim','uclh@example.test','subject','body',[])

def test_live_send_gate_calls_provider_only_once(monkeypatch,tmp_path):
    monkeypatch.setenv('APP_MODE','live')
    monkeypatch.setenv('CONFIRM_THROWAWAY_ACCOUNTS','true')
    monkeypatch.setenv('TEST_EMPLOYER_EMAIL','owned-demo@example.com')
    from app import integrations
    provider=MagicMock(return_value='test-msg-1')
    monkeypatch.setattr(integrations,'gmail_send',provider)
    store=Store(tmp_path)
    d=store.draft('employer','owned-demo@example.com','Time away','Personal appointment',[])
    with pytest.raises(PermissionError): send_message(store,d['id'])
    provider.assert_not_called()
    store.approve(d['id'],d['digest'])
    assert send_message(store,d['id'])['message_id']=='test-msg-1'
    send_message(store,d['id']); provider.assert_called_once()

def test_ambiguous_live_delivery_blocks_retry(monkeypatch,tmp_path):
    monkeypatch.setenv('APP_MODE','live');monkeypatch.setenv('CONFIRM_THROWAWAY_ACCOUNTS','true')
    monkeypatch.setenv('TEST_EMPLOYER_EMAIL','owned-demo@example.com')
    from app import integrations
    provider=MagicMock(side_effect=TimeoutError())
    monkeypatch.setattr(integrations,'gmail_send',provider)
    store=Store(tmp_path);d=store.draft('employer','owned-demo@example.com','Time away','Personal appointment',[])
    store.approve(d['id'],d['digest'])
    with pytest.raises(TimeoutError):send_message(store,d['id'])
    with pytest.raises(PermissionError):send_message(store,d['id'])
    provider.assert_called_once()

def test_gmail_poll_returns_plain_source_and_provider_id(monkeypatch):
    from app import integrations
    message=EmailMessage();message['Subject']='SYNTHETIC UCLH';message.set_content('SYNTHETIC attendance fixture')
    provider=MagicMock()
    provider.users.return_value.messages.return_value.list.return_value.execute.return_value={'messages':[{'id':'fixture-1'}]}
    provider.users.return_value.messages.return_value.get.return_value.execute.return_value={
        'raw':base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip('=')}
    monkeypatch.setattr(integrations,'google_service',lambda name:provider)
    text,id=integrations.poll_gmail()
    assert id=='fixture-1'
    assert text.strip()=='SYNTHETIC attendance fixture'

def test_gmail_poll_rejects_html_only_source(monkeypatch):
    from app import integrations
    message=EmailMessage();message.set_content('<p>SYNTHETIC attendance</p>',subtype='html')
    provider=MagicMock()
    provider.users.return_value.messages.return_value.list.return_value.execute.return_value={'messages':[{'id':'fixture-1'}]}
    provider.users.return_value.messages.return_value.get.return_value.execute.return_value={
        'raw':base64.urlsafe_b64encode(message.as_bytes()).decode()}
    monkeypatch.setattr(integrations,'google_service',lambda name:provider)
    with pytest.raises(ValueError,match='plain text'): integrations.poll_gmail()

def test_calendar_conflict_reuses_known_event_without_inviting_attendees(monkeypatch):
    from app import integrations
    provider=MagicMock()
    conflict=RuntimeError('Already exists');conflict.resp=SimpleNamespace(status=409)
    provider.events.return_value.insert.return_value.execute.side_effect=conflict
    provider.events.return_value.get.return_value.execute.return_value={'id':'known-event'}
    monkeypatch.setattr(integrations,'google_service',lambda name:provider)
    assert integrations.calendar_create('known-event','2026-11-11T13:10:00+00:00','2026-11-11T15:00:00+00:00','Synthetic hospital')=='known-event'
    insert=provider.events.return_value.insert.call_args.kwargs
    assert insert['sendUpdates']=='none'
    assert 'attendees' not in insert['body']

def test_transcription_and_embeddings_have_no_automatic_retry(monkeypatch,tmp_path):
    import openai
    from app import integrations
    constructor=MagicMock();client=constructor.return_value
    client.audio.transcriptions.create.return_value=SimpleNamespace(text='Synthetic diary words')
    client.embeddings.create.return_value=SimpleNamespace(data=[SimpleNamespace(embedding=[0.25,0.75])])
    monkeypatch.setattr(openai,'OpenAI',constructor)
    audio=tmp_path/'synthetic.wav';audio.write_bytes(b'synthetic fixture bytes')
    assert integrations.transcribe(audio)=='Synthetic diary words'
    assert client.audio.transcriptions.create.call_args.kwargs['language']=='en'
    assert client.audio.transcriptions.create.call_args.kwargs['file'].closed
    assert integrations.embed('Synthetic words')==[0.25,0.75]
    assert all(call.kwargs['max_retries']==0 for call in constructor.call_args_list)

def test_companion_image_adapter_requests_png_and_rejects_invalid_content(monkeypatch):
    import openai
    from app import integrations
    constructor=MagicMock();client=constructor.return_value
    png=b'\x89PNG\r\n\x1a\nsynthetic-fixture'
    client.images.generate.return_value=SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(png).decode())])
    monkeypatch.setattr(openai,'OpenAI',constructor)
    assert integrations.generate_companion_image('Fictional fox','soft')==png
    args=client.images.generate.call_args.kwargs
    assert args['output_format']=='png' and args['background']=='transparent'
    assert constructor.call_args.kwargs['max_retries']==0
    client.images.generate.return_value=SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(b'<script>bad</script>').decode())])
    with pytest.raises(ValueError): integrations.generate_companion_image('Fictional fox','soft')

def test_agent_exposes_only_draft_and_retrieval_tools(monkeypatch,tmp_path):
    from app import agent
    captured={}
    def construct_agent(**kwargs):
        captured.update(kwargs);return SimpleNamespace(**kwargs)
    async def run(model_agent,*args,**kwargs):
        for tool in model_agent.tools: await tool()
    monkeypatch.setattr(agent,'function_tool',lambda function:function)
    monkeypatch.setattr(agent,'Agent',construct_agent)
    monkeypatch.setattr(agent.Runner,'run',run)
    monkeypatch.setattr(agent.t,'draft_employer',lambda *args:{'id':'prepared-draft'})
    monkeypatch.setattr(agent.t,'cited_answer',lambda *args:{'sentences':[]})
    asyncio.run(agent.prepare_with_agent(Store(tmp_path)))
    assert {tool.__name__ for tool in captured['tools']}=={'prepare_manager_draft','retrieve_cited_diary_answer'}

def test_live_diary_ingest_upgrades_local_fixture_rows(monkeypatch,tmp_path):
    from app import integrations,vector
    from app.tools import ingest_diary
    store=Store(tmp_path);ingest_diary(store)
    transcriber=MagicMock(return_value='Synthetic live transcription')
    embedding=MagicMock(return_value=[0.0]*1536)
    database=MagicMock()
    monkeypatch.setattr(integrations,'transcribe',transcriber)
    monkeypatch.setattr(integrations,'embed',embedding)
    monkeypatch.setattr(vector,'VectorStore',lambda:database)
    monkeypatch.setenv('APP_MODE','live')
    result=ingest_diary(store)
    assert result['count']==3
    assert transcriber.call_count==database.upsert.call_count==3
    assert all(note['transcription_mode']=='gpt-4o-transcribe' for note in store.notes())
    ingest_diary(store)
    assert transcriber.call_count==database.upsert.call_count==3

def test_live_retrieval_rejects_unknown_or_changed_sources(monkeypatch,tmp_path):
    from app import integrations,vector
    from app.tools import ingest_diary,retrieve_diary
    store=Store(tmp_path);ingest_diary(store)
    known=store.notes()[0]
    database=MagicMock()
    database.search.return_value=[{**known,'id':'unrelated-source'},{**known,'transcript':'Changed source words'}]
    monkeypatch.setattr(vector,'VectorStore',lambda:database)
    monkeypatch.setattr(integrations,'embed',lambda text:[0.0]*1536)
    monkeypatch.setenv('APP_MODE','live')
    assert retrieve_diary(store,'How do you manage stairs and walking?')==[]
    database.search.return_value=[known]
    assert retrieve_diary(store,'How do you manage stairs and walking?')==[known]
