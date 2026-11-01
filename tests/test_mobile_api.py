from fastapi.testclient import TestClient
from app import main
from app.store import Store


def setup_client(tmp_path,monkeypatch,remote=False):
    monkeypatch.setattr(main,'store',Store(tmp_path))
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    if remote:
        monkeypatch.setenv('PUBLIC_DEMO_HOST','demo.example.test')
        monkeypatch.setenv('DEMO_ACCESS_TOKEN','synthetic-access-token-0123456789abcdef')
    return TestClient(main.app,base_url='https://demo.example.test' if remote else 'http://testserver')


def test_remote_session_is_exact_host_secure_and_same_origin(tmp_path,monkeypatch):
    with setup_client(tmp_path,monkeypatch,True) as client:
        assert client.get('/').status_code==200
        assert client.get('/api/status').status_code==401
        assert client.get('/api/companion').status_code==401
        assert client.get('/api/status',headers={'Host':'other.example.test'}).status_code==403
        assert client.get('/api/status',headers={'Host':'localhost','X-Forwarded-For':'203.0.113.8','X-Forwarded-Host':'demo.example.test'}).status_code==403
        origin={'Origin':'https://demo.example.test'}
        assert client.post('/api/session',json={'token':'wrong'},headers=origin).status_code==403
        assert client.post('/api/session',json={'token':'synthetic-access-token-0123456789abcdef'},headers={'Origin':'https://evil.example'}).status_code==403
        response=client.post('/api/session',json={'token':'synthetic-access-token-0123456789abcdef'},headers=origin)
        assert response.status_code==200
        cookie=response.headers['set-cookie'].lower()
        assert 'secure' in cookie and 'httponly' in cookie and 'samesite=strict' in cookie
        status=client.get('/api/status');assert status.status_code==200
        assert status.headers['cache-control']=='no-store'
        csrf=status.json()['csrf']
        payload={'transcript':'Synthetic walking note','synthetic':True}
        assert client.post('/api/journal',json=payload,headers=origin).status_code==403
        assert client.post('/api/journal',json=payload,headers={'x-demo-csrf':csrf}).status_code==403
        assert client.post('/api/journal',json=payload,headers={**origin,'x-demo-csrf':csrf}).status_code==200


def test_access_link_bootstraps_session_and_redirects_to_clean_url(tmp_path,monkeypatch):
    with setup_client(tmp_path,monkeypatch,True) as client:
        assert client.get('/api/status').status_code==401
        response=client.get('/access/synthetic-access-token-0123456789abcdef',follow_redirects=False)
        assert response.status_code==303
        assert response.headers['location']=='/'
        cookie=response.headers['set-cookie'].lower()
        assert 'secure' in cookie and 'httponly' in cookie and 'samesite=strict' in cookie
        assert response.headers['cache-control']=='no-store'
        assert response.headers['referrer-policy']=='no-referrer'
        assert client.get('/api/status').status_code==200
        client.cookies.clear()
        assert client.get('/api/status').status_code==401


def test_invalid_access_link_is_generic_uncached_and_does_not_authenticate(tmp_path,monkeypatch):
    with setup_client(tmp_path,monkeypatch,True) as client:
        response=client.get('/access/invalid-synthetic-token',follow_redirects=False)
        assert response.status_code==403
        assert 'invalid-synthetic-token' not in response.text
        assert 'set-cookie' not in response.headers
        assert response.headers['cache-control']=='no-store'
        assert response.headers['referrer-policy']=='no-referrer'
        assert client.get('/api/status').status_code==401
        blocked=client.get('/access/synthetic-access-token-0123456789abcdef',headers={'Host':'other.example.test'},follow_redirects=False)
        assert blocked.status_code==403 and 'set-cookie' not in blocked.headers


