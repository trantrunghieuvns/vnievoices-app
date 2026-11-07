import sys
import json
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

import vieneu
from vieneu import Vieneu

p = Path(vieneu.__file__).parent / "assets" / "voices_v3_turbo.json"
d = json.loads(p.read_text(encoding="utf-8"))
print(f"Total presets: {len(d['presets'])}, default: {d.get('default_voice')}")
for k, v in d["presets"].items():
    print(f" - {k}: {v.get('description')} (aliases={v.get('aliases')})")
