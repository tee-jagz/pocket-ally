# Credits and provenance

- Application code, UI, CSS mascot, tests and synthetic persona/email/diary/evidence were created in this repository during the hackathon on 1 November 2026 with Codex assistance. No existing application template was used.
- `fixtures/HC5-T.pdf`: unchanged NHSBSA HC5(T) V13, June 2025, downloaded 1 November 2026 from https://www.nhsbsa.nhs.uk/sites/default/files/2025-07/HC5%28T%29%20%28V13%29%20online%20-%2006.2025.pdf . Crown Copyright 2025. This existing official asset was not created at the hackathon. Source preserved; filled drafts are in ignored `data/`.
- Submission checklist adapted from UCLH's published travel-cost guidance, linked in README. No real hospital address is configured as a send target.
- Voice recordings: generated during the hackathon using macOS built-in `say` from the synthetic text in `fixtures/voice/notes.json`. Not patient recordings and not OpenAI transcription output in local mode.
- Mascot: original code-native CSS illustration created during the hackathon. Eight visual states, no image-model provenance claimed. No pre-hackathon reference image or generated mascot assets were supplied.
- Typography: installed system fonts; the app does not download or redistribute font files.
- Libraries retain upstream licences: Python, FastAPI, Uvicorn, pypdf, ReportLab, OpenAI Python/Agents SDKs, psycopg, pgvector, Google API/auth clients, PyYAML, python-dateutil, python-dotenv, pytest and httpx. Exact tested application and test package versions are in `requirements.lock`.
- Official documentation informed API usage; no Cookbook application or repository was copied wholesale.