def test_opt_in_tailscale_identity_requires_trusted_peer_and_keeps_mutation_guards(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'store',Store(tmp_path))
    monkeypatch.setenv('PUBLIC_DEMO_HOST','demo.example.test')
    monkeypatch.setenv('TAILSCALE_ALLOWED_LOGIN','synthetic-login@example.test')
    trusted={'Tailscale-User-Login':'synthetic-login@example.test',
             'X-Forwarded-Proto':'https','X-Forwarded-Host':'demo.example.test'}
    with TestClient(main.app,base_url='https://demo.example.test',client=('127.0.0.1',50000)) as client:
        response=client.get('/api/status',headers=trusted)
        assert response.status_code==200
        assert not client.cookies
        assert client.get('/api/status').status_code==401
        assert client.get('/api/status',headers={key:value for key,value in trusted.items() if key!='Tailscale-User-Login'}).status_code==401
        assert client.get('/api/status',headers={**trusted,'Tailscale-User-Login':'other@example.test'}).status_code==401
        assert client.get('/api/status',headers={**trusted,'X-Forwarded-Proto':'http'}).status_code==401
        assert client.get('/api/status',headers={**trusted,'X-Forwarded-Host':'other.example.test'}).status_code==401
        assert client.get('/api/status',headers={**trusted,'Host':'other.example.test'}).status_code==403
        payload={'transcript':'Synthetic journal note','synthetic':True}
        assert client.post('/api/journal',json=payload,headers={**trusted,'Origin':'https://demo.example.test'}).status_code==403
        csrf=response.json()['csrf']
        assert client.post('/api/journal',json=payload,headers={**trusted,'x-demo-csrf':csrf,'Origin':'https://other.example.test'}).status_code==403
        assert client.post('/api/journal',json=payload,headers={**trusted,'x-demo-csrf':csrf,'Origin':'https://demo.example.test'}).status_code==200
        monkeypatch.delenv('TAILSCALE_ALLOWED_LOGIN')
        assert client.get('/api/status',headers=trusted).status_code==401
    monkeypatch.setenv('TAILSCALE_ALLOWED_LOGIN','synthetic-login@example.test')
    with TestClient(main.app,base_url='https://demo.example.test',client=('203.0.113.8',50000)) as client:
        assert client.get('/api/status',headers=trusted).status_code==401


def test_audio_provider_failure_preserves_pending_recording(tmp_path,monkeypatch):
    from app import integrations
    from unittest.mock import MagicMock
    with setup_client(tmp_path,monkeypatch) as client:
        monkeypatch.setenv('OPENAI_API_KEY','synthetic-key-for-mocked-provider')
        provider=MagicMock(side_effect=TimeoutError())
        monkeypatch.setattr(integrations,'transcribe',provider)
        csrf=client.get('/api/status').json()['csrf']
        headers={'x-demo-csrf':csrf,'Content-Type':'audio/mp4','X-Synthetic':'true','X-Audio-Duration':'10'}
        data=b'\x00\x00\x00\x18ftypisomsynthetic'
        response=client.post('/api/journal/audio',content=data,headers=headers)
        assert response.status_code==200
        entry=response.json()['entry']
        assert entry['transcript_pending'] and 'provider unavailable' in entry['transcription_mode']
        assert client.get(entry['audio_url']).content==data
        provider.assert_called_once()
        provider.side_effect=None;provider.return_value='I rested after a synthetic walk.'
        completed=client.post('/api/journal/audio',content=data,headers=headers).json()['entry']
        assert not completed['transcript_pending']
        assert completed['transcription_mode']=='gpt-4o-transcribe'
        assert completed['transcript']=='I rested after a synthetic walk.'


def test_generated_companion_image_is_private_and_selection_is_explicit(tmp_path,monkeypatch):
    from app import integrations
    from unittest.mock import MagicMock
    with setup_client(tmp_path,monkeypatch,True) as client:
        headers={'Origin':'https://demo.example.test'}
        client.post('/api/session',json={'token':'synthetic-access-token-0123456789abcdef'},headers=headers)
        headers['x-demo-csrf']=client.get('/api/status').json()['csrf']
        monkeypatch.setenv('OPENAI_API_KEY','synthetic-key-for-mocked-provider')
        image=b'\x89PNG\r\n\x1a\nsynthetic-fixture'
        monkeypatch.setattr(integrations,'generate_companion_image',MagicMock(return_value=image))
        preview=client.post('/api/companion/preview',json={'prompt':'Friendly fictional fox','style':'minimal'},headers=headers).json()['preview']
        assert preview['mode']=='openai-generated'
        assert client.get('/api/companion').json()['saved'] is None
        assert client.get(preview['image_url']).content==image
        client.cookies.clear()
        assert client.get(preview['image_url']).status_code==401


def test_unavailable_image_provider_returns_honest_unsaved_local_preview(tmp_path,monkeypatch):
    from app import integrations
    from unittest.mock import MagicMock
    with setup_client(tmp_path,monkeypatch) as client:
        monkeypatch.setenv('OPENAI_API_KEY','synthetic-key-for-mocked-provider')
        monkeypatch.setattr(integrations,'generate_companion_image',MagicMock(side_effect=TimeoutError()))
        csrf=client.get('/api/status').json()['csrf']
        response=client.post('/api/companion/preview',json={'prompt':'Sunny fictional fox','style':'playful'},headers={'x-demo-csrf':csrf})
        assert response.status_code==200
        preview=response.json()['preview']
        assert preview['mode']=='local-personalised-preview'
        assert preview['image_url']=='/assets/companion-playful.png'
        assert 'unavailable' in preview['fallback_reason']
        assert client.get('/api/companion').json()['saved'] is None


