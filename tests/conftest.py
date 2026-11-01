import pytest
@pytest.fixture(autouse=True)
def synthetic_local(monkeypatch):
    monkeypatch.setenv('APP_MODE','local')
    monkeypatch.setenv('TEST_UCLH_EMAIL','uclh@example.test')
    monkeypatch.setenv('TEST_EMPLOYER_EMAIL','manager@example.test')
    monkeypatch.setenv('TRUST_ID','uclh')
