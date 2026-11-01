import pytest
@pytest.fixture(autouse=True)
def synthetic_local(monkeypatch):
    from unittest.mock import MagicMock
    monkeypatch.setattr('openai.OpenAI',MagicMock(side_effect=AssertionError('Provider calls must be explicitly mocked in tests')))
    monkeypatch.setattr('app.decisions._client',MagicMock(side_effect=AssertionError('Decisions provider calls must be explicitly mocked in tests')))
    monkeypatch.setattr('dotenv.load_dotenv',lambda *args,**kwargs:False)
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    monkeypatch.delenv('TAILSCALE_ALLOWED_LOGIN',raising=False)
    monkeypatch.setenv('APP_MODE','local')
    monkeypatch.setenv('TEST_UCLH_EMAIL','uclh@example.test')
    monkeypatch.setenv('TEST_EMPLOYER_EMAIL','manager@example.test')
    monkeypatch.setenv('TRUST_ID','uclh')
