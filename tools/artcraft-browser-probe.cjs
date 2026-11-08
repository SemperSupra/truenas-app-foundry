'use strict';
// Public-safe browser smoke test: no accounts, privileged tokens, or user artifacts.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_PACKAGE || 'playwright');

(async () => {
  const url = process.env.ARTCRAFT_PROBE_URL;
  const name = process.env.ARTCRAFT_PROBE_NAME || 'artcraft';
  const dir = process.env.ARTCRAFT_EVIDENCE_DIR || 'evidence';
  assert(url && /^https?:\/\//.test(url), 'ARTCRAFT_PROBE_URL required');
  fs.mkdirSync(dir, { recursive: true });
  const browser = await chromium.launch({
    channel: 'chrome',
    headless: true,
    args: ['--disable-dev-shm-usage', '--no-sandbox']
  });
  const evidence = {
    target: name, url, utc: new Date().toISOString(),
    playwright: require(path.join(path.dirname(require.resolve(process.env.PLAYWRIGHT_PACKAGE || 'playwright')), 'package.json')).version,
    probes: []
  };
  try {
    for (const viewport of [
      {width:1280, height:800, label:'desktop'},
      {width:390, height:844, label:'mobile'}
    ]) {
      const context = await browser.newContext({
        viewport, ignoreHTTPSErrors:true, acceptDownloads:true
      });
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', e => errors.push({type:'pageerror',message:String(e.message).slice(0,500)}));
      page.on('console', m => {
        if (m.type() === 'error') errors.push({type:'console',message:m.text().slice(0,500)});
      });
      const response = await page.goto(url, {waitUntil:'domcontentloaded',timeout:60000});
      await page.waitForTimeout(8000);
      const title = await page.title();
      const snapshot = await page.evaluate(() => ({
        htmlLength:document.documentElement.outerHTML.length,
        canvasCount:document.querySelectorAll('canvas').length,
        buttonCount:document.querySelectorAll('button').length,
        viewportWidth:document.documentElement.clientWidth,
        scrollWidth:document.documentElement.scrollWidth
      }));
      const screenshot = path.join(dir, `${name}-${viewport.label}.png`);
      await page.screenshot({path:screenshot,fullPage:false,timeout:15000});
      const pass = response && response.status() < 400 && snapshot.htmlLength > 100;
      evidence.probes.push({viewport,status:response?.status()??null,title,snapshot,errors,screenshot,pass});
      await context.close();
      assert(pass, `HTTP/DOM smoke failed for ${name}/${viewport.label}`);
    }
  } finally {
    await browser.close();
    fs.writeFileSync(path.join(dir,`${name}-browser-evidence.json`),JSON.stringify(evidence,null,2)+'\n');
    process.stdout.write(JSON.stringify(evidence,null,2)+'\n');
  }
})().catch(e => { console.error(e.stack || String(e)); process.exitCode = 1; });
