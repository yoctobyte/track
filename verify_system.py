#!/usr/bin/env python3
import os
import sys
import shutil
import subprocess

def check_step(name, success):
    if success:
        print(f"[\033[92mOK\033[0m] {name}")
    else:
        print(f"[\033[91mFAIL\033[0m] {name}")
        return False
    return True

def verify_system():
    print(">>> Verifying NetInventory Environment...")
    all_good = True

    # 1. Check Directories
    dirs = ['data/snapshots', 'venv', 'cmd/netinv', 'ui']
    for d in dirs:
        exists = os.path.exists(d)
        all_good &= check_step(f"Directory exists: {d}", exists)

    # 2. Check Go Binary
    go_bin = './netinv'
    if os.path.exists(go_bin):
        check_step("Go binary built", True)
        
        # Check capabilities
        try:
            getcap = subprocess.check_output(['getcap', go_bin]).decode()
            if 'cap_net_admin' in getcap and 'cap_net_raw' in getcap:
                 check_step("Go binary capabilities (net_admin, net_raw)", True)
            else:
                 check_step("Go binary capabilities", False)
                 print("    Run: sudo setcap cap_net_raw,cap_net_admin=eip ./netinv")
                 all_good = False
        except Exception as e:
            print(f"    Error checking capabilities: {e}")
            all_good = False
    else:
        check_step("Go binary built", False)
        all_good = False

    # 3. Check Python Depedencies
    # We assume we are running inside the venv or with access to it
    try:
        import flask
        check_step("Python dependency: Flask", True)
    except ImportError:
        check_step("Python dependency: Flask", False)
        all_good = False

    # 4. Check Test Data
    try:
        from ui.analysis_module import load_snapshots
        snaps = load_snapshots('data/snapshots')
        print(f"    Found {len(snaps)} snapshots in data/snapshots")
        check_step("Snapshot loading", True)
    except Exception as e:
        check_step("Snapshot loading", False)
        print(f"    Error: {e}")
        all_good = False

    print("-" * 40)
    if all_good:
        print("\n\033[92m>>> System is ready to run!\033[0m")
        sys.exit(0)
    else:
        print("\n\033[91m>>> System has issues. Please fix them above.\033[0m")
        sys.exit(1)

if __name__ == "__main__":
    verify_system()
