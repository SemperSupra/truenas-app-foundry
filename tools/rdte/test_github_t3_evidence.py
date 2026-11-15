"""Negative artifact binding tests without any external requests."""
import copy,unittest
from tools.rdte.github_t3_evidence import require,EvidenceError,REPO,NAME,ARTIFACT

class Tests(unittest.TestCase):
 def setUp(self):
  self.req={"t3_run_id":123,"t3_head_sha":"a"*40,"t3_artifact_id":456}
  self.run={"id":123,"head_sha":"a"*40,"status":"completed","conclusion":"success","name":NAME,
            "repository":{"full_name":REPO}}
  self.art={"artifacts":[{"id":456,"name":ARTIFACT,"expired":False,"size_in_bytes":100,
                            "workflow_run":{"id":123}}]}
 def test_positive(self):
  self.assertTrue(require(self.req,self.run,self.art))
 def test_fail_closed_run(self):
  for key,v in (("id",999),("head_sha","b"*40),("status","in_progress"),
                ("conclusion","failure"),("name","other"),("repository",{"full_name":"foreign/other"})):
   r=copy.deepcopy(self.run);r[key]=v
   with self.subTest(k=key),self.assertRaises(EvidenceError):require(self.req,r,self.art)
 def test_fail_closed_artifact(self):
  for key,v in (("id",9),("name","foreign"),("expired",True),("size_in_bytes",0),
                ("workflow_run",{"id":1})):
   a=copy.deepcopy(self.art);a["artifacts"][0][key]=v
   with self.subTest(k=key),self.assertRaises(EvidenceError):require(self.req,self.run,a)
 def test_absent_or_duplicate(self):
  for arts in ({"artifacts":[]},{"artifacts":self.art["artifacts"]*2},{}):
   with self.assertRaises(EvidenceError):require(self.req,self.run,arts)
if __name__=="__main__":unittest.main()
