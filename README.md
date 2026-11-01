# Pocket Ally

**A little less to carry.**

A phone-first companion for adults living with cancer and their partners. Turn daily notes and incoming messages into sourced replies, visit plans and paperwork. You control what is shared.

*Built at DevDay Exchange London with Codex. Synthetic UK demo; approved messages stay in a local outbox.*

## A look inside

| Home | Tasks | Journal |
|---|---|---|
| <img src="docs/screenshots/home.jpg" alt="Home and next action" width="210"> | <img src="docs/screenshots/tasks.jpg" alt="Sourced results and draft review" width="210"> | <img src="docs/screenshots/journal.jpg" alt="Record, write and recall notes" width="210"> |

| Companion | Demo |
|---|---|
| <img src="docs/screenshots/companion.jpg" alt="Choose a visual companion" width="210"> | <img src="docs/screenshots/demo.jpg" alt="Editable synthetic incoming messages" width="210"> |

Screens captured from isolated synthetic data.

## How it works

- Record or write everyday observations, keeping the original audio and editable text.
- Submit an incoming message. Pocket Ally finds relevant dated notes and prepares a supported result, or asks for missing information.
- Inspect sources, edit the draft and approve the exact version saved to the local outbox.

```mermaid
flowchart TD
    Message["Incoming message"] --> Facts["OpenAI Responses API<br/>validated facts"]
    Message --> Route["OpenAI Decisions API<br/>bounded output route"]
    Facts --> Agent["Agents SDK + Responses API<br/>preparation tools"]
    Route --> Agent
    Agent --> Context["Embeddings API<br/>relevant dated context"]
    Journal["Journal"] --> Context
    Context --> Result["Sourced reply, visit plan<br/>or paperwork"]
    Result --> Review["User edits + exact approval"]
    Review --> Outbox["Local .eml outbox"]
    Voice["Voice note"] --> Audio["Audio API<br/>transcription"]
    Audio --> Journal
    Agent --> Travel["TfL JourneyResults<br/>requested travel plan"]
    Travel --> Result
    Prompt["Companion prompt"] --> Images["Images API<br/>visual preview"]
    Images --> Choice["User chooses saved companion"]
```

The model has no approval or send tools. Sources remain reviewable, and editing invalidates prior approval.

## Quickstart

Requires Python 3.12. Run from the repository root:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
cp -n .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open [localhost:8000](http://127.0.0.1:8000). Without keys, fallbacks are labelled; configure `.env` to enable OpenAI features. Email stays local with `APP_MODE=local`.

[Technical setup, APIs and safety](docs/TECHNICAL.md) · [Demo guide](docs/DEMO.md) · [Submission](docs/SUBMISSION.md) · [Codex build evidence](CODEX.md) · [Credits](CREDITS.md)
