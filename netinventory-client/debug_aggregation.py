import sys
import os

# Add ui to path
sys.path.append(os.path.join(os.getcwd(), 'ui'))

from analysis_module import load_snapshots, aggregate_networks

DATA_DIR = os.path.join(os.getcwd(), 'data')
snap_dir = os.path.join(DATA_DIR, 'snapshots')

print(f"Loading snapshots from {snap_dir}...")
snapshots = load_snapshots(snap_dir)
print(f"Loaded {len(snapshots)} snapshots.")

print("Aggregating networks...")
try:
    networks = aggregate_networks(snapshots)
    print(f"Aggregation successful. Found {len(networks)} networks.")
    for net_id, data in networks.items():
        print(f" - Network {net_id}: {len(data['hosts'])} hosts, {data['count']} snapshots.")
except Exception as e:
    print(f"Aggregation FAILED: {e}")
    import traceback
    traceback.print_exc()
