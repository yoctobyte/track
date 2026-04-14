#!/usr/bin/env python3
import json
import os
import glob
import sys
from collections import defaultdict

def load_snapshots(data_dir):
    """Loads all JSON snapshots from the data directory."""
    snapshots = []
    files = glob.glob(os.path.join(data_dir, "*.json"))
    for f in files:
        try:
            with open(f, 'r') as fd:
                snapshots.append(json.load(fd))
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
        'count': 0,
        'hosts': {},  # MAC -> HostDetails
        'graph_edges': set()
    })

    for snap in snapshots:
        net_id = snap.get('net_id', 'unknown')
        networks[net_id]['count'] += 1
        
        # In a real scenario, we'd identify "Self" from InterfacePlugin
        # For now, let's treat ARP entries as discovered neighbors
        
        neighbors = extract_arp_neighbors(snap.get('data', {}))
        for n in neighbors:
            mac = n.get('mac')
            if not mac: continue
            
            if mac not in networks[net_id]['hosts']:
                networks[net_id]['hosts'][mac] = {
                    'ips': set(),
                    'names': set()
                }
            
            networks[net_id]['hosts'][mac]['ips'].add(n['ip'])
            
            # Assuming 'Self' is the observer, we add an edge from Observer to Neighbor
            # Since we don't have explicit 'Self' MAC in all plugins yet, we represent the snapshot source as a node
            # But for a cleaner graph, let's just show the mesh of ARP neighbors
            pass

    return networks

def generate_dot_graph(networks):
    """Generates a Graphviz DOT representation."""
    lines = ["digraph NetInventory {", "  rankdir=LR;", "  node [shape=box style=filled fillcolor=\"#E0F7FA\"];"]
    
    for net_id, net_data in networks.items():
        lines.append(f"  subgraph cluster_{net_id} {{")
        lines.append(f"    label = \"Network {net_id}\";")
        lines.append("    style=filled; color=\"#F5F5F5\";")
        
        # Nodes
        for mac, details in net_data['hosts'].items():
            ips = "\\n".join(details['ips'])
            label = f"{mac}\\n{ips}"
            node_id = f"node_{mac.replace(':', '')}"
            lines.append(f"    {node_id} [label=\"{label}\"];")
        
        lines.append("  }")
    
    lines.append("}")
    return "\n".join(lines)

def main():
    if len(sys.argv) < 2:
        print("Usage: analyze_snapshots.py <data_dir>")
        sys.exit(1)
        
    data_dir = sys.argv[1]
    snapshots = load_snapshots(data_dir)
    print(f"Loaded {len(snapshots)} snapshots.")
    
    networks = aggregate_networks(snapshots)
    
    print(f"\nFound {len(networks)} unique networks:")
    for net_id, data in networks.items():
        print(f" - {net_id}: {data['count']} snapshots, {len(data['hosts'])} unique hosts identified via ARP")
    
    print("\nGenerating graph...")
    dot_output = generate_dot_graph(networks)
    
    out_file = "network_graph.dot"
    with open(out_file, "w") as f:
        f.write(dot_output)
    
    print(f"Graph saved to {out_file}. Render with: dot -Tpng {out_file} -o graph.png")

if __name__ == "__main__":
    main()
