# Submission checklist — 1 November 2026, London

- [x] Core acceptance tests and a complete local journey pass: 50 Python tests and two clean browser rehearsals.
- [x] Mode decided: local synthetic fallback; live providers remain unconfigured.
- [ ] 15:45 feature freeze: fixes only; no TfL or share-card stretch unless already fully done.
- [ ] README setup tested from a clean environment; credentials excluded.
- [ ] Public GitHub repository created under the builder's account; source pushed.
- [x] Run `python scripts/release_check.py`; inspect the staged file list.
- [ ] Repository link opens in a signed-out/private window without access requests.
- [x] Two rehearsals completed; final recorded video measures 82.44 seconds.
- [x] Save a backup local video; SHA-256 matches the final recording.
- [ ] Upload final video ≤90 seconds.
- [ ] Video link opens signed-out; playback works without access requests.
- [x] Give a concrete Codex example: approval bound to exact message/attachment bytes; test changes a file after approval and proves send refusal.
- [x] Credit the pre-existing NHS form, libraries and documentation; all original app work created during the event. System fonts require no downloaded font assets.
- [x] List actual team members: solo human builder + Codex assistance.
- [ ] Submit by 17:00 London. Event source confirms the submission close time.

Public repository URL: not published yet; builder confirmed GitHub is not set up.
Public video URL: not uploaded yet.

Suggested public-repository commands (after signing in using your usual secure tooling):

```bash
git init
git add .
git diff --cached --stat
# Inspect staged contents and run release_check.py before committing.
git commit -m "Build Pocket Ally synthetic paperwork demo"
# Create an empty PUBLIC GitHub repository in your account, then:
git remote add origin git@github.com:YOUR_USER/pocket-ally.git
git push -u origin HEAD
```

Do not put API keys in clone URLs, commit messages, issues or the demo video.
