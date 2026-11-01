# How Codex helped

## Brief and decisions — 1 November 2026

- Began with an empty repository, no supplied fixtures, no configured services and system Python 3.9. Located the bundled Python 3.12 runtime and created an isolated environment.
- Asked only for team/configuration/fixture details. User confirmed effectively solo and authorised adapting the synthetic persona for a better demo. Ade is now a 54-year-old part-time employee, making the manager email consistent.
- Wrote the extraction, PDF, retrieval, no-send gate and employer-privacy tests before the workflow/agent loop.
- Read current official OpenAI, Google, NHSBSA and UCLH sources. Found that UCLH requests a postal form; did not portray HC5(T) alone as a verified real claim pack.
- Inspected the official form's canonical fields and widgets. Found duplicate date-field names. Filled verified unique fields, left ambiguous DOB/signatures/eligibility/bank details blank, preserved interactivity and watermarked every page as a synthetic draft.
- Split trusted orchestration from untrusted content and kept sending out of the model's tool set. The approval endpoint binds the user's tap to the exact message and attachment bytes.
- Built local fallbacks first: `.ics`, `.eml` outbox, fixture transcripts and keyword retrieval. Optional OpenAI/Google/Postgres adapters are explicit, not silently simulated successes.
- Added SSE action events, a mobile-first review screen, dated source-note links and an original eight-state CSS mascot. No supplied pre-generated art existed, so no image-model provenance is claimed.
- Avoided deadline-risk extras: no TfL, share card, microphone capture, clinical advice or expanded PIP workflow.
- The builder subsequently requested “Implementation should be with a gpt sol 6.1 high while Astra ochestrates” and “also, parallel implementation where possiibile”. Updated the earlier no-subagents rule accordingly: the human team remains solo; two GPT-6.1 Sol HIGH agents review backend/security/tests and frontend/browser verification with disjoint file ownership under Astra coordination.
- The safety review tightened recipient parsing and NHS subdomain blocks, and eliminated a file-change race by sending the same attachment bytes used for the approval check. Exact attachments now have integrity-checked review links. Live diary retrieval rejects records that do not match the ingested source notes; local fixture rows cannot be silently relabelled as live transcriptions.

## Concrete judge-friendly example

**Failure scenario:** a user reviews a claim PDF and approves an email. A later process changes that PDF before send.

**Implementation:** store a SHA-256 approval digest containing the recipient, subject, body, metadata and attachment contents. Recompute before delivery; refuse if anything changed.

**Evidence:** `tests/test_tools.py::test_tampered_attachment_refuses` writes an attachment, approves it, changes the attachment and expects `PermissionError`. `tests/test_live_contracts.py` proves the provider is never called without approval and an ambiguous timeout cannot trigger a blind retry. These are executable examples of how Codex converted a product safety requirement into working code and tests.

## Connectivity smoke results

At first smoke run, all four were unavailable due to missing configuration:

- OpenAI: `OPENAI_API_KEY` missing.
- Gmail: Google OAuth token missing.
- Calendar: Google OAuth token missing.
- pgvector: `DATABASE_URL` missing.

The builder was informed immediately after the smoke run. Local mode selected; no live calls or real sends claimed. Installation required network permission; the first synthetic speech attempt yielded empty audio under sandboxing, then succeeded using the permitted macOS speech service.

## Verification log

- Audio fixture inspection with Python's `wave` module: all three files have nonzero PCM frames, one channel and a 22,050 Hz sample rate. Durations are 8.13 seconds (`note-1.wav`), 7.93 seconds (`note-2.wav`) and 7.37 seconds (`note-3.wav`). Browser verification also exercised actual playback and confirmed the player's time advanced.
- Filled-PDF visual check: generated the draft in a separate ignored QA directory, rendered all four pages with Poppler and inspected every page. Ade's names/address/email, date, £8.40, department and hospital are visible without clipping or overlap. Bank, DOB, declaration and signature fields remain blank, and every page has the synthetic draft stamp. PNG evidence is under ignored `data/qa/filled-1.png` through `filled-4.png`.
- Backend syntax check: `.venv/bin/python -m compileall -q app tests` passed.
- Final Python suite: `.venv/bin/python -m pytest -q` passed with **50 passed in 1.34s**, exit 0, no warnings displayed. Coverage includes the complete local journey, separate approvals, content/attachment changes, delivery byte snapshots, NHS domain blocks, exact attachment previews, employer privacy and safe source citations. PDF tests verify blank signature/declaration/bank fields and unchecked eligibility/declaration fields and visual widgets.
- Completed the original adapter-structure requirement with a shared YAML loader and `TRUST_ID` configuration. Tests exercise a temporary alternative adapter plus invalid IDs, traversal, symlink escapes and unsupported evidence IDs. Only the verified UCLH adapter is shipped; recipient protections remain unchanged.
- Optional Gmail, Calendar, OpenAI and agent-tool authority tests use mocks. Re-running connectivity smoke with dependencies installed still reported all four missing configurations; no real provider call or send is claimed.
- Dependency check: `.venv/bin/pip check` passed with no broken requirements. `requirements.lock` pins the 72-package application/test dependency closure, excluding unrelated PDF QA tooling. The Agents SDK imports successfully. This is an installed-environment verification, not a second fresh-environment installation.
- Browser QA found and fixed a 4-pixel decorative overflow at 320 pixels; the claim deadline now includes its year. Passing runs checked all four exact attachment previews (including the native PDF viewer), dated notes and audio, separate approvals, local email downloads, no JavaScript errors, widths of 320/375/390/768 pixels, missing-audio fallback and a persistent error mascot on connection failure. Early harness selectors were corrected before the final passing runs. Desktop, phone, PDF, error and audio-fallback screenshots were visually inspected.
- Two clean complete rehearsals passed: 6 seconds for the automated correctness run, then 79 seconds of script execution for the recorded run. Each began ready and ended complete after two independent local approvals. The final recording used isolated port 8001 and `data/recording-state`, leaving the builder's open app on port 8000 untouched.
- The final silent captioned video is `data/browser-qa/rehearsal-2/pocket-ally-demo.webm`; its backup is `pocket-ally-demo-backup.webm` in the same directory. Independent ffmpeg input metadata measured **82.44 seconds**, VP8, 1280 × 900 at 25 fps, 5,749,978 bytes. The backup SHA-256 matches exactly. The probe's attempted null output returned an unsupported-muxer error in the minimal recorder build; input metadata was successfully parsed, so no successful full-file decode is claimed from that probe.
- Saved-video playback check passed in Chrome without touching the app: metadata duration 82.44 seconds, 1280 × 900, `readyState=4`, no media error. Playback advanced to 0.3201 seconds; seeking to 79 seconds and resuming advanced to 79.3223 seconds with no error. Chrome decoded 90 frames (7 dropped during the rapid seek/play check). A near-end frame was saved and visually inspected, showing the completed local-outbox record and unconfirmed refund. This is a bounded playback/seek check, not an uninterrupted watch of the entire video.
- Pre-commit source inspection: 46 staged files, whitespace/diff check and heuristic secret-pattern scan passed. Generated run state, screenshots and recordings remain ignored. Final documentation is restaged before the local commit.
- The builder confirmed GitHub is not set up yet. Public repository and public video links remain pending; no external publication or anonymous-access verification is claimed.
