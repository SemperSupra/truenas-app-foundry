#!/usr/bin/env python3
"""Offline negative oracles for materialized TrueNAS source, not actual runtime."""
import copy
import unittest
from tools.validate_ad_foundry_ix_render import verify, RenderFailure, CONTROL, WORKER, IMAGE

def source():
    svc=lambda mode: {
        "image":IMAGE,"user":"65532:65532","read_only":True,
        "cap_drop":["ALL"],"security_opt":["no-new-privileges:true"],
        "command":[mode],
        "volumes":[
            {"type":"bind","source":"/mnt/synthetic/agent-dispatch-rdte/custody","target":"/custody","read_only":True,"bind":{"create_host_path":False}},
            {"type":"bind","source":"/mnt/synthetic/agent-dispatch-rdte/ledger","target":"/ledger","read_only":False,"bind":{"create_host_path":False}},
        ],
    }
    a,b=svc("serve"),svc("worker")
    a["ports"]=[{"target":8080,"published":"18091","host_ip":"127.0.0.1"}]
    b["ports"]=[]
    return {"services":{CONTROL:a,WORKER:b}}

class SourceRenderFalsification(unittest.TestCase):
    def test_control(self):
        self.assertTrue(verify(source())["loopback"])

    def deny(self,modify):
        value=source()
        modify(value)
        with self.assertRaises(RenderFailure): verify(value)

    def test_privilege_and_identity_refusals(self):
        for role in (CONTROL,WORKER):
            for key,bad in (("user","0:0"),("read_only",False),("cap_drop",[]),("security_opt",[]),("privileged",True)):
                with self.subTest(role=role,key=key):
                    self.deny(lambda v,r=role,k=key,b=bad:v["services"][r].update({k:b}))

    def test_storage_and_ingress_refusals(self):
        self.deny(lambda v:v["services"][CONTROL]["ports"][0].update(host_ip="0.0.0.0"))
        self.deny(lambda v:v["services"][WORKER].update(ports=[{"target":8080}]))
        self.deny(lambda v:v["services"][CONTROL]["volumes"][0].update(read_only=False))
        self.deny(lambda v:v["services"][CONTROL]["volumes"][1].update(read_only=True))
        self.deny(lambda v:v["services"][WORKER]["volumes"][1].update(source="/mnt/realhost"))
        self.deny(lambda v:v["services"][CONTROL]["volumes"][0]["bind"].update(create_host_path=True))

    def test_image_and_socket_refusals(self):
        self.deny(lambda v:v["services"][CONTROL].update(image="ghcr.io/private/service:latest"))
        self.deny(lambda v:v["services"][WORKER].update(volumes=v["services"][WORKER]["volumes"]+[
            {"type":"bind","source":"/var/run/docker.sock","target":"/run/docker.sock"}]))

if __name__=="__main__":unittest.main()
