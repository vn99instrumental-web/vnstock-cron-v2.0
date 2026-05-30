"""
scripts/debug_find_venv.py — v2
================================
Tim venv + vnstock_ta. KHONG quet toan bo filesystem (gay timeout).
Trigger qua debug.yml voi input: scripts/debug_find_venv.py
"""
import os
import sys
import glob

print("=" * 60)
print("  FIND VENV DIAGNOSTIC v2")
print("=" * 60)

# 1. Python dang chay (quan trong nhat)
print("\n-- Current Python --")
print(f"  sys.executable : {sys.executable}")
print(f"  sys.version    : {sys.version.split()[0]}")
print(f"  sys.prefix     : {sys.prefix}")

# 2. vnstock_ta import duoc khong + nam dau
print("\n-- Import test --")
try:
    import vnstock_ta
    print(f"  vnstock_ta : OK")
    print(f"  location   : {vnstock_ta.__file__}")
except ImportError as e:
    print(f"  vnstock_ta : FAIL -- {e}")

try:
    import pandas
    print(f"  pandas     : OK ({pandas.__version__})")
except ImportError:
    print(f"  pandas     : MISSING")

try:
    import pyarrow
    print(f"  pyarrow    : OK ({pyarrow.__version__})")
except ImportError:
    print(f"  pyarrow    : MISSING")

# 3. sys.path
print("\n-- sys.path (site-packages) --")
for p in sys.path:
    if "site-packages" in p or "venv" in p:
        print(f"  {p}")

# 4. Glob cac path kha di (khong dung find /)
print("\n-- Candidate venv paths (glob) --")
candidates = [
    "/opt/vnstock/.venv/bin/pip",
    "/opt/vnstock/.venv/bin/python",
    "/home/runner/work/*/*/opt/vnstock/.venv/bin/pip",
    "/home/runner/.venv/bin/pip",
]
for pattern in candidates:
    matches = glob.glob(pattern, recursive=True)
    if matches:
        for m in matches:
            print(f"  FOUND: {m}")
    else:
        print(f"  none : {pattern}")

# 5. Check /opt/vnstock
print("\n-- /opt/vnstock tree --")
opt_path = "/opt/vnstock"
if os.path.exists(opt_path):
    for root, dirs, files in os.walk(opt_path):
        depth = root[len(opt_path):].count(os.sep)
        if depth > 2:
            dirs.clear()
            continue
        indent = "  " * (depth + 1)
        print(f"{indent}{os.path.basename(root) or opt_path}/")
else:
    print(f"  {opt_path} KHONG ton tai")

# 6. Working dir nested venv
print(f"\n-- Working dir: {os.getcwd()} --")
nested = glob.glob(os.path.join(os.getcwd(), "**/.venv/bin/pip"), recursive=True)
if nested:
    for v in nested:
        print(f"  NESTED VENV: {v}")
else:
    print(f"  Khong co .venv nested")

# 7. Env vars
print("\n-- Env vars --")
for k in ["VNSTOCK_VENV_PATH", "VIRTUAL_ENV"]:
    print(f"  {k}: {os.environ.get(k, '(unset)')}")

print("\n" + "=" * 60)
print("  DONE")
print("=" * 60)
