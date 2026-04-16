import json
import os
import glob
import sys
from collections import defaultdict

def load_snapshots(data_dir):
    """Loads all JSON snapshots from the data directory."""
    snapshots = []
    if not os.path.exists(data_dir):
        return []
        
    files = glob.glob(os.path.join(data_dir, "*.json"))
    for f in files:
        try:
            with open(f, 'r') as fd:
                data = json.load(fd)
                # Attach filename for reference
                data['_filename'] = os.path.basename(f)
                snapshots.append(data)
        except Exception as e:
            print(f"Error loading {f}: {e}", file=sys.stderr)
    return snapshots

def extract_arp_neighbors(snapshot_data):
    """Extracts neighbors from ARP cache plugin output."""
    neighbors = []
    if 'arp_cache' in snapshot_data and 'facts' in snapshot_data['arp_cache']:
        arp_facts = snapshot_data['arp_cache']['facts']
        for ip, details in arp_facts.items():
            neighbors.append({
                'ip': ip,
                'mac': details.get('hw_addr'),
                'device': details.get('device')
            })
    return neighbors

def aggregate_networks(snapshots):
    """Groups snapshots by NetID and merges host data."""
    networks = defaultdict(lambda: {
        'net_id': '',
        'count': 0,
        'first_seen': None,
        'last_seen': None,
        'hosts': {},  # MAC -> HostDetails
        'snapshots': []
    })

    for snap in snapshots:
        net_id = snap.get('net_id', 'unknown')
        ts = snap.get('timestamp')
        
        net = networks[net_id]
        net['net_id'] = net_id
        net['count'] += 1
        net['snapshots'].append(snap['_filename'])
        
        if not net['first_seen'] or (ts and str(ts) < str(net['first_seen'])):
            net['first_seen'] = ts
        if not net['last_seen'] or (ts and str(ts) > str(net['last_seen'])):
            net['last_seen'] = ts
        
        neighbors = extract_arp_neighbors(snap.get('data', {}))
        for n in neighbors:
            mac = n.get('mac')
            if not mac: continue
            
            if mac not in net['hosts']:
                net['hosts'][mac] = {
                    'mac': mac,
                    'ips': set(),
                    'names': set(), # Placeholder for future
                    'vendors': 'Unknown' # Placeholder
                }
            
            net['hosts'][mac]['ips'].add(n['ip'])

    # Convert sets to lists for JSON serialization
    results = {}
    for net_id, data in networks.items():
        # Clean up host data
        hosts_list = []
        for mac, hdata in data['hosts'].items():
            hdata['ips'] = list(hdata['ips'])
            hdata['names'] = list(hdata['names'])
            hosts_list.append(hdata)
        
        data['hosts'] = hosts_list
        results[net_id] = data
        
    return results
