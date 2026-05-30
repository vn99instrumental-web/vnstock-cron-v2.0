"""
scripts/debug_find_venv.py
===========================
Tìm venv và vnstock_ta nằm ở đâu thực sự sau cache restore.
Trigger qua debug.yml với input: scripts/debug_find_venv.py
"""
import os
import sys
import subprocess

print("=" * 60)
print("  FIND VENV DIAGNOSTIC")
print("=" * 60)

# 1. Tìm tất cả pip executables trên hệ thống
print("\n── All pip executables ──")
result = subprocess.run(
    ["find", "/", "-name", "pip", "-o", "-name", "pip3"],
    capture_output=True, text=True, timeout=10
)
for line in result.stdout.splitlines():
    if "vnstock" in line or "venv" in line:
        print(f"  [venv] {line}")
    else:
        print(f"         {line}")

# 2. Tìm vnstock_ta
print("\n── Find vnstock_ta ──")
result2 = subprocess.run(
    ["find", "/", "-name", "vnstock_ta", "-type", "d"],
    capture_output=True, text=True, timeout=10
)
print(result2.stdout or "  (not found)")

# 3. Tìm thư mục .venv
print("\n── Find .venv directories ──")
result3 = subprocess.run(
    ["find", "/", "-name", ".venv", "-type", "d", "-maxdepth", "8"],
    capture_output=True, text=True, timeout=10
)
print(result3.stdout or "  (not found)")

# 4. Check /opt/
print("\n── /opt/ contents ──")
try:
    for root, dirs, files in os.walk("/opt", topdown=True):
        depth = root.count(os.sep) - "/opt".count(os.sep)
        if depth > 3:
            dirs.clear()
            continue
        indent = "  " * depth
        print(f"{indent}{os.path.basename(root)}/")
except Exception as e:
    print(f"  Error: {e}")

# 5. Check working dir
print(f"\n── Working directory: {os.getcwd()} ──")
for item in os.listdir("."):
    print(f"  {item}")

# 6. Which python đang chạy script này
print(f"\n── Current Python ──")
print(f"  sys.executable: {sys.executable}")
print(f"  sys.version: {sys.version}")

# 7. Try import vnstock_ta
print(f"\n── Import test ──")
try:
    import vnstock_ta
    print(f"  vnstock_ta: OK — {vnstock_ta.__file__}")
except ImportError as e:
    print(f"  vnstock_ta: FAIL — {e}")

print("\n" + "=" * 60)
print("  DONE — copy output này để debug")
print("=" * 60)
