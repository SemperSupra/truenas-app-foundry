#!/usr/bin/env python3
from __future__ import annotations
import copy, hashlib, importlib.util, json, pathlib, subprocess, sys, tempfile, unittest
HERE=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
SPEC=importlib.util.spec_from_file_location('sitepkg',HERE/'package_foliorelay_site_deployment.py')
MOD=importlib.util.module_from_spec(SPEC); assert SPEC.loader; SPEC.loader.exec_module(MOD)
GEN=importlib.util.spec_from_file_location('generic',HERE/'package_truenas_deployment_artifact.py')
GENMOD=importlib.util.module_from_spec(GEN); assert GEN.loader; GEN.loader.exec_module(GENMOD)
FOUNDRY='81deb97185760975fd8d3162df42056c77b3c0fd'
CONTROL='ghcr.io/sempersupra/foliorelay-control@sha256:'+'d'*64
CUPS='ghcr.io/sempersupra/foliorelay-cups@sha256:'+'c'*64

def write_bundle(root:pathlib.Path,version='25.04.1', mutate=None):
    root.mkdir(); avahi=version!='26.0.0-BETA.3'; host='foliorelay-t6.local'; base='/mnt/rdtepool/foliorelay-t6'
    disc={'image':CONTROL,'read_only':True,'cap_drop':['ALL'],'security_opt':['no-new-privileges:true'],'depends_on':{'control':{'condition':'service_healthy'}},'entrypoint':['/usr/local/bin/foliorelay-dnssd'],'command':['-identity-file','/var/lib/foliorelay-control/config/printer.json'],'healthcheck':{'disable':True},'network_mode':'host','volumes':[{'type':'bind','source':base+'/control','target':'/var/lib/foliorelay-control','read_only':True}]}
    if avahi:
        disc['user']='65534:10001'; disc['command'] += ['-backend','avahi','-dbus-address','unix:path=/run/dbus/system_bus_socket']; disc['volumes'].append({'type':'bind','source':'/run/dbus/system_bus_socket','target':'/run/dbus/system_bus_socket','read_only':True})
    compose={'services':{
      'control':{'image':CONTROL,'read_only':True,'cap_drop':['ALL'],'security_opt':['no-new-privileges:true'],'ports':[{'target':18443,'published':'18443'}],'volumes':[{'type':'bind','source':base+'/control','target':'/var/lib/foliorelay','read_only':False},{'type':'bind','source':base+'/tls','target':'/var/lib/foliorelay-tls','read_only':False},{'type':'bind','source':base+'/artifacts','target':'/var/lib/foliorelay/artifacts','read_only':False},{'type':'bind','source':base+'/secrets/control.token','target':'/run/secrets/foliorelay.token','read_only':True}],'command':['-listen','0.0.0.0:18080','-https-listen','0.0.0.0:18443','-tls-state-dir','/var/lib/foliorelay-tls','-journal','/var/lib/foliorelay/state/journal.frj','-artifact-store','/var/lib/foliorelay/artifacts','-token-file','/run/secrets/foliorelay.token','-identity-file','/var/lib/foliorelay/config/printer.json','-printer-uri',f'ipp://{host}:8634/printers/FolioRelay','-printer-name','FolioRelay','-printer-location','RDTE','-airprint']},
      'cups':{'image':CUPS,'read_only':True,'cap_drop':['ALL'],'security_opt':['no-new-privileges:true'],'ports':[{'target':8634,'published':'8634'}],'tmpfs':['/etc/cups:rw','/var/cache/cups:rw','/var/log/cups:rw'],'environment':{'FOLIORELAY_PUBLIC_HOST':host},'volumes':[{'type':'bind','source':base+'/control','target':'/var/lib/foliorelay-control','read_only':True},{'type':'bind','source':base+'/artifacts','target':'/var/lib/foliorelay-artifacts','read_only':False},{'type':'bind','source':base+'/cups-state','target':'/var/lib/cups','read_only':False},{'type':'bind','source':base+'/cups-spool','target':'/var/spool/cups','read_only':False},{'type':'bind','source':base+'/secrets/control.token','target':'/run/secrets/foliorelay.token','read_only':True}]},
      'discovery':disc},'x-portals':[{'name':'Web UI','scheme':'https','host':host,'port':18443,'path':'/'}]}
    if mutate: mutate(compose)
    target={'schema_version':2,'profile_id':f'truenas-scale-{version}-materialization','truenas_version':version}; values='app_name: rdte-t6-foliorelay\n'; pub={'status':'PASS','source_revision':'1'*40,'control':{'image':CONTROL.split('@')[0],'digest':CONTROL.split('@')[1],'anonymous_pull':True,'signed_keyless':True},'cups':{'image':CUPS.split('@')[0],'digest':CUPS.split('@')[1],'anonymous_pull':True,'signed_keyless':True}}
    for n,obj in [('compose.json',compose),('target-profile.json',target),('publication-receipt.json',pub)]: (root/n).write_text(json.dumps(obj,indent=2,sort_keys=True)+'\n')
    (root/'values.yaml').write_text(values)
    def sh(p): return hashlib.sha256((root/p).read_bytes()).hexdigest()
    control={'schema':MOD.CONTROL_SCHEMA,'foundry_ref':FOUNDRY,'secrets_captured':False,'candidate':{'control_image':CONTROL,'cups_image':CUPS,'source_revision':'1'*40,'truenas_version':version,'target_profile_id':target['profile_id'],'target_profile_schema':2,'discovery_backend':'avahi' if avahi else 'direct'},'required_oracles':sorted(MOD.EXPECTED_ORACLES),'artifacts':{'compose_canonical_sha256':GENMOD.canonical_sha256(compose),'publication_receipt_sha256':sh('publication-receipt.json'),'target_profile_sha256':sh('target-profile.json'),'values_sha256':sh('values.yaml')},'runtime':{'app_name':'rdte-t6-foliorelay','control_root':base+'/control','management_tls_root':base+'/tls','artifact_root':base+'/artifacts','cups_state_root':base+'/cups-state','cups_spool_root':base+'/cups-spool','token_path':base+'/secrets/control.token','management_port':18443,'management_internal_port':18080,'ipp_port':8634,'management_scheme':'https','management_tls_state':'/var/lib/foliorelay-tls','management_portal':{'name':'Web UI','scheme':'https','host':host,'port':18443,'path':'/'}}}
    (root/'control.json').write_text(json.dumps(control,indent=2,sort_keys=True)+'\n')
    return compose,control

