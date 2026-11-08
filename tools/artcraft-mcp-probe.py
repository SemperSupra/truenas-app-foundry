#!/usr/bin/env python3
"""Public-safe stdio MCP handshake for a released editor CLI, no credentials."""
import json
import hashlib
import shutil
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
            def call(request_id, tool_name, args):
                if tool_name not in names: raise RuntimeError(f'missing required tool: {tool_name}')
                send({'jsonrpc':'2.0','id':request_id,'method':'tools/call','params':{'name':tool_name,'arguments':args}})
                result = recv(request_id, timeout=50)
                response = result.get('result')
                error = result.get('error')
                if error or not isinstance(response, dict) or response.get('isError'):
                    details = json.dumps(error or response,ensure_ascii=True)[:700]
                    raise RuntimeError(f'{tool_name} failed: {details}')
                evidence['mcp'][tool_name] = 'PASS'
                return response
            call(3, 'doc_inspect', {})
            call(4, 'doc_new', {'width':256, 'height':192, 'mode':'rgb','depth':8,'background':'white'})
            call(5, 'command_run', {'id':'layer.new.layer','params':{'name':'Cloud RDTE layer'}})
            call(6, 'doc_save', {'path':'cloud-rdte.pcraft'})
            call(7, 'doc_export', {'path':'cloud-rdte.png'})
            proof = {}
            for name, signature in [('cloud-rdte.pcraft',None), ('cloud-rdte.png',bytes.fromhex('89504e470d0a1a0a'))]:
                artifact = out / name
                if not artifact.is_file() or artifact.stat().st_size < 100:
                    raise RuntimeError(f'expected {name} is missing or empty')
                shutil.copyfile(artifact, evidence_dir / name)
                if signature and not artifact.read_bytes().startswith(signature):
                    raise RuntimeError(f'{name} has invalid file signature')
                proof[name] = {'size_bytes':artifact.stat().st_size,'sha256':hashlib.sha256(artifact.read_bytes()).hexdigest()}
            shutil.copyfile(out/'cloud-rdte.pcraft', inp/'cloud-rdte.pcraft')
            call(8, 'doc_open', {'path':'cloud-rdte.pcraft'})
            call(9, 'doc_inspect', {})
            evidence['artifacts'] = proof
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
