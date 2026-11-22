"""Fake download_models.py for UI testing (WAN_MOCK=1): prints PROGRESS lines and marks the pack installed
in test/mock_packs.json. Pack name "FAIL" or WAN_MOCK_DL_FAIL=1 simulates a network error halfway."""
import json
import os
import sys
import time
from pathlib import Path

packs = [x for x in sys.argv[1:] if not x.startswith("--")]
total = 2_000_000_000
print("Checking…", flush=True)
for i in range(21):
    print(f"PROGRESS {total * i // 20} {total}", flush=True)
    time.sleep(0.4)
    if i == 10 and os.environ.get("WAN_MOCK_DL_FAIL") == "1":
        print("ERROR mock: connection reset", flush=True)
        sys.exit(1)
f = Path(__file__).resolve().parent / "test" / "mock_packs.json"
f.parent.mkdir(exist_ok=True)
st = json.loads(f.read_text()) if f.exists() else {}
st.update({p: True for p in packs})
f.write_text(json.dumps(st))
print("DONE", flush=True)
