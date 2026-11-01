/* Focused client auth recovery checks. Synthetic token and mocked HTTP gate only. */
const {chromium}=require('playwright');
const fs=require('node:fs/promises');
const path=require('node:path');
const assert=require('node:assert/strict');
const origin='https://pocket-ally.test', token='synthetic-valid-access-for-regression';
const output=path.resolve('data/access-qa');
let browser;
(async()=>{
  await fs.mkdir(output,{recursive:true});
  browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const context=await browser.newContext({viewport:{width:390,height:844},serviceWorkers:'block'});
  await context.addInitScript(()=>{window.__qaStreams={created:0,active:0,maxActive:0};window.EventSource=class{constructor(){this.closed=false;window.__qaStreams.created++;window.__qaStreams.active++;window.__qaStreams.maxActive=Math.max(window.__qaStreams.maxActive,window.__qaStreams.active);}close(){if(!this.closed){this.closed=true;window.__qaStreams.active--;}}};});
  const payload={phase:'ready',mode:'synthetic task demo',delivery_mode:'local-outbox',csrf:'synthetic-csrf',drafts:[],events:[],mascot:'idle',error:null};
  const states=new Map();
  await context.route('**/*',async route=>{
    const request=route.request(),url=new URL(request.url()),page=request.frame().page();
    if(!states.has(page))states.set(page,{authorized:false,exchanges:0,delayFirst:false,statusCalls:0});
    const state=states.get(page);
    if(url.pathname==='/api/session'){
      const body=request.postDataJSON();assert.deepEqual(Object.keys(body),['token']);state.exchanges++;
      if(body.token===token){state.authorized=true;return route.fulfill({status:200,contentType:'application/json',body:'{"authenticated":true}'});}
      return route.fulfill({status:403,contentType:'application/json',body:'{"detail":"Invalid private code"}'});
    }
    if(url.pathname.startsWith('/api/')){
      state.statusCalls++;
      const authorizedAtRequest=state.authorized;
      if(state.delayFirst&&state.statusCalls===1)await new Promise(resolve=>setTimeout(resolve,350));
      if(!authorizedAtRequest)return route.fulfill({status:401,contentType:'application/json',body:'{"detail":"Private access required"}'});
      const result=url.pathname==='/api/status'?payload:url.pathname==='/api/journal'?{entries:[]}:{saved:null,previews:[],styles:['soft','playful','minimal']};
      return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(result)});
    }
    const file=url.pathname==='/'?'static/index.html':url.pathname.slice(1);
    if(!file.startsWith('static/')&&!file.startsWith('assets/'))return route.fulfill({status:404,body:''});
    const mime=file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':file.endsWith('.png')?'image/png':file.endsWith('.svg')?'image/svg+xml':'text/html';
    try{return route.fulfill({status:200,contentType:mime,body:await fs.readFile(path.resolve(file))});}catch{return route.fulfill({status:404,body:''});}
  });
  const page=await context.newPage(),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto(origin+'/');await page.locator('#access-panel').waitFor({state:'visible'});
  assert.equal(await page.locator('#main-content').isVisible(),false);
  assert.equal(await page.evaluate(()=>window.__qaStreams.active),0);
  await page.evaluate(value=>{location.hash='access='+value;dispatchEvent(new HashChangeEvent('hashchange'));},token);
  await page.locator('#access-panel').waitFor({state:'hidden'});
  assert.equal(await page.evaluate(()=>state.phase),'ready');
  assert.equal(states.get(page).exchanges,1);
  assert.equal(await page.evaluate(()=>window.__qaStreams.active),1);
  assert.equal(await page.evaluate(()=>location.hash),'#home');
  states.get(page).authorized=false;await page.evaluate(()=>refresh());
  await page.locator('#access-panel').waitFor({state:'visible'});
  await page.locator('#access-input').fill('https://private.example/#access=synthetic-invalid');
  await page.locator('#access-submit').click();
  await page.locator('#access-error').waitFor({state:'visible'});
  assert.equal(await page.locator('#access-input').inputValue(),'');
  assert.match(await page.locator('#access-error').innerText(),/try again/);
  await page.screenshot({path:path.join(output,'invalid-access-retry.png')});
  await page.locator('#access-input').fill(token);await page.locator('#access-submit').click();
  await page.locator('#access-panel').waitFor({state:'hidden'});
  assert.equal(await page.locator('#access-input').inputValue(),'');
  assert.equal(await page.evaluate(()=>JSON.stringify({...localStorage,...sessionStorage}).includes('synthetic-')),false);
  assert.equal(await page.evaluate(()=>location.href.includes('access=')),false);
  assert.equal(await page.evaluate(()=>window.__qaStreams.active),1);
  assert.equal(await page.evaluate(()=>window.__qaStreams.maxActive),1);
  const initial=await context.newPage();await initial.goto(origin+'/#access='+token);
  await initial.locator('#access-panel').waitFor({state:'hidden'});await initial.waitForFunction(()=>typeof state!=='undefined'&&state);
  assert.equal(states.get(initial).exchanges,1);assert.equal(await initial.evaluate(()=>location.hash),'#home');
  const race=await context.newPage();states.set(race,{authorized:false,exchanges:0,delayFirst:true,statusCalls:0});
  await race.goto(origin+'/');await race.waitForTimeout(50);
  await race.evaluate(value=>location.hash='access='+value,token);
  await race.waitForFunction(()=>typeof state!=='undefined'&&state?.phase==='ready');
  await race.waitForTimeout(450);
  assert.equal(await race.locator('#access-panel').isVisible(),false);assert.equal(await race.locator('#error').isVisible(),false);
  assert.equal(await race.evaluate(()=>window.__qaStreams.active),1);
  assert.deepEqual(errors,[]);
  const result={ok:true,initialAnonymousLocks:true,sameDocumentFragmentRecovers:true,invalidCodeCanRetry:true,validManualRetryRecovers:true,initialFragmentRecovers:true,staleAnonymousResponseCannotRelock:true,inputCleared:true,fragmentCleared:true,tokenStored:false,oneActiveEventSource:true,duplicateHashEventExchanges:1,browserErrors:errors,gate:'Synthetic HTTP mock; real cookie gate independently verified by root'};
  await fs.writeFile(path.join(output,'results.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
  await browser.close();
})().catch(async error=>{console.error(error);if(browser)await browser.close().catch(()=>{});process.exitCode=1;});
