#!/usr/bin/env python3
import copy, importlib.util, pathlib, tempfile, unittest, json, sys
HERE=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
SPEC=importlib.util.spec_from_file_location("bind",HERE/"bind_truenas_site.py")
MOD=importlib.util.module_from_spec(SPEC); assert SPEC.loader; SPEC.loader.exec_module(MOD)

BASE={"services":{"app":{"image":"example@sha256:"+"a"*64,
 "volumes":[{"type":"bind","source":"/mnt/rdte/app","target":"/data","read_only":False}],
 "environment":{"PUBLIC_HOST":"app-rdte.local"},
 "command":["-listen","0.0.0.0:443","-public-uri","https://app-rdte.local/"]}},
 "x-portals":[{"name":"Web UI","scheme":"https","host":"app-rdte.local","port":443,"path":"/"}]}

def spec():
    return {"schema":MOD.SCHEMA,"app_name":"probe-app",
      "expected_base_compose_sha256":MOD.canonical_sha256(BASE),
      "patches":[
        {"path":"/services/app/volumes/0/source","expected":"/mnt/rdte/app","value":"/mnt/tank/apps/probe"},
        {"path":"/services/app/environment/PUBLIC_HOST","expected":"app-rdte.local","value":"probe.local"},
        {"path":"/services/app/command/3","expected":"https://app-rdte.local/","value":"https://probe.local/"},
        {"path":"/x-portals/0/host","expected":"app-rdte.local","value":"probe.local"}],
      "host_resources":[
        {"path":"/mnt/tank/apps/probe","kind":"directory","uid":1000,"gid":1000,"mode":"0700","ownership":"foundry-owned","retain_on_remove":True},
        {"path":"/mnt/tank/apps/probe/token","kind":"file","uid":1000,"gid":1000,"mode":"0400","ownership":"foundry-owned","retain_on_remove":True,
         "content_policy":{"kind":"generated-random-base64","bytes":48}}]}

class Tests(unittest.TestCase):
  def test_exact_declarative_binding(self):
    out,res=MOD.bind(BASE,spec())
    self.assertEqual(out["services"]["app"]["volumes"][0]["source"],"/mnt/tank/apps/probe")
    self.assertEqual(out["x-portals"][0]["host"],"probe.local")
    self.assertEqual(len(res),2)

  def test_base_identity_drift_fails_closed(self):
    s=spec(); s["expected_base_compose_sha256"]="0"*64
    with self.assertRaises(MOD.BindingError): MOD.bind(BASE,s)

  def test_expected_value_drift_fails_closed(self):
    s=spec(); s["patches"][0]["expected"]="wrong"
    with self.assertRaises(MOD.BindingError): MOD.bind(BASE,s)

  def test_duplicate_patch_and_resource_fail(self):
    s=spec(); s["patches"].append(copy.deepcopy(s["patches"][0]))
    with self.assertRaises(MOD.BindingError): MOD.bind(BASE,s)
    s=spec(); s["host_resources"].append(copy.deepcopy(s["host_resources"][0]))
    with self.assertRaises(MOD.BindingError): MOD.bind(BASE,s)

  def test_resources_must_be_bounded_to_mnt_and_secret_policy_has_no_value(self):
    s=spec(); s["host_resources"][0]["path"]="/etc/probe"
    with self.assertRaises(MOD.BindingError): MOD.bind(BASE,s)
    s=spec(); s["host_resources"][1]["content_policy"]["value"]="secret"
    with self.assertRaises(MOD.BindingError): MOD.bind(BASE,s)

  def test_resource_path_traversal_or_noncanonical_form_rejected(self):
    for attack in (
      "/mnt/tank/../../etc/shadow",
      "/mnt/tank/../other",
      "/mnt/tank//apps/probe",
      "/mnt/tank/./apps/probe",
      "/mnt/tank/apps/probe/",
      "//mnt/tank/apps/probe",
      "/mnt/tank/apps/probe\\nspoof",
      "/etc/probe",
    ):
      with self.subTest(path=attack):
        s=spec(); s["host_resources"][0]["path"]=attack
        with self.assertRaises(MOD.BindingError):
          MOD.bind(BASE,s)

  def test_strict_host_mount_resource_coverage_positive(self):
    s=spec(); s["strict_host_bind_sources"]=True
    bound,resources=MOD.bind(BASE,s)
    self.assertEqual(bound["services"]["app"]["volumes"][0]["source"],
                     "/mnt/tank/apps/probe")
    self.assertEqual(len(resources),2)

  def test_strict_host_mount_refuses_undeclared_or_short_form(self):
    for attack in (
      [{"type":"bind","source":"/mnt/other/secret","target":"/data"}],
      ["/mnt/other/secret:/data:ro"],
      [{"type":"bind","source":"/etc/shadow","target":"/secret"}],
      [{"type":"volume","source":"/mnt/secret","target":"/data"}],
      [{"type":"bind","source":"/mnt/tank/apps/probe","target":"relative"}],
    ):
      with self.subTest(volumes=attack):
        s=spec(); s["strict_host_bind_sources"]=True
        s["patches"]=[]
        base=copy.deepcopy(BASE)
        base["services"]["app"]["volumes"]=attack
        s["expected_base_compose_sha256"]=MOD.canonical_sha256(base)
        with self.assertRaises(MOD.BindingError): MOD.bind(base,s)

  def test_strict_host_mount_rejects_volumes_from(self):
    s=spec(); s["strict_host_bind_sources"]=True
    base=copy.deepcopy(BASE); base["services"]["app"]["volumes_from"]=["foreign"]
    s["expected_base_compose_sha256"]=MOD.canonical_sha256(base)
    s["patches"]=[]
    with self.assertRaises(MOD.BindingError): MOD.bind(base,s)

  def test_strict_host_mount_flag_is_boolean(self):
    s=spec(); s["strict_host_bind_sources"]="false"
    with self.assertRaises(MOD.BindingError): MOD.bind(BASE,s)

if __name__=="__main__": unittest.main()
