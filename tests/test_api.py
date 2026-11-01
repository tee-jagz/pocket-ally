from fastapi.testclient import TestClient
from app import main
from app.store import Store

def test_browser_api_rejects_unapproved_and_cross_origin_actions(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'store',Store(tmp_path))
    with TestClient(main.app) as c:
        assert c.get('/').status_code==200
        assert c.post('/api/start',json={}).status_code==403
        state=c.get('/api/status').json()
        token=state['csrf']
        assert c.post('/api/drafts/missing/approve-send',json={'digest':'x'},headers={'x-demo-csrf':token}).status_code==403
        assert c.get('/api/status',headers={'host':'evil.example'}).status_code==403

def test_no_arbitrary_file_reads(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'store',Store(tmp_path))
    with TestClient(main.app) as c:
        assert c.get('/api/notes/unknown').status_code==404
        assert c.get('/api/outbox/unknown').status_code==404

def test_draft_attachment_review_is_indexed_and_integrity_checked(tmp_path,monkeypatch):
    store=Store(tmp_path);monkeypatch.setattr(main,'store',store)
    evidence=tmp_path/'evidence.txt';evidence.write_bytes(b'SYNTHETIC evidence')
    draft=store.draft('claim','uclh@example.test','Claim','Synthetic claim',[str(evidence)])
    url=f"/api/drafts/{draft['id']}/attachments/0"
    with TestClient(main.app) as client:
        response=client.get(url)
        assert response.status_code==200
        assert response.content==b'SYNTHETIC evidence'
        assert response.headers['content-type'].startswith('text/plain')
        assert client.get(f"/api/drafts/{draft['id']}/attachments/-1").status_code==404
        assert client.get(f"/api/drafts/{draft['id']}/attachments/1").status_code==404
        assert client.get('/api/drafts/unknown/attachments/0').status_code==404
        evidence.write_bytes(b'Changed after review')
        assert client.get(url).status_code==409
        evidence.unlink()
        assert client.get(url).status_code==409
