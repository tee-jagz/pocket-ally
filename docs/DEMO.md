# 80-second demo script

Run locally with synthetic data. Record the browser tab only; hide terminals, credentials and unrelated tabs. Do not claim the local mode sends real emails or calls AI.

| Time | Screen / action | Narration |
|---|---|---|
| 0–10s | Landing screen, Ade | “A diagnosis creates enough work. Pocket Ally handles the paperwork around it. This is entirely synthetic.” |
| 10–22s | Prepare paperwork; mascot reacts | “One forwarded attendance email starts a chain. Each extracted fact keeps its original email line.” |
| 22–35s | Calendar and claim; open source details | “The next appointment includes travel time. Here’s a partially filled official travel form, a checklist and a payment-based deadline. The refund is only an estimate; bank details stay out.” |
| 35–48s | Claim message, approve | “Nothing is sent without a separate approval. Today’s offline fallback writes a complete email with attachments to a local outbox.” |
| 48–61s | Manager message, approve | “The manager gets the date and a fact I already shared, without the hospital name or diagnosis.” |
| 61–73s | Diary answer; click dated citation and play audio | “When a form asks about stairs or walking, my own notes provide the words. Every sentence links back to its dated source.” |
| 73–80s | Today’s record, refund pending | “A clear record of what happened, what I approved and what’s still pending. Less admin. More room for you.” |

If live checks pass, replace the fallback sentence with “This sends only to our throwaway test accounts.” Show test inbox delivery in rehearsal before claiming it in the recording.

Two rehearsals: first check correctness and all source links; second time it under 90 seconds. Save a backup recording locally. Freeze features at 15:45 London, fix only after that, finish rehearsals by 16:30 and upload with time to test anonymous access before 17:00.

## Repeat the browser rehearsal

`scripts/browser_qa.cjs` checks the local journey, individual attachment review, dated audio/transcript sources, separate approvals, saved emails, phone widths and error states. It refuses live mode. It requires Node, Playwright and a Chrome executable; the application itself has no Node dependency.

Install the optional browser tooling under the ignored runtime directory:

```bash
npm install --prefix data/qa-tools playwright
```

With the app running in local mode, run the first rehearsal. Set `CHROME_PATH` to your browser executable; on this Mac it is `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`.

```bash
NODE_PATH="$PWD/data/qa-tools/node_modules" CHROME_PATH="/path/to/chrome" node scripts/browser_qa.cjs
```

For the second rehearsal, stop the app, run `python scripts/reset_demo.py`, and restart it so the initial state is ready. Install Playwright's recording helper, then record the complete journey:

```bash
PLAYWRIGHT_BROWSERS_PATH="$PWD/data/browser-tools" node data/qa-tools/node_modules/playwright/cli.js install ffmpeg
NODE_PATH="$PWD/data/qa-tools/node_modules" PLAYWRIGHT_BROWSERS_PATH="$PWD/data/browser-tools" CHROME_PATH="/path/to/chrome" node scripts/browser_qa.cjs --record
```

Screenshots, results and recordings are saved under ignored `data/browser-qa`. Check the actual duration and playback before upload. The recording has captions and shows synthetic local-outbox approvals; it does not claim external delivery. Browser sandbox permissions may be needed in managed development environments.

The verified recording from this build is `data/browser-qa/rehearsal-2/pocket-ally-demo.webm`: 82.44 seconds, with an identical `pocket-ally-demo-backup.webm` beside it. It is a silent captioned screen recording. The underlying diary player's playback was exercised during verification, but browser audio is not captured in the video. Public upload is still pending.
