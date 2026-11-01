import json
from pathlib import Path
import pytest
from pypdf import PdfReader
from app.tools import (extract_attendance, calendar_event, fill_claim, evidence_checklist,
                       claim_deadline, ingest_diary, retrieve_diary, cited_answer,
                       draft_employer, assert_private, send_message, status_screen,
                       load_trust,prepare_claim_email)
from app.store import Store

@pytest.fixture
def store(tmp_path):
    return Store(tmp_path)

def test_extraction_has_exact_line_provenance():
    text = Path('fixtures/attendance.txt').read_text()
    result = extract_attendance(text)
    assert result['next_appointment']['value'] == '2026-11-11T14:00:00+00:00'
    for field in result.values():
        assert text.splitlines()[field['line']-1] == field['quote']
    with pytest.raises(ValueError):
        extract_attendance(text.replace('Next appointment:', 'Unknown:'))

def test_calendar_travel_and_idempotency(store):
    a = extract_attendance(Path('fixtures/attendance.txt').read_text())
    first = calendar_event(store, a)
    assert first == calendar_event(store, a)
    assert 'DTSTART:20261111T131000Z' in Path(first['path']).read_text()

def test_fill_official_pdf_and_no_bank_details(store):
    a = extract_attendance(Path('fixtures/attendance.txt').read_text())
    result = fill_claim(store, a)
    reader = PdfReader(result['path'])
    fields = reader.get_fields()
    assert fields[result['field_map']['first_name']]['/V'] == 'Ade'
    assert fields[result['field_map']['surname']]['/V'] == 'Demo'
    for name in result['bank_fields']:
        assert not fields[name].get('/V')
    # The official template misspells the two applicant signature field names.
    signatures={'4A signture','4B signture','4A Signature date - day',
                '4A Signature date - month','4A Signature date - year',
                '4B Signature date - day','4B Signature date - month','4B Signature date - year',
                'Name in capitals','Step 2 Signature Date - day','Step 2 Signature Date - month',
                'Step 2 Name in capitals','Authorisation'}
    assert signatures<=set(fields)
    assert all(not fields[name].get('/V') for name in signatures)
    assert 'Confirm Check Box' in fields
    assert all(field.get('/V') in (None,'','/Off') for field in fields.values() if field.get('/FT')=='/Btn')
    widgets=[annotation.get_object() for page in reader.pages for annotation in page.get('/Annots',[])]
    assert all(widget.get('/AS') in (None,'/Off') for widget in widgets if widget.get('/FT')=='/Btn')
    assert result['refund_status'] == 'refund not yet confirmed'
    assert result['estimate'] == '£8.40 estimate - synthetic receipt, subject to verification'

def test_checklist_and_deadline(store):
    assert claim_deadline('2026-11-30') == '2027-02-28'
    assert all(x['present'] for x in evidence_checklist(store, claim_exists=True))

def test_trust_adapter_can_be_selected_from_another_yaml(store,tmp_path,monkeypatch):
    from app import tools
    adapters=tmp_path/'config/trusts';adapters.mkdir(parents=True)
    (adapters/'example-trust.yaml').write_text('''id: example-trust
name: Synthetic Example Trust
destination_env: TEST_UCLH_EMAIL
required_documents: [attendance, travel, claim_form]
claim_form_label: Unsigned synthetic example trust draft
''')
    evidence=tmp_path/'fixtures/evidence';evidence.mkdir(parents=True)
    for name in ('attendance','travel'): (evidence/f'{name}.txt').write_text('SYNTHETIC evidence')
    pdf=tmp_path/'draft.pdf';pdf.write_bytes(b'SYNTHETIC PDF fixture')
    store.put('claim',{'path':str(pdf)})
    monkeypatch.setattr(tools,'ROOT',tmp_path)
    assert load_trust('example-trust')['name']=='Synthetic Example Trust'
    explicit=evidence_checklist(store,True,trust_id='example-trust')
    assert [item['id'] for item in explicit]==['attendance','travel','claim_form']
    assert all(item['present'] for item in explicit)
    assert explicit[-1]['label']=='Unsigned synthetic example trust draft'
    monkeypatch.setenv('TRUST_ID','example-trust')
    assert load_trust()['id']=='example-trust'
    assert evidence_checklist(store,True)==explicit
    draft=prepare_claim_email(store)
    assert draft['recipient']=='uclh@example.test'
    assert draft['attachments']==[str(pdf),str(evidence/'attendance.txt'),str(evidence/'travel.txt')]

@pytest.mark.parametrize('trust_id',['../uclh','uclh/../../secret','/tmp/secret','uclh.yaml','', 'Uppercase'])
def test_trust_adapter_rejects_invalid_or_traversing_identifiers(trust_id):
    with pytest.raises(ValueError,match='trust identifier'): load_trust(trust_id)

def test_trust_adapter_rejects_symlink_escape_and_unsafe_document_names(tmp_path,monkeypatch):
    from app import tools
    adapters=tmp_path/'config/trusts';adapters.mkdir(parents=True)
    outside=tmp_path/'outside.yaml';outside.write_text('id: escape')
    (adapters/'escape.yaml').symlink_to(outside)
    monkeypatch.setattr(tools,'ROOT',tmp_path)
    with pytest.raises(ValueError,match='trust path'): load_trust('escape')
    (adapters/'unsafe.yaml').write_text('id: unsafe\nname: Synthetic\ndestination_env: TEST_UCLH_EMAIL\nrequired_documents: [../secret]\n')
    with pytest.raises(ValueError,match='required_documents'): load_trust('unsafe')