class Tests(unittest.TestCase):
  def validate(self,root,version='25.04.1'):
    return MOD._validate_source(root,FOUNDRY,version,CONTROL,CUPS)
  def test_avahi_site_binding_preserves_qualified_semantics(self):
    with tempfile.TemporaryDirectory() as td:
      source,_=write_bundle(pathlib.Path(td)/'b'); ctl,src=self.validate(pathlib.Path(td)/'b')
      out,site=MOD.bind_site(ctl,src,app_name='foliorelay',data_root='/mnt/tank/apps/foliorelay',token_file='/mnt/tank/apps/foliorelay/secrets/control.token',public_host='foliorelay.local',printer_name='FolioRelay',printer_location='Home')
      self.assertEqual(out['services']['control']['image'],CONTROL); self.assertEqual(out['services']['cups']['image'],CUPS)
      self.assertEqual(out['services']['discovery']['user'],'65534:10001'); self.assertEqual(out['services']['discovery']['healthcheck'],{'disable':True})
      self.assertEqual(out['x-portals'][0]['host'],'foliorelay.local'); self.assertNotIn('/mnt/rdtepool/foliorelay-t6',json.dumps(out)); self.assertFalse(site['secrets_captured'])
      self.assertEqual(site['host_path_requirements'][0]['mode'],'0710')
  def test_beta3_keeps_direct_discovery(self):
    with tempfile.TemporaryDirectory() as td:
      write_bundle(pathlib.Path(td)/'b','26.0.0-BETA.3'); ctl,src=self.validate(pathlib.Path(td)/'b','26.0.0-BETA.3'); out,site=MOD.bind_site(ctl,src,app_name='foliorelay',data_root='/mnt/tank/f',token_file='/mnt/tank/f/secrets/control.token',public_host='foliorelay.local',printer_name='FolioRelay',printer_location='')
      self.assertNotIn('user',out['services']['discovery']); self.assertNotIn('/run/dbus/system_bus_socket',json.dumps(out)); self.assertEqual(site['host_path_requirements'][0]['mode'],'0700')
  def test_rejects_rehashed_security_drift(self):
    with tempfile.TemporaryDirectory() as td:
      root=pathlib.Path(td)/'b'; compose,control=write_bundle(root); compose['services']['control']['cap_drop']=[]; (root/'compose.json').write_text(json.dumps(compose,indent=2,sort_keys=True)+'\n'); control['artifacts']['compose_canonical_sha256']=GENMOD.canonical_sha256(compose); (root/'control.json').write_text(json.dumps(control,indent=2,sort_keys=True)+'\n')
      with self.assertRaises(MOD.SiteBindingError): self.validate(root)
  def test_rejects_unqualified_site_shapes(self):
    with tempfile.TemporaryDirectory() as td:
      root=pathlib.Path(td)/'b'; write_bundle(root); ctl,src=self.validate(root)
      for kwargs in [
       dict(data_root='/tmp/f',token_file='/tmp/f/secrets/control.token',public_host='foliorelay.local'),
       dict(data_root='/mnt/tank/f',token_file='/mnt/tank/other/control.token',public_host='foliorelay.local'),
       dict(data_root='/mnt/tank/f',token_file='/mnt/tank/f/secrets/control.token',public_host='localhost'),
       dict(data_root='/mnt/tank/f',token_file='/mnt/tank/f/secrets/control.token',public_host='printer.example.com')]:
        with self.assertRaises(MOD.SiteBindingError): MOD.bind_site(ctl,src,app_name='foliorelay',printer_name='FolioRelay',printer_location='',**kwargs)
  def test_cli_is_deterministic_and_does_not_echo_site_values(self):
    with tempfile.TemporaryDirectory() as td:
      td=pathlib.Path(td); root=td/'b'; write_bundle(root)
      outputs=[]
      for i in (1,2):
        out=td/f'o{i}'; cp=subprocess.run([sys.executable,str(HERE/'package_foliorelay_site_deployment.py'),'--control-dir',str(root),'--expected-foundry-ref',FOUNDRY,'--expected-target-version','25.04.1','--expected-control-image',CONTROL,'--expected-cups-image',CUPS,'--app-name','foliorelay','--data-root','/mnt/PRIVATE_SENTINEL/foliorelay','--token-file','/mnt/PRIVATE_SENTINEL/foliorelay/secrets/control.token','--public-host','foliorelay.local','--out-dir',str(out)],text=True,capture_output=True)
        self.assertEqual(cp.returncode,0,cp.stderr); self.assertNotIn('PRIVATE_SENTINEL',cp.stdout); outputs.append(json.loads((out/'deployment-artifact.json').read_text()))
      self.assertEqual(outputs[0]['artifact_sha256'],outputs[1]['artifact_sha256']); self.assertEqual(outputs[0]['materialization_identity'],outputs[1]['materialization_identity'])
if __name__=='__main__': unittest.main()
