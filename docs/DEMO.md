# Current 90-second demo plan

Use synthetic content only. Keep the working notes-to-reply journey central. For a weekly wellbeing reply, first add an explicitly labelled synthetic self-report about how the fictional person felt. Existing walking/stairs fixtures alone should lead to a missing-wellbeing question, not an invented answer. Do not silently inject notes or present text notes as recorded audio. The [Builders Guide](https://warp-peach-ef6.notion.site/) requires a video of at most 90 seconds, with submission by 17:00 Europe/London. Public upload and a current recording remain pending.

| Time | Show | Short narration or overlay |
|---|---|---|
| 0–8s | Home and the Journal | “Pocket Ally turns everyday notes into the paperwork and replies people need.” |
| 8–16s | A synthetic voice note, playable audio and its saved English transcript | “Voice becomes editable text, while the original recording stays available.” Overlay: `Audio transcription: gpt-4o-transcribe`. |
| 16–22s | Saved generated companion, then Demo | “A familiar visual guide makes the work easier to follow.” Overlay: `Images API: saved generated companion`. |
| 22–29s | Generate a natural weekly question, then Send to Pocket Ally | “A synthetic incoming email asks how the week has been.” Overlay: `gpt-6-luna: demo message only`. |
| 29–53s | View activity and actual task progress | “The agent interprets the request, retrieves relevant notes and chooses the safe preparation tools.” Overlay: `Decisions routing → Responses + Agents SDK → sourced reply`. |
| 53–66s | Composed reply and one dated source | “It combines relevant observations into a reply, with the original sources one click away.” Overlay: `text-embedding-3-small + cited synthesis`. |
| 66–82s | Edit, Save changes, inspect exact preview and explicitly approve | “I can change the words. Only the exact version I review can be approved.” Show the local-copy label. |
| 82–90s | Completed local record and concise Codex credit | “This demo saves an approved local email copy. Codex helped build the agent, interface and tests, including a regression that caught a saved-draft persistence bug.” |

Use the measured timings as planning evidence, not a latency promise: the latest reply run took 24.37 seconds; synthetic message generation took roughly 2–3 seconds. If waiting is edited, label the cut or time compression. Do not present a prerecorded model result as a new live call. If using a saved transcript or image preview, label it as saved earlier. The companion is a visual guide, not a speaking agent or real-time avatar.

## API map for judges

| Capability | Actual implementation | User benefit and evidence |
|---|---|---|
| Output routing | Decisions API with `gpt-6-luna` | Chooses a bounded route from incoming text. Accepted check-in routes select a reply draft or internal summary, subject to validated facts and explicit no-reply instructions. Uncertain results retain an honest fallback. |
| Interpretation and tool choice | OpenAI Responses API through the Agents SDK, with source-validated extraction | Chooses relevant read, retrieval and preparation tools. No approval/send tools are exposed to the model. |
| Relevant memory | `text-embedding-3-small` with cosine ranking and dated source links | Finds relevant note content beyond exact keyword matches. Original sources remain reviewable. |
| Voice notes | Audio transcription with `gpt-4o-transcribe`, explicitly English | Produces editable text while retaining playable audio. This is transcription, not a voice agent. |
| Visual companion | Images API, default `gpt-image-1-mini` | Generates a visual companion preview that the user explicitly chooses. Actual generated-preview metadata was verified; it is not a conversational avatar. |
| Demo message generation | `gpt-6-luna`, reasoning effort `none` | Quickly generates realistic synthetic incoming messages from bounded administrative context. It does not run the task automatically. |
| Journey planning | TfL JourneyResults | Fetches postcode/date-specific plans and updates the same calendar UID. Verified in earlier live QA; omit from this short video rather than distract from the reply journey. Future plans are not guaranteed live departures. |
| Delivery boundary | Exact digest-bound approval, configured throwaway recipients and local `.eml` outbox | Editing invalidates prior approval. The video must call the result a local copy, not an externally delivered email. |

## Criteria and Codex example

- **Idea/usefulness:** show the transition from everyday observations to a useful reply, with less retyping and clear user control.
- **Use of Codex:** solo human builder, Astra orchestration and requested parallel GPT-6.1 Sol HIGH backend/frontend implementation. A concrete example is the reply-save bug: browser QA found that a new draft lost its case association, and a SQLite reread regression verified the fix. Exact approval/attachment-change tests provide a second example.
- **Execution:** show the working edit, save, review and approval path. The latest backend suite has 150 passing tests, with real provider and CUA verification recorded in CODEX.md.
- **Demo clarity:** keep one core journey. Use brief API overlays, not long architecture narration. Include actual builder name/contact in the submission, and verify public repository/video access.

## Verification and historical recording

Current browser interaction uses CUA against an isolated synthetic store. Verify independent Demo draft state, optional View activity, source citations, generated synthesis, edits surviving refresh, replacement draft digest and exact approved `.eml` content. Do not reset production data or use personal journal content for provider QA.

The old Playwright browser/case entry points are retired; source contract checks and API tests remain separate. The historical recording is `data/browser-qa/rehearsal-2/pocket-ally-demo.webm`, measured at 82.44 seconds, with an identical backup. It shows the earlier interface and must not be represented as the current app. See `SUBMISSION.md` for pending public links and submission requirements.
