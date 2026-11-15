import unittest
from tools.rdte.foundry_t5_request import validate,SCHEMA
class Admission(unittest.TestCase):
 def test_good(self):
  self.assertEqual(validate(self.req()),[])
 def req(self):
  return {"schema":SCHEMA,"request_id":"fndry-t5-25-04-2-6-batch-001",
          "version":"25.04.2.6","rung":"t5","t3_run_id":123,
          "t3_head_sha":"a"*40,"t3_artifact_id":456,
          "scope":"public-disposable-platform-nginx-only"}
 def test_scope_and_version_fail_closed(self):
  for k,v in (("scope","production"),("version","latest"),("rung","t6"),
              ("t3_run_id",0),("t3_artifact_id",0),("t3_head_sha","unknown")):
   x=self.req();x[k]=v
   with self.subTest(key=k):self.assertTrue(validate(x))
 def test_extra_fields_denied(self):
  x=self.req();x["credentials"]={"token":"not-allowed"}
  self.assertTrue(validate(x))
if __name__=="__main__":unittest.main()
