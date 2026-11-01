import json
import pytest
from app.store import Store


@pytest.mark.parametrize('protected',['approved','sending','delivered',None])
def test_copy_migration_preserves_protected_drafts_and_refreshes_pending(tmp_path,protected):
    store=Store(tmp_path);old=chr(0x2014)
    evidence=tmp_path/'attendance.txt'
    evidence.write_text('SYNTHETIC DEMO EVIDENCE ONLY '+old+' not valid proof.\n')
    draft=store.draft('claim','uclh@example.test','SYNTHETIC DEMO '+old+' travel claim draft','Synthetic claim',[str(evidence)])
    if protected=='approved': store.approve(draft['id'],draft['digest'])
    if protected in ('sending','delivered'):
        with store.connect() as connection:
            if protected=='sending': connection.execute('UPDATE drafts SET sending=1 WHERE id=?',(draft['id'],))
            else: connection.execute('UPDATE drafts SET result=? WHERE id=?',(json.dumps({'delivery':'local outbox only'}),draft['id']))
    evidence.write_text('SYNTHETIC DEMO EVIDENCE ONLY - not valid proof.\n')
    store.put('claim',{'estimate':'Estimate '+old+' verify'})
    store.put('answer',{'method':'Source '+old+' wording','sentences':[{'text':'User source '+old+' unchanged'}]})
    store.migrate_product_copy()
    after=store.drafts()
    assert len(after)==1
    if protected:
        assert after[0]['id']==draft['id']
        assert store.draft_payload(draft['id'])==draft
    else:
        assert after[0]['id']!=draft['id'] and not after[0]['approved']
        assert store.digest(store.draft_payload(after[0]['id']))==after[0]['digest']
        assert old not in after[0]['subject']
    assert store.get('claim')['estimate']=='Estimate - verify'
    assert store.get('answer')['method']=='Source - wording'
    assert store.get('answer')['sentences'][0]['text']=='User source '+old+' unchanged'
    store.migrate_product_copy()
    assert store.drafts()==after


def test_copy_migration_does_not_bless_unrelated_attachment_tampering(tmp_path):
    store=Store(tmp_path);old=chr(0x2014)
    evidence=tmp_path/'attendance.txt';evidence.write_text('SYNTHETIC DEMO EVIDENCE ONLY '+old+' not valid proof.\n')
    draft=store.draft('claim','uclh@example.test','SYNTHETIC DEMO '+old+' travel claim draft','Synthetic claim',[str(evidence)])
    evidence.write_text('An unrelated unreviewed replacement')
    store.migrate_product_copy()
    assert store.draft_payload(draft['id'])==draft