def test_ingest_and_retrieval(store):
    ingest_diary(store)
    ingest_diary(store)
    assert len(store.notes()) == 3
    notes = retrieve_diary(store, 'How do you manage stairs and walking?')
    assert {x['id'] for x in notes} == {'note-1','note-2'}

def test_cited_answer_every_sentence_links_to_source(store):
    ingest_diary(store)
    result = cited_answer(store, 'How do you manage stairs and walking?')
    assert len(result['sentences']) >= 2
    for sentence in result['sentences']:
        note = next(x for x in store.notes() if x['id'] == sentence['note_id'])
        assert sentence['text'] in note['transcript']
        assert sentence['date'] == note['timestamp'][:10]
        assert sentence['source'] == '/api/notes/' + note['id']

def test_employer_privacy_and_diary_fact(store):
    ingest_diary(store)
    a = extract_attendance(Path('fixtures/attendance.txt').read_text())
    draft = draft_employer(store, a)
    assert 'personal appointments' in draft['body']
    assert draft['source_note'] == 'note-3'
    assert_private(draft['subject'] + draft['body'])
    for term in ['UCLH','cancer','chemotherapy','hospital','treatment','oncology','diagnosis']:
        with pytest.raises(ValueError):
            assert_private(term)

def test_send_refused_without_approval(store):
    draft = store.draft('employer','manager@example.test','Time away','Personal appointment',[])
    with pytest.raises(PermissionError):
        send_message(store, draft['id'])
    assert not list(store.root.glob('outbox/*'))

def test_approval_bound_to_content_and_single_use(store):
    draft = store.draft('employer','manager@example.test','Time away','Personal appointment',[])
    store.approve(draft['id'], draft['digest'])
    result = send_message(store, draft['id'])
    assert result['delivery'] == 'local outbox only'
    assert send_message(store, draft['id']) == result
    assert len(list(store.root.glob('outbox/*.eml'))) == 1

def test_tampered_attachment_refuses(store):
    p = store.root/'evidence.txt'; p.write_text('first')
    draft = store.draft('claim','uclh@example.test','Claim','Synthetic claim',[str(p)])
    store.approve(draft['id'],draft['digest'])
    p.write_text('changed')
    with pytest.raises(PermissionError): send_message(store,draft['id'])

def test_missing_attachment_cannot_be_approved(store):
    evidence=store.root/'evidence.txt';evidence.write_text('SYNTHETIC evidence')
    draft=store.draft('claim','uclh@example.test','Claim','Synthetic claim',[str(evidence)])
    evidence.unlink()
    with pytest.raises(PermissionError): store.approve(draft['id'],draft['digest'])
    assert not store.drafts()[0]['approved']

def test_real_nhs_address_never_allowed(store):
    with pytest.raises(ValueError):
        store.draft('claim','someone@nhs.net','Claim','Body',[])

@pytest.mark.parametrize('recipient',[
    'someone@nhs.net','someone@sub.nhs.net','someone@nhs.uk',
    'someone@uclh.nhs.uk','someone@nhs.scot','someone@sub.nhs.scot',
    'someone@NHS.NET',
])
def test_nhs_address_block_overrides_explicit_configuration(store,monkeypatch,recipient):
    monkeypatch.setenv('TEST_UCLH_EMAIL',recipient)
    with pytest.raises(ValueError):
        store.draft('claim',recipient,'Claim','Body',[])

@pytest.mark.parametrize('recipient',[
    'one@example.test,two@example.test','Demo <one@example.test>',
    'one@example.test\r\nBcc: two@example.test','one@example.test.',
])
def test_recipient_configuration_must_be_one_plain_mailbox(store,monkeypatch,recipient):
    monkeypatch.setenv('TEST_UCLH_EMAIL',recipient)
    with pytest.raises(ValueError):
        store.draft('claim',recipient,'Claim','Body',[])

def test_delivery_uses_the_exact_attachment_bytes_checked_for_approval(store,monkeypatch):
    from email import policy
    from email.parser import BytesParser
    path=store.root/'evidence.txt';path.write_bytes(b'approved evidence')
    draft=store.draft('claim','uclh@example.test','Claim','Synthetic claim',[str(path)])
    store.approve(draft['id'],draft['digest'])
    original=Path.read_bytes
    def change_after_read(target):
        content=original(target)
        if target==path: path.write_bytes(b'unapproved replacement')
        return content
    monkeypatch.setattr(Path,'read_bytes',change_after_read)
    send_message(store,draft['id'])
    message=BytesParser(policy=policy.default).parsebytes(original(store.root/'outbox'/f"{draft['id']}.eml"))
    assert next(message.iter_attachments()).get_payload(decode=True)==b'approved evidence'

def test_mutating_body_invalidates_approval(store):
    draft=store.draft('employer','manager@example.test','Time away','Personal appointment',[])
    store.approve(draft['id'],draft['digest'])
    draft['body']='Changed after approval'
    with store.connect() as connection:
        connection.execute('UPDATE drafts SET payload=? WHERE id=?',(json.dumps(draft),draft['id']))
    with pytest.raises(PermissionError): send_message(store,draft['id'])

def test_status_not_confirmed(store):
    assert status_screen(store)['refund_status'] == 'refund not yet confirmed'
    assert status_screen(store)['delivery_mode']=='local-outbox'
