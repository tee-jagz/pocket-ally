/* Local synthetic journey only. Run with NODE_PATH pointing to Playwright's node_modules.
 * Add --record for a captioned demo (under 90 seconds on a prepared local runtime).
 * All generated artifacts remain beneath ignored data/.
 */
const {chromium} = require('playwright');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const record = process.argv.includes('--record');
const baseURL = process.env.DEMO_URL || 'http://127.0.0.1:8000';
const output = path.resolve(process.env.QA_OUTPUT || 'data/browser-qa');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
let browser;

(async () => {
  await fs.mkdir(output, {recursive:true});
  browser = await chromium.launch({headless:true, executablePath:process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const context = await browser.newContext({baseURL, viewport:{width:1280,height:900}, reducedMotion:'reduce', ...(record ? {recordVideo:{dir:output,size:{width:1280,height:900}}} : {})});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  const started = Date.now();
  async function chapter(text, until) {
    await page.evaluate(text => {
      let caption = document.querySelector('#qa-caption');
      if (!caption) {
        caption = document.createElement('div'); caption.id = 'qa-caption'; caption.setAttribute('aria-hidden','true');
        caption.style.cssText = 'position:fixed;left:24px;right:24px;bottom:16px;z-index:99999;padding:14px 22px;background:#173d37f2;color:white;border-radius:10px;font:600 19px/1.4 system-ui;box-shadow:0 4px 20px #0003;pointer-events:none';
        document.body.append(caption);
      }
      const modal = document.querySelector('dialog[open]');
      (modal || document.body).append(caption);
      caption.textContent = text;
    }, text);
    if (record) await delay(Math.max(0, until * 1000 - (Date.now()-started)));
  }
  async function status() { return (await context.request.get('/api/status')).json(); }
  async function waitPhase(phase) {
    await page.waitForFunction(async phase => (await (await fetch('/api/status')).json()).phase === phase, phase, {timeout:20000});
    await page.waitForTimeout(400);
  }
  async function screenshot(name) { await page.screenshot({path:path.join(output,name+'.png'),fullPage:true}); }
  await page.goto(baseURL, {waitUntil:'domcontentloaded'});
  await page.locator('#start').waitFor({state:'attached'});
  await page.waitForFunction(() => typeof csrf !== 'undefined' && csrf.length > 0);
  let s = await status();
  const initialPhase = s.phase;
  assert.match(s.mode,/offline/, 'QA must never send to external inboxes');
  if (record) assert.equal(s.phase,'ready','Reset the local demo with the server stopped before recording a complete journey');
  await screenshot('desktop-start');
  await chapter('Pocket Ally · Adults’ synthetic paperwork demo. No clinical advice or real patient data.',5);
  if (s.phase === 'ready' || s.phase === 'error') await page.locator('#start').click();
  await waitPhase(s.phase === 'complete' ? 'complete' : 'awaiting-approval');
  s = await status();
  assert.equal(s.drafts.length,2);
  await page.locator('.appointment').scrollIntoViewIfNeeded();
  await chapter('One synthetic attendance email prepares an appointment, travel paperwork and a private manager draft.',11);
  await page.locator('details summary').click();
  await page.locator('#provenance').waitFor({state:'visible'});
  assert.match(await page.locator('#provenance').innerText(),/email line/);
  await chapter('Extracted appointment details retain exact source lines. Calendar fallback is an ICS export only.',17);
  await screenshot('desktop-sources');
  await page.locator('details summary').click();
  await page.locator('.claim').scrollIntoViewIfNeeded();
  const pdf = await context.request.get('/api/claim.pdf');
  assert.equal(pdf.status(),200); assert.match(pdf.headers()['content-type'],/application\/pdf/);
  assert.equal((await pdf.body()).subarray(0,4).toString(),'%PDF');
  await chapter('The unsigned claim PDF needs review. Eligibility and refunds are unconfirmed; bank details stay blank.',23);
  await page.locator('#drafts').scrollIntoViewIfNeeded();
  const claim = s.drafts.find(d => d.kind === 'claim');
  for (let i=0;i<claim.attachments.length;i++) {
    const response = await context.request.get(`/api/drafts/${claim.id}/attachments/${i}`);
    assert.equal(response.status(),200, 'Every attachment must be reviewable');
    assert.ok((await response.body()).length > 0);
  }
  assert.equal(await page.locator('.attachment').count(),claim.attachments.length);
  await page.locator('.attachment').first().click();
  await page.locator('#attachment-dialog').waitFor({state:'visible'});
  await page.locator('#attachment-preview').waitFor({state:'visible'});
  await page.waitForTimeout(700);
  await chapter('Review the exact unsigned PDF attached to this draft. The same bytes are bound to approval.',28);
  await screenshot('desktop-pdf-review');
  await page.locator('#attachment-close').click();
  await chapter('Review the exact recipient, subject, body and every evidence attachment before approving the claim email.',32);
  await screenshot('desktop-review');
  const manager = s.drafts.find(d => d.kind === 'employer');
  assert.doesNotMatch(manager.subject+' '+manager.body,/cancer|uclh|chemotherapy|hospital|nhs|oncology|treatment/i);
  await chapter('The manager draft says “personal appointment” and asks about cover. It has a separate approval.',36);
  await page.locator('.diary').scrollIntoViewIfNeeded();
  await page.locator('.citation').first().click();
  await page.locator('#note-dialog').waitFor({state:'visible'});
  assert.match(await page.locator('#note-date').innerText(),/October/);
  assert.ok((await page.locator('#note-transcript').innerText()).length > 30);
  const audio = await context.request.get('/api/notes/note-1/audio');
  assert.equal(audio.status(),200); assert.ok((await audio.body()).length > 44);
  await page.locator('#note-audio').evaluate(a => a.play());
  await page.waitForFunction(() => document.querySelector('#note-audio').currentTime > 0.1, null, {timeout:5000});
  await chapter('Diary answers cite dated source notes. Each citation opens its transcript and synthetic audio recording.',42);
  await screenshot('desktop-diary-source');
  await page.locator('[data-source="note-2"]').click();
  await page.waitForFunction(() => document.querySelector('#note-date').textContent.startsWith('27'));
  await chapter('Walking and stairs evidence is extracted from the diary. Review the original wording before using it.',47);
  await page.locator('[data-source="note-3"]').click();
  await page.waitForFunction(() => document.querySelector('#note-date').textContent.startsWith('28'));
  await chapter('The manager note supports the privacy-preserving wording. No clinical details go into the employer email.',52);
  await page.locator('#note-dialog .dialog-close').click();
  assert.equal(await page.locator('#note-audio').evaluate(a => a.paused),true);
  await page.locator('#drafts').scrollIntoViewIfNeeded();
  const mobileResults = [];
  for (const width of [320,375,390,768]) {
    const mobile = await browser.newContext({baseURL,viewport:{width,height:844},isMobile:width<600,hasTouch:width<600,reducedMotion:'reduce'});
    const m = await mobile.newPage();
    m.on('pageerror', e => errors.push(e.message));
    await m.goto(baseURL,{waitUntil:'domcontentloaded'});
    await m.locator('#drafts .draft').first().waitFor();
    await m.screenshot({path:path.join(output,`mobile-${width}.png`),fullPage:true});
    const dimensions = await m.evaluate(() => ({viewport:innerWidth,document:document.documentElement.scrollWidth,body:document.body.scrollWidth}));
    assert.ok(dimensions.document <= width, `Horizontal overflow at ${width}px: ${JSON.stringify(dimensions)}`);
    assert.ok(dimensions.body <= width,`Body overflow at ${width}px`);
    const approve = m.locator('.approve').first();
    if (await approve.count()) {
      const button = await approve.boundingBox();
      assert.ok(button.x >= 0 && button.x+button.width <= width,`Approval button overflows at ${width}px`);
    }
    await m.screenshot({path:path.join(output,`mobile-${width}.png`),fullPage:true});
    await m.locator('.attachment').first().click();
    await m.locator('#attachment-dialog').waitFor({state:'visible'});
    const preview = await m.locator('#attachment-dialog').boundingBox();
    assert.ok(preview.x >= 0 && preview.x+preview.width <= width,`Attachment preview overflows at ${width}px`);
    await m.locator('#attachment-close').click();
    if (width === 320) await m.route('**/api/notes/note-1/audio', route => route.fulfill({status:404,body:'Synthetic unavailable-audio check'}));
    await m.locator('#show-notes').click();
    await m.locator('#note-dialog').waitFor({state:'visible'});
    const dialog = await m.locator('#note-dialog').boundingBox();
    assert.ok(dialog.x >= 0 && dialog.x+dialog.width <= width,`Dialog overflows at ${width}px`);
    if (width === 320) {
      await m.locator('#audio-status').waitFor({state:'visible'});
      assert.match(await m.locator('#audio-status').innerText(),/transcript/);
      await m.screenshot({path:path.join(output,'mobile-audio-fallback.png'),fullPage:true});
    }
    mobileResults.push({width,...dimensions,dialogFits:true});
    await mobile.close();
  }
  await chapter('Each email stays unsent until its own exact draft is approved. This run saves only to the local outbox.',58);
  if (!claim.result) {
    await page.locator(`.approve[data-id="${claim.id}"]`).click();
    await page.waitForFunction(async id => (await (await fetch('/api/status')).json()).drafts.find(d=>d.id===id).result,claim.id);
    s = await status();
    assert.equal(s.drafts.find(d=>d.id===manager.id).approved,false,'Claim approval must not approve manager email');
  }
  await chapter('Claim approved and saved locally. The manager draft still needs its own approval.',64);
  if (!manager.result) await page.locator(`.approve[data-id="${manager.id}"]`).click();
  await waitPhase('complete');
  s = await status();
  assert.ok(s.drafts.every(d=>d.approved && d.result.delivery==='local outbox only'));
  for (const d of s.drafts) assert.equal((await context.request.get(d.result.download)).status(),200);
  await chapter('Both approved drafts are now in the local outbox. No email has left this computer.',70);
  await screenshot('desktop-complete');
  await page.locator('.record').scrollIntoViewIfNeeded();
  assert.match(await page.locator('.record').innerText(),/Refund not yet confirmed/);
  await chapter('The action record shows what happened. Refund and eligibility are still unconfirmed.',77);
  assert.deepEqual(errors,[],'No browser JavaScript errors');
  const video = record ? page.video() : null;
  await context.close();
  let recording = null;
  if (video) {
    recording=path.join(output,'pocket-ally-demo.webm');
    await video.saveAs(recording);
    await fs.copyFile(recording,path.join(output,'pocket-ally-demo-backup.webm'));
  }
  const failureContext = await browser.newContext({baseURL,viewport:{width:390,height:844}});
  const failurePage = await failureContext.newPage();
  await failurePage.route('**/api/status',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Synthetic connection-failure check. Reload to retry.'})}));
  await failurePage.goto(baseURL,{waitUntil:'domcontentloaded'});
  await failurePage.locator('#error').waitFor({state:'visible'});
  await failurePage.locator('.mascot.stuck').waitFor();
  await failurePage.waitForTimeout(600);
  await failurePage.locator('.mascot.stuck').waitFor();
  await failurePage.screenshot({path:path.join(output,'mobile-error-state.png'),fullPage:true});
  await failureContext.close();
  await browser.close();
  const result = {ok:true,initialPhase,mode:s.mode,phase:s.phase,approvals:s.drafts.length,attachmentsReviewed:claim.attachments.length,mobile:mobileResults,browserErrors:errors,errorStateVerified:true,audioFallbackVerified:true,elapsedSeconds:Math.round((Date.now()-started)/1000),recording};
  await fs.writeFile(path.join(output,'results.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify(result,null,2));
})().catch(async error=>{
  console.error(error);
  if (browser) await browser.close().catch(()=>{});
  process.exitCode=1;
});
