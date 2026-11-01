# Submission checklist: 1 November 2026, London

The [Builders Guide](https://warp-peach-ef6.notion.site/) was read through CUA on 1 November. Submit by **17:00 Europe/London** using the [event submission form](https://hack.outpostcrew.co/e/devday-hack-london-49b733). The four equally weighted criteria are the idea/usefulness, use of Codex, execution and demo clarity. Finalists have a two-minute presentation followed by one minute of questions.

- [x] README describes the product, local setup and the work built during the event.
- [x] Backend checks pass: latest full suite 150 tests. Actual provider and browser evidence is recorded in CODEX.md.
- [x] OpenAI generation, extraction, retrieval and synthesis use real configured services. TfL planning is live. Email remains an explicitly approved local outbox copy; no external email delivery is claimed.
- [x] Final edited-reply browser/outbox check passed in isolated QA: edited subject/body exactly matched one explicitly approved local email copy.
- [ ] Record the current working core journey in at most 90 seconds. The existing 82.44-second video shows the superseded interface and is historical only.
- [ ] Upload the current video and verify signed-out playback without permission requests.
- [ ] Publish a public GitHub repository with README/setup and what was built today, then verify signed-out access.
- [ ] Re-run `python scripts/release_check.py` and inspect tracked/staged files before publication. Keep credentials, personal recordings and generated runtime data out of Git.
- [ ] Include the solo builder's actual full name and contact details. Codex and the requested Astra/Sol agents are development assistance, not additional human team members.
- [x] Include a concrete Codex example: test-first approval binding to exact message and attachment bytes, including rejection after an attachment changes. A second example is the live-QA-discovered reply persistence bug, corrected with a regression that reloads SQLite rather than asserting only returned memory.
- [x] Credit the official NHS form, libraries, documentation and generated artwork in CREDITS.md.
- [ ] If supplying a deployed app link, provide usable access instructions and verify judges can open it. The current Tailscale preview is private, not a public deployment.
- [ ] Submit before 17:00 London; the form and guide do not themselves authorise publishing or sending on the builder's behalf.

Public repository URL: not published yet.
Current public video URL: not uploaded yet.
Builder full name and contact: to be supplied by the builder.

Suggested current video focus: synthetic journal observations, a natural weekly check-in, relevant retrieved context, a composed reply, one edit and exact approval of the local outbox copy. Keep Demo input separate from Tasks results. Show the real working flow and label any edited waiting time; do not imply the approved local copy was emailed externally.
