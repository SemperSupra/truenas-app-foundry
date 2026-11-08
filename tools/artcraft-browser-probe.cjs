'use strict';
// Public-safe, dependency-free Chromium screenshot/DOM smoke. NOT a usability acceptance test.
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const assert = require('node:assert/strict');
const url = process.env.ARTCRAFT_PROBE_URL;
const name = process.env.ARTCRAFT_PROBE_NAME || 'artcraft';
const dir = path.resolve(process.env.ARTCRAFT_EVIDENCE_DIR || 'evidence');
assert(url && /^https?:\/\//.test(url), 'ARTCRAFT_PROBE_URL required');
fs.mkdirSync(dir, {recursive:true});
const evidence = {target:name, url, utc:new Date().toISOString(), probes:[]};
let failures = [];
for (const v of [{width:1280,height:800,label:'desktop'},{width:390,height:844,label:'narrow-viewport'}]) {
  const screenshot = path.join(dir,`${name}-${v.label}.png`);
  const profile = path.join('/tmp',`craft-chrome-${process.pid}-${v.label}`);
  try {
    const dom = execFileSync(process.env.CHROME_BIN || 'google-chrome', [
      '--headless=new','--no-sandbox','--disable-dev-shm-usage','--disable-gpu',
      '--ignore-certificate-errors','--no-first-run',`--user-data-dir=${profile}`,
      '--virtual-time-budget=12000',`--window-size=${v.width},${v.height}`,
      `--screenshot=${screenshot}`,'--dump-dom',url
    ], {timeout:80000,maxBuffer:20*1024*1024,encoding:'utf8',stdio:['ignore','pipe','pipe']});
    const pngBytes=fs.statSync(screenshot).size;
    const ok=dom.includes('<html') && dom.length>200 && pngBytes>1000;
    evidence.probes.push({viewport:v,htmlLength:dom.length,screenshot:path.basename(screenshot),pngBytes,pass:ok});
    if(!ok) failures.push(v.label);
  } catch(err) {
    evidence.probes.push({viewport:v,pass:false,error:String(err.message).slice(0,900)});
    failures.push(v.label);
  } finally { fs.rmSync(profile,{recursive:true,force:true}); }
}
fs.writeFileSync(path.join(dir,`${name}-browser-evidence.json`),JSON.stringify(evidence,null,2)+'\n');
process.stdout.write(JSON.stringify(evidence,null,2)+'\n');
if(failures.length) process.exitCode=1;