def test_typed_journal_persists_and_never_changes_task_sources_or_drafts(tmp_path,monkeypatch):
    with setup_client(tmp_path,monkeypatch) as client:
        csrf=client.get('/api/status').json()['csrf'];headers={'x-demo-csrf':csrf}
        main.store.draft('employer','manager@example.test','Time away','Personal appointment',[])
        before=main.store.drafts()
        payload={'title':'Synthetic walk','transcript':'I walked to the station and rested on a bench.','synthetic':True}
        assert client.post('/api/journal',json={**payload,'synthetic':False},headers=headers).status_code==422
        response=client.post('/api/journal',json=payload,headers=headers)
        assert response.status_code==200
        entry=response.json()['entry'];id=entry['id']
        assert entry['source']=='journal' and not entry['transcript_pending']
        assert main.store.notes()==[]
        assert client.get('/api/notes/'+id).json()['transcript']==payload['transcript']
        recall=client.post('/api/journal/recall',json={'question':'What did I do at the station?'},headers=headers).json()
        assert any(sentence['note_id']==id and sentence['text'] in payload['transcript'] for sentence in recall['sentences'])
        assert recall['clinical_advice'] is False
        clinical=client.post('/api/journal/recall',json={'question':'What medication should I take?'},headers=headers).json()
        assert clinical['sentences']==[] and clinical['clinical_advice'] is False
        assert client.post('/api/journal/'+id+'/link',json={'task':'employer'},headers=headers).json()['entry']['linked_tasks']==['employer']
        assert main.store.drafts()==before and main.store.notes()==[]
        assert not list(tmp_path.glob('outbox/*'))
        assert client.post('/api/journal/'+id+'/link',json={'task':'unknown'},headers=headers).status_code==422
        assert client.patch('/api/journal/note-1',json={'transcript':'Changed fixture','synthetic':True},headers=headers).status_code==403
        assert client.get('/api/status').json()['dashboard']['journal_count']>=4
    with setup_client(tmp_path,monkeypatch) as client:
        assert any(entry['id']==id for entry in client.get('/api/journal').json()['entries'])


def test_audio_upload_bounds_pending_transcript_and_manual_patch(tmp_path,monkeypatch):
    with setup_client(tmp_path,monkeypatch) as client:
        csrf=client.get('/api/status').json()['csrf']
        headers={'x-demo-csrf':csrf,'Content-Type':'audio/webm;codecs=opus','X-Synthetic':'true','X-Audio-Duration':'12'}
        assert client.post('/api/journal/audio',content=b'not an audio container',headers=headers).status_code==422
        audio=b'\x1aE\xdf\xa3'+b'synthetic-fixture'
        assert client.post('/api/journal/audio',content=audio,headers={**headers,'X-Audio-Duration':'121'}).status_code==422
        assert client.post('/api/journal/audio',content=audio,headers={**headers,'Content-Length':str(10*1024*1024+1)}).status_code==413
        response=client.post('/api/journal/audio',content=audio,headers=headers)
        assert response.status_code==200
        entry=response.json()['entry']
        assert entry['transcript_pending'] and not entry['transcript']
        assert client.get(entry['audio_url']).content==audio
        patched=client.patch('/api/journal/'+entry['id'],json={'transcript':'I rested after a synthetic walk.','synthetic':True},headers={'x-demo-csrf':csrf}).json()['entry']
        assert not patched['transcript_pending']
        assert patched['transcription_mode']=='manual transcript'
        assert client.get(entry['audio_url']).content==audio


def test_companion_preview_requires_selection_and_persists_safe_descriptor(tmp_path,monkeypatch):
    with setup_client(tmp_path,monkeypatch) as client:
        csrf=client.get('/api/status').json()['csrf'];headers={'x-demo-csrf':csrf}
        assert client.get('/api/companion').json()['saved'] is None
        preview=client.post('/api/companion/preview',json={'prompt':'A sunny synthetic fox','style':'soft'},headers=headers).json()['preview']
        assert preview['mode']=='local-personalised-preview'
        assert preview['image_url']=='/assets/companion-soft.png'
        assert set(preview['descriptor'])=={'hue','accent_hue','shape'}
        assert 0<=preview['descriptor']['hue']<360
        assert client.get('/api/companion').json()['saved'] is None
        saved=client.post('/api/companion/select',json={'preview_id':preview['id']},headers=headers).json()['saved']
        assert saved==preview
        assert client.post('/api/companion/preview',json={'prompt':'anything','style':'<script>'},headers=headers).status_code==422
        assert client.post('/api/companion/select',json={'preview_id':'unknown'},headers=headers).status_code==404
    with setup_client(tmp_path,monkeypatch) as client:
        assert client.get('/api/companion').json()['saved']==saved
