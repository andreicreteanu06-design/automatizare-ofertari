"""Faza 0: stack-ul încape în 16 GB când Colibri streamează experți de pe SSD?

Rulare (stack pornit):  docker compose up -d  ->  pytest tests/test_memory_16gb.py -s
Generează sarcină reală în paralel (generare Colibri + clasificare Laya) și
eșantionează la ~2 s memoria containerelor (docker stats) și a host-ului (psutil).
Serviciile nu au porturi publicate, așa că cererile pornesc din interiorul
containerelor, pe 127.0.0.1 (permis de protecția Host a serverului colibri).
"""
import json
import os
import re
import shutil
import subprocess
import threading
import time

import psutil
import pytest

PROJECT = "ofertare-"
STACK_BUDGET_GIB = float(os.environ.get("STACK_BUDGET_GIB", 13))   # memoria dată WSL2
HOST_MIN_FREE_GIB = float(os.environ.get("HOST_MIN_FREE_GIB", 1))  # sub asta Windows face swap
REQUEST_TIMEOUT = 900  # secunde; primul token Colibri e lent cât timp cache-ul de experți e rece

CHAT = """import json, urllib.request as u
body = {"model": "qwen36", "max_tokens": 48, "messages": [{"role": "user",
        "content": "Listeaza 3 cerinte de omologare AFER pentru o piesa feroviara importata."}]}
r = u.Request("http://127.0.0.1:5000/v1/chat/completions", json.dumps(body).encode(),
              {"Content-Type": "application/json"})
print(json.load(u.urlopen(r, timeout=%d))["usage"])""" % REQUEST_TIMEOUT

DECIDE = """import json, urllib.request as u
body = {"model": "laya", "state": "Datasheet page: part number 3EST000123, bogie frame, EN 15085.",
        "questions": {"present": {"type": "noul",
                      "instructions": "Does the code 3EST000123 appear literally on the page?"}}}
r = u.Request("http://127.0.0.1:5000/v1/systemone", json.dumps(body).encode(),
              {"Content-Type": "application/json"})
for _ in range(20):
    print(json.load(u.urlopen(r, timeout=120))["answers"]["present"])"""

_UNITS = {"B": 1, "kB": 1e3, "KiB": 2**10, "MB": 1e6, "MiB": 2**20, "GB": 1e9, "GiB": 2**30}


def _gib(s):
    m = re.fullmatch(r"([\d.]+)\s*([A-Za-z]+)", s.strip())
    return float(m[1]) * _UNITS[m[2]] / 2**30


def _run(*cmd, timeout=60):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _container_mem():
    out = _run("docker", "stats", "--no-stream", "--format", "{{json .}}").stdout
    rows = (json.loads(line) for line in out.splitlines() if line.strip())
    return {r["Name"]: _gib(r["MemUsage"].split("/")[0]) for r in rows if r["Name"].startswith(PROJECT)}


def _running():
    if not shutil.which("docker"):
        return set()
    out = _run("docker", "compose", "ps", "--services", "--status", "running").stdout
    return set(out.split())


@pytest.mark.skipif(not {"colibri", "laya", "qdrant"} <= _running(),
                    reason="pornește stack-ul: docker compose up -d")
def test_stack_fits_in_16gb():
    results = {}

    def load(name, service, script):
        results[name] = _run("docker", "compose", "exec", "-T", service, "python3", "-c", script,
                             timeout=REQUEST_TIMEOUT + 60)

    workers = [threading.Thread(target=load, args=a) for a in
               (("colibri", "colibri", CHAT), ("laya", "laya", DECIDE))]
    for w in workers:
        w.start()

    peak, total_peak, host_min_free = {}, 0.0, float("inf")
    while any(w.is_alive() for w in workers):
        mem = _container_mem()
        for name, gib in mem.items():
            peak[name] = max(peak.get(name, 0.0), gib)
        total_peak = max(total_peak, sum(mem.values()))
        host_min_free = min(host_min_free, psutil.virtual_memory().available / 2**30)
        time.sleep(1)

    print("\nVârf memorie pe container (GiB):")
    for name, gib in sorted(peak.items(), key=lambda kv: -kv[1]):
        print(f"  {name:<32} {gib:6.2f}")
    print(f"  {'TOTAL stack (vârf simultan)':<32} {total_peak:6.2f} / {STACK_BUDGET_GIB}")
    print(f"  {'Host: minim liber':<32} {host_min_free:6.2f} (prag {HOST_MIN_FREE_GIB})")

    for name, r in results.items():
        assert r.returncode == 0, f"{name} a eșuat:\n{r.stderr[-2000:]}"
        print(f"{name}: {r.stdout.strip().splitlines()[-1]}")

    ids = _run("docker", "compose", "ps", "-q").stdout.split()
    oom = [i for i in ids if _run("docker", "inspect", "-f", "{{.State.OOMKilled}}", i).stdout.strip() == "true"]
    assert not oom, f"containere omorâte de OOM: {oom}"
    assert total_peak <= STACK_BUDGET_GIB, f"stack-ul a depășit bugetul: {total_peak:.2f} GiB"
    assert host_min_free >= HOST_MIN_FREE_GIB, f"host-ul a rămas cu {host_min_free:.2f} GiB liberi"


def test_gib_parser():
    assert _gib("512MiB") == 0.5
    assert _gib("1.5GiB") == 1.5
    assert round(_gib("1.073741824GB"), 6) == 1.0
