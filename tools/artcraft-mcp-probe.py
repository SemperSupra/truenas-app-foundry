#!/usr/bin/env python3
"""Public-safe stdio MCP handshake for a released editor CLI, no credentials."""
import json
import os
import selectors
import subprocess
import sys
import tempfile
import time
from pathlib import Path

def main() -> int:
    cli = Path(sys.argv[1]).resolve()
    evidence_dir = Path(os.environ.get('ARTCRAFT_EVIDENCE_DIR', 'evidence')).resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='artcraft-mcp-') as root:
        inp = Path(root, 'in'); out = Path(root, 'out'); inp.mkdir(); out.mkdir()
        version = subprocess.run([str(cli), '--version'], capture_output=True, text=True, timeout=20)
        p = subprocess.Popen([str(cli), 'mcp', '--automation-read-root', str(inp), '--automation-write-root', str(out)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        buffer = bytearray(); sel = selectors.DefaultSelector(); sel.register(p.stdout, selectors.EVENT_READ)
        evidence = {'binary': cli.name, 'version': version.stdout.strip() or version.stderr.strip(), 'mcp': {}}
        def send(obj):
            p.stdin.write((json.dumps(obj, separators=(',', ':')) + '\n').encode()); p.stdin.flush()
        def recv(expected_id, timeout=25):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                while b'\n' in buffer:
                    line, _, tail = buffer.partition(b'\n'); buffer[:] = tail
                    try: obj = json.loads(line)
                    except Exception: continue
                    if obj.get('id') == expected_id: return obj
                if p.poll() is not None: break
                if sel.select(timeout=max(0, min(1, deadline - time.monotonic()))):
                    chunk = os.read(p.stdout.fileno(), 65536)
                    if not chunk: break
                    buffer.extend(chunk)
            raise RuntimeError(f'MCP response id={expected_id} unavailable within deadline (exit={p.poll()})')
        try:
            send({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'artcraft-public-cloud-rdte','version':'0.1'}}})
            hello = recv(1)
            if 'error' in hello: raise RuntimeError(f'MCP initialize error: {hello["error"]}')
            evidence['mcp']['initialize'] = {'protocolVersion': hello.get('result',{}).get('protocolVersion'), 'serverInfo':hello.get('result',{}).get('serverInfo')}
            send({'jsonrpc':'2.0','method':'notifications/initialized','params':{}})
            send({'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}})
            tools = recv(2)
            if 'error' in tools: raise RuntimeError(f'MCP tools/list error: {tools["error"]}')
            names = [t.get('name','') for t in tools.get('result',{}).get('tools',[])]
            evidence['mcp']['tool_names'] = names
            if not names: raise RuntimeError('MCP returned no tools')
            if 'doc_inspect' in names:
                send({'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'doc_inspect','arguments':{}}})
                result = recv(3)
                evidence['mcp']['doc_inspect'] = {'has_result':'result' in result,'error':result.get('error')}
                if 'error' in result: raise RuntimeError('doc_inspect returned MCP protocol error')
            evidence['result']='PASS'
        except Exception as e:
            evidence['result']='FAIL'; evidence['reason']=str(e)[:600]
        finally:
            p.terminate()
            try: p.wait(timeout=5)
            except subprocess.TimeoutExpired: p.kill(); p.wait()
            evidence['exit_code']=p.returncode
            evidence['stderr_excerpt']=p.stderr.read(1200).decode('utf-8','replace')
            (evidence_dir/'photocraft-mcp-evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
            print(json.dumps(evidence,indent=2))
        return 0 if evidence['result']=='PASS' else 1

if __name__=='__main__':
    sys.exit(main())
