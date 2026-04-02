from flask import Flask, render_template, jsonify, request
import os
import json
from analysis_module import load_snapshots, aggregate_networks

app = Flask(__name__)
# Adjust path to point to the correct data directory relative to ui/app.py
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
ANNOTATIONS_FILE = os.path.join(DATA_DIR, 'annotations.json')

def load_annotations():
    if os.path.exists(ANNOTATIONS_FILE):
        try:
            with open(ANNOTATIONS_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_annotations(data):
    with open(ANNOTATIONS_FILE, 'w') as f:
        json.dump(data, f, indent=2)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/active_network')
def get_active_network():
    """Returns the latest active net_id."""
    active_path = os.path.join(DATA_DIR, 'snapshots', 'active.json')
    if not os.path.exists(active_path):
        return jsonify({'active_net_id': None})
    
    try:
        with open(active_path, 'r') as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/networks')
def get_networks():
    """Returns aggregated network data."""
    # Look for snapshots in data/snapshots/ (Production) or data/test_samples/ (Dev)
    # The Go collector writes to data/snapshots/
    snap_dir = os.path.join(DATA_DIR, 'snapshots')
    
    if not os.path.exists(snap_dir) or not os.listdir(snap_dir):
        # Fallback to test samples if empty
        test_dir = os.path.join(DATA_DIR, 'test_samples')
        if os.path.exists(test_dir):
            snap_dir = test_dir

    snapshots = load_snapshots(snap_dir)
    networks = aggregate_networks(snapshots)
    
    # Merge annotations
    annotations = load_annotations()
    for net_id, net_data in networks.items():
        if net_id in annotations:
            net_data['annotation'] = annotations[net_id]
            
    return jsonify(networks)

@app.route('/api/networks/<net_id>')
def get_network_graph(net_id):
    """Returns graph data for a specific network."""
    snap_dir = os.path.join(DATA_DIR, 'snapshots')
    if not os.path.exists(snap_dir) or not os.listdir(snap_dir):
        test_dir = os.path.join(DATA_DIR, 'test_samples')
        if os.path.exists(test_dir):
            snap_dir = test_dir
        
    snapshots = load_snapshots(snap_dir)
    networks = aggregate_networks(snapshots)
    
    if net_id not in networks:
        return jsonify({'error': 'Network not found'}), 404
        
    net = networks[net_id]
    
    # Findings the latest snapshot for this network for "Raw View" and "Playbook Status"
    latest_snap = None
    latest_ts = None
    
    # aggregate_networks returned filenames in 'snapshots' list.
    # We need to find the actual data.
    # We loaded all snapshots in 'snapshots' var (list of dicts).
    for snap in snapshots:
        if snap.get('net_id') == net_id:
            ts = snap.get('timestamp')
            if latest_snap is None or ts > latest_ts:
                latest_ts = ts
                latest_snap = snap

    # Format for a graph visualization (Nodes + Links)
    nodes = []
    links = []
    
    # Central Node (The Network)
    # Include annotation in the graph context too
    annotations = load_annotations()
    note = annotations.get(net_id, "")
    
    nodes.append({
        'id': 'net', 
        'label': f"Network {net_id}", 
        'type': 'network',
        'annotation': note
    })
    
    for host in net['hosts']:
        h_id = host['mac']
        nodes.append({
            'id': h_id,
            'label': f"{host['ips'][0]} ({host['mac']})",
            'type': 'host',
            'details': host
        })
        links.append({'source': 'net', 'target': h_id})
        
    return jsonify({
        'nodes': nodes, 
        'links': links,
        'latest_snapshot': latest_snap # Include full raw data
    })

@app.route('/api/networks/<net_id>/annotate', methods=['POST'])
def annotate_network(net_id):
    data = request.json
    note = data.get('annotation', '')
    use_gps = data.get('use_gps', False)
    
    if use_gps:
        # Find latest snapshot for this network to get GPS
        snap_dir = os.path.join(DATA_DIR, 'snapshots')
        snapshots = load_snapshots(snap_dir)
        lat, lon = None, None
        latest_ts = None
        
        for snap in snapshots:
            if snap.get('net_id') == net_id:
                ts = snap.get('timestamp')
                if latest_ts is None or ts > latest_ts:
                    latest_ts = ts
                    gps_data = snap.get('data', {}).get('gps_location', {}).get('facts', {})
                    lat = gps_data.get('lat')
                    lon = gps_data.get('lon')
        
        if lat is not None and lon is not None:
            note += f"\n[GPS: {lat}, {lon}]"
    
    annotations = load_annotations()
    annotations[net_id] = note
    save_annotations(annotations)
    
    return jsonify({'success': True})

@app.route('/api/logs')
def get_logs():
    """Returns the last 100 lines of the engine log."""
    log_path = os.path.join(os.path.dirname(DATA_DIR), 'netinv.log')
    if not os.path.exists(log_path):
        return jsonify({'logs': 'Log file not found.'})
    
    try:
        with open(log_path, 'r') as f:
            lines = f.readlines()
            return jsonify({'logs': "".join(lines[-100:])})
    except Exception as e:
        return jsonify({'logs': f"Error reading logs: {e}"})

if __name__ == '__main__':
    app.run(port=8888, debug=True)
