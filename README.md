# Pocket Ally

**A little less to carry.** A synthetic UK cancer-care paperwork demo for adults and their partners. One attendance email prepares a calendar event, a travel-claim draft, a private manager email, and a diary-backed answer. Two separate approval taps control the two outgoing messages.

Built during the DevDay Exchange London Community Hackathon, 1 November 2026. Solo project with Codex. No clinical advice, symptom interpretation, benefits calculation or real patient data.

## Run locally

Requires Python 3.12. All example data is synthetic. The default works without API keys, Google OAuth or a database server.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
cp .env.example .env
python scripts/smoke.py       # missing credentials are expected in local mode
python -m pytest -q
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open [the local app](http://127.0.0.1:8000). Tap **Prepare my paperwork**, inspect the source email, calendar export and PDF, review the exact two emails, approve each separately, then open the dated diary citations. The app is deliberately restricted to loopback hosts. Do not expose it publicly: it has no multi-user authentication.

`requirements.lock` pins the verified application and test dependencies; `requirements.txt` records the allowed version ranges. The Python suite passed with 50 tests, including the complete local journey, separate approvals, attachment tampering and employer privacy. Optional provider tests use mocks; live credentials are still required for integration verification.

### What is real, and what is a fallback?

| Feature | Default `APP_MODE=local` | Optional `APP_MODE=live` |
|---|---|---|
| Inbox | Synthetic forwarded email from `fixtures/attendance.txt` | Polls Gmail for a UCLH + SYNTHETIC subject |
| Extraction | Strict labelled fields with exact source lines | Same validated extraction |
| Calendar | Downloadable `.ics`; **not** added to Google | Creates an event using Google Calendar |
| Claim | Actual NHSBSA June 2025 HC5(T), partially filled with pypdf | Same PDF preparation |
| Email | Approved `.eml` files in ignored `data/outbox` | Approved messages to exact throwaway test addresses |
| Diary | Three synthetic recordings and fixture transcripts in SQLite | `gpt-4o-transcribe`, Postgres + pgvector, `text-embedding-3-small` |
| Answer | Source-extractive paragraph; every sentence has a dated citation | Vector retrieval with the same source-extractive citation contract |
| Agent | Ordered Python workflow | Agents SDK + GPT-5-class Responses model calls the safe preparation tools |
| Mascot | Original CSS character with 8 event-driven states | Same; no live mascot image generation |

**Local mode makes no OpenAI calls.** Do not pitch it as a working live AI integration until live smoke tests and a full live rehearsal pass. The optional adapters and SDK imports are implemented; credential-dependent behavior must be verified with your accounts.

## Live configuration (optional; protect the deadline)

1. Create a throwaway Google Cloud project/account. Enable Gmail and Google Calendar APIs. Configure an OAuth consent screen with your throwaway account as a test user and create a Desktop OAuth client.
2. Save the client file as ignored `data/google-client.json`. Run `python scripts/google_auth.py` and sign in to the throwaway account. Scopes: Gmail read/send, Calendar events and Calendar list read.
3. Put `OPENAI_API_KEY`, `DATABASE_URL` and exact `TEST_UCLH_EMAIL`, `TEST_EMPLOYER_EMAIL`, `TEST_INBOX_EMAIL` values in `.env`. Never use actual NHS or employer addresses. Set `CONFIRM_THROWAWAY_ACCOUNTS=true` only for accounts you control. The NHS domain block is unconditional.
4. Start Postgres with the pgvector extension. An optional local container definition is provided in `compose.yaml`. Configure its password through `POSTGRES_PASSWORD` and the matching local `DATABASE_URL`.
5. Run `python scripts/smoke.py`. It makes a small Responses and embedding call, reads Gmail/Calendar metadata and checks vector SQL. It does not send mail or create events. All four must pass before switching `APP_MODE=live` and restarting.
6. Put the synthetic attendance email in the test inbox with UCLH and SYNTHETIC in the subject. Its plain-text body must contain the labelled fields from the fixture.
7. Use a fresh runtime directory between local and live rehearsals: stop the server and run `python scripts/reset_demo.py`. This preserves OAuth credentials while archiving synthetic run state.

`OPENAI_MODEL=gpt-5-mini` is configurable; verify account access in the smoke script. Google HTTP operations have bounded timeouts. No service failure silently becomes a success. An uncertain live send remains blocked until you inspect the test mailbox; do not blindly retry it.

## Safety and source fidelity

- Sending requires a **server-held approval bound to a SHA-256 digest** of recipient, subject, body, metadata and actual attachment bytes. The model cannot approve or send. The UI approval is protected by a same-origin token.
- Only exact configured test recipients can be used. NHS domains are blocked. Use only throwaway addresses you control; the software cannot verify a person's employment relationship.
- Calendar events have a stable ID. Local sends are idempotent. Live ambiguous delivery is held for manual inspection rather than automatically duplicated.
- Incoming email is data, never instructions. Extraction rejects missing/ambiguous labels. Employer text is a constrained template with a tested diagnosis/treatment/hospital word list.
- Every cited-answer sentence uses source wording and links to the dated note and synthetic audio. No unsupported facts are added. This is one draft paragraph, not a PIP assessment or complete form.
- No bank-details input, database column or PDF fill is provided. The official PDF's bank fields remain blank. UCLH will ask directly. Do not add real bank information to diary fixtures.
- The £8.40 is an **invented receipt-based estimate**, not a TfL fare quote or guaranteed refund. A separate fare estimate remains `[estimate pending]`.
- The deadline uses **three calendar months from payment**, including month-end handling. It is an administrative reminder, not an eligibility decision.
- UCLH accepts claims by email or post and lists attendance, entitlement, travel evidence and its postal claim form. **HC5(T) alone is not a verified complete UCLH submission.** The synthetic pack is unsigned and visibly marked NOT FOR SUBMISSION. Date of birth, declarations, entitlement and UCLH form requirements remain pending review. See the [UCLH guidance](https://www.uclh.nhs.uk/patients-and-visitors/patient-information-pages/help-travel-costs).
- SQLite stores local run state. Live diary notes additionally persist in Postgres with timestamps, audio paths and 1536-dimensional embeddings. Logs and files stay local in ignored `data/`. SDK tracing is disabled. OpenAI receives synthetic data when live mode is enabled; API `store=False` is used for the smoke Responses request.

## Architecture

`app/tools.py` contains the separately testable operations. `app/workflow.py` orders preparation and emits tool-start/tool-end/error SSE events. `app/agent.py` offers only safe draft/retrieval tools to the Agents SDK. `app/store.py` persists drafts, digest-bound approvals and the audit trail. `app/integrations.py` holds optional Google/OpenAI adapters; `app/vector.py` is the Postgres store. `config/trusts/uclh.yaml` holds submission channel, environment-based destination and evidence list.

Only UCLH is supplied and verified. Adapter selection is configuration-based: add `config/trusts/<slug>.yaml` and set `TRUST_ID=<slug>`; the default is `uclh`. The loader rejects invalid identifiers, path escapes and unsupported evidence IDs. Supported evidence IDs are `attendance`, `entitlement`, `travel` and `claim_form`. The destination variable must resolve to an existing exact-allowlisted throwaway mailbox (the synthetic adapter can reuse `TEST_UCLH_EMAIL`); an adapter cannot bypass the send gate. A new trust's real submission rules and required forms still need independent verification.

The browser is buildless HTML/CSS/minimal JavaScript and uses system fonts without external requests. No frontend package manager is required. CSS was used instead of Tailwind CDN to keep the demo functional without external assets.

## Demo, submission and attribution

See [the 80-second demo script](docs/DEMO.md), [submission checklist](docs/SUBMISSION.md), [Codex decisions and evidence](CODEX.md), and [credits](CREDITS.md). Generated runtime files and credentials are ignored. Run `python scripts/release_check.py` before publishing.

The public GitHub repository and externally accessible demo-video URL must be added after publishing with your account. No public URL is claimed by this checkout.

## Official references checked on 1 November 2026

- [Codex](https://developers.openai.com/codex) and [quickstart](https://developers.openai.com/codex/quickstart)
- [OpenAI Agents SDK tools](https://openai.github.io/openai-agents-python/tools/)
- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)
- [Transcription](https://developers.openai.com/api/docs/guides/speech-to-text), [embeddings](https://developers.openai.com/api/docs/guides/embeddings), [Cookbook](https://developers.openai.com/cookbook)
- [Gmail sending](https://developers.google.com/workspace/gmail/api/guides/sending), [Calendar events](https://developers.google.com/workspace/calendar/api/guides/create-events)
- [UCLH travel-cost guidance](https://www.uclh.nhs.uk/patients-and-visitors/patient-information-pages/help-travel-costs)
- [NHSBSA travel guidance and current linked form](https://www.nhsbsa.nhs.uk/help-travel-eye-care-wigs-and-fabric-support-costs/travel-receive-nhs-treatment)
