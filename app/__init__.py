import json
import os
import subprocess
import requests
import time
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, jsonify, Response, redirect, url_for, session
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config

app = Flask(__name__)
app.config.from_object(Config)
csrf = CSRFProtect(app)

# Ensure data directory exists
os.makedirs(app.config['DATA_DIR'], exist_ok=True)

@app.context_processor
def inject_config():
    title = "Museum Kiosk Control"
    subtitle = "Monitoring museum displays across the Tailscale network."
    language = "en"
    
    if os.path.exists(app.config.get('CONFIG_JSON')):
        try:
            with open(app.config.get('CONFIG_JSON'), 'r') as f:
                cfg = json.load(f)
                title = cfg.get('title', title)
                subtitle = cfg.get('subtitle', subtitle)
                language = cfg.get('language', language)
        except Exception:
            pass
            
    t = {}
    try:
        with open(os.path.join(app.config['DATA_DIR'], 'translations.json'), 'r') as f:
            all_t = json.load(f)
            t = all_t.get(language, all_t.get('en', {}))
    except Exception:
        pass
        
    return dict(app_title=title, app_subtitle=subtitle, app_lang=language, t=t)

def load_devices():
    if not os.path.exists(app.config['DEVICES_FILE']):
        return []
    try:
        with open(app.config['DEVICES_FILE'], 'r') as f:
            return json.load(f)
    except json.JSONDecodeError:
        return []

def load_auth():
    if not os.path.exists(app.config['AUTH_FILE']):
        default = {"admin_password": generate_password_hash("museum_default")}
        try:
            with open(app.config['AUTH_FILE'], 'w') as f:
                json.dump(default, f, indent=2)
        except Exception as e:
            print(f"Error creating auth.json: {e}")
        return default
    try:
        with open(app.config['AUTH_FILE'], 'r') as f:
            data = json.load(f)
            pw = data.get('admin_password', '')
            if not pw.startswith('scrypt:') and not pw.startswith('pbkdf2:'):
                data['admin_password'] = generate_password_hash(pw if pw else 'museum_default')
                try:
                    with open(app.config['AUTH_FILE'], 'w') as f:
                        json.dump(data, f, indent=2)
                except Exception:
                    pass
            return data
    except json.JSONDecodeError:
        return {"admin_password": generate_password_hash("museum_default")}

def save_devices(devices):
    with open(app.config['DEVICES_FILE'], 'w') as f:
        json.dump(devices, f, indent=2)

def get_tailscale_devices():
    """Scrape device statuses from `tailscale status`."""
    try:
        # For security and stability, we should probably parse JSON if possible:
        # tailscale status --json
        result = subprocess.run(['tailscale', 'status', '--json'], capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        ts_devices = {}
        # Parse Peer list
        for pubkey, peer in data.get('Peer', {}).items():
             hostname = peer.get('HostName', '')
             if hostname.startswith('fons-'):
                online = peer.get('Online', False)
                ips = peer.get('TailscaleIPs', [])
                ts_devices[hostname] = {
                    'online': online,
                    'ip': ips[0] if ips else None
                }
        return ts_devices
    except Exception as e:
        print(f"Error fetching tailscale status: {e}")
        return {}

SCRAPE_CACHE = {}
CACHE_TTL = 60 # 60 seconds

def scrape_kiosk_status(ip, port=8080):
    """Scrape the active video, play mode, and timezone schedules from the kioskplayer's webcontrol."""
    global SCRAPE_CACHE
    now = time.time()
    
    # Return quick cached hit if available and not expired
    if ip in SCRAPE_CACHE and now - SCRAPE_CACHE[ip]['timestamp'] < CACHE_TTL:
        return SCRAPE_CACHE[ip]['data']
        
    data = {
        'active_video': "Unknown / Not playing",
        'play_mode': "Unknown",
        'loop_mode': "Unknown",
        'default_subtitle': "Unknown",
        'start_time': "N/A",
        'end_time': "N/A"
    }
    
    try:
        url = f"http://{ip}:{port}/"
        response = requests.get(url, timeout=3)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Look for <select name="active_video">
        select = soup.find('select', {'name': 'active_video'})
        if select:
            selected_option = select.find('option', selected=True)
            if selected_option:
                data['active_video'] = selected_option.text.split(':', 1)[-1].strip()
                
        # Look for play mode
        play_mode_select = soup.find('select', {'name': 'play_mode'})
        if play_mode_select:
             opt = play_mode_select.find('option', selected=True)
             if opt: data['play_mode'] = opt.get('value', 'Unknown')

        # Look for loop mode
        loop_mode_select = soup.find('select', {'name': 'loop_mode'})
        if loop_mode_select:
             opt = loop_mode_select.find('option', selected=True)
             if opt: data['loop_mode'] = opt.text.strip()

        # Look for default_subtitle
        subtitle_select = soup.find('select', {'name': 'default_subtitle'})
        if subtitle_select:
             opt = subtitle_select.find('option', selected=True)
             if opt: data['default_subtitle'] = opt.text.strip()
             
        # Look for screensaver_start_hhmm
        start_input = soup.find('input', {'name': 'screensaver_start_hhmm'})
        if start_input: data['start_time'] = start_input.get('value', 'N/A')
        
        # Look for screensaver_end_hhmm
        end_input = soup.find('input', {'name': 'screensaver_end_hhmm'})
        if end_input: data['end_time'] = end_input.get('value', 'N/A')
        
    except Exception as e:
        print(f"Error scraping kiosk at {ip}: {e}")
        
    # Overwrite the cache
    SCRAPE_CACHE[ip] = {'timestamp': now, 'data': data}
    return data

@app.route('/')
def index():
    configured_devices = load_devices()
    ts_devices = get_tailscale_devices()
    
    # Merge configured device data with live Tailscale status
    dashboard_devices = []
    
    # Auto-discover unconfigured fons-* devices
    configured_hostnames = {d.get('hostname') for d in configured_devices}
    for ts_host, ts_data in ts_devices.items():
        if ts_host not in configured_hostnames:
             configured_devices.append({
                 "id": f"auto-{ts_host}",
                 "hostname": ts_host,
                 "name": ts_host.capitalize(),
                 "type": "kioskplayer",
                 "room": "Unknown",
                 "placement": "Unknown",
                 "notes": "Auto-discovered via Tailscale",
                 "web_port": 8080,
                 "ssh_user": "pi"
             })
             save_devices(configured_devices)
    
    # Refresh configured devices after potential auto-discovery
    configured_devices = load_devices()
    
    for device in configured_devices:
        hostname = device.get('hostname')
        ts_info = ts_devices.get(hostname, {})
        
        status = 'Online' if ts_info.get('online') else 'Offline'
        active_video = "N/A"
        
        if status == 'Online' and device.get('type') == 'kioskplayer' and ts_info.get('ip'):
            scraped_data = scrape_kiosk_status(ts_info['ip'], device.get('web_port', 8080))
        else:
            scraped_data = {
                'active_video': 'N/A',
                'play_mode': 'N/A',
                'loop_mode': 'N/A',
                'default_subtitle': 'N/A',
                'start_time': 'N/A',
                'end_time': 'N/A'
            }

        dashboard_devices.append({
            **device,
            'status': status,
            'ip': ts_info.get('ip'),
            **scraped_data
        })

    # Sort devices: Online first, then offline, then alphabetically by name
    dashboard_devices.sort(key=lambda x: (
        0 if x.get('status') == 'Online' else 1,
        x.get('name', '').lower()
    ))

    return render_template('index.html', devices=dashboard_devices)

# IP rate-limiting state
FAILED_LOGINS_GLOBAL = []
FAILED_LOGINS_IP = {}

@app.route('/login', methods=['GET', 'POST'])
def login():
    global FAILED_LOGINS_GLOBAL, FAILED_LOGINS_IP
    if request.method == 'POST':
        client_ip = request.remote_addr
        now = time.time()
        
        # Cleanup old timestamps
        FAILED_LOGINS_GLOBAL = [t for t in FAILED_LOGINS_GLOBAL if now - t < 60] # 1 min global window
        
        # Ensure FAILED_LOGINS_IP doesn't leak memory infinitely in a distributed brute-force
        if len(FAILED_LOGINS_IP) > 500:
             FAILED_LOGINS_IP.clear()
        
        if client_ip in FAILED_LOGINS_IP:
            FAILED_LOGINS_IP[client_ip] = [t for t in FAILED_LOGINS_IP[client_ip] if now - t < 120] # 2 min IP window
        else:
            FAILED_LOGINS_IP[client_ip] = []
            
        # Check limits
        if len(FAILED_LOGINS_GLOBAL) >= 20:
            return render_template('login.html', error="System is temporarily locked down due to too many failed attempts.")
            
        if len(FAILED_LOGINS_IP[client_ip]) >= 3:
            return render_template('login.html', error="Your IP is temporarily blocked due to too many failed attempts.")
    
        auth_data = load_auth()
        password = request.form.get('password')
        stored_hash = auth_data.get('admin_password', '')
        
        if stored_hash and check_password_hash(stored_hash, password):
            session['logged_in'] = True
            
            # Follow redirect if Next is specified
            next_url = request.args.get('next')
            if next_url and next_url.startswith('/'):
                 return redirect(next_url)
                 
            return redirect(url_for('admin'))
        else:
            FAILED_LOGINS_GLOBAL.append(now)
            FAILED_LOGINS_IP[client_ip].append(now)
            return render_template('login.html', error="Invalid password")
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('index'))

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    devices = load_devices()
    
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add_device':
            new_hostname = request.form.get('hostname').strip()
            if new_hostname and not any(d.get('hostname') == new_hostname for d in devices):
                 new_id = f"manual-{new_hostname.replace('.', '-')}"
                 devices.append({
                     "id": new_id,
                     "hostname": new_hostname,
                     "name": new_hostname.capitalize(),
                     "type": "kioskplayer",
                     "room": "Added Manually",
                     "placement": "Unknown",
                     "notes": "Added via Admin Panel",
                     "web_port": 8080,
                     "ssh_user": "pi"
                 })
                 save_devices(devices)
        elif action == 'update_settings':
            new_title = request.form.get('app_title', '').strip()
            new_subtitle = request.form.get('app_subtitle', '').strip()
            new_lang = request.form.get('language', 'en').strip()
            try:
                cfg = {}
                cfg_path = app.config.get('CONFIG_JSON')
                if os.path.exists(cfg_path):
                    with open(cfg_path, 'r') as f:
                        cfg = json.load(f)
                
                if new_title: cfg['title'] = new_title
                if new_subtitle: cfg['subtitle'] = new_subtitle
                if new_lang: cfg['language'] = new_lang
                
                with open(cfg_path, 'w') as f:
                    json.dump(cfg, f, indent=4)
            except Exception as e:
                print(f"Error updating config: {e}")
        else:
            # Simple handling to update location or notes on a device
            device_id = request.form.get('device_id')
            for d in devices:
                if d.get('id') == device_id:
                    d['room'] = request.form.get('room')
                    d['placement'] = request.form.get('placement')
                    d['notes'] = request.form.get('notes')
                    d['ssh_user'] = request.form.get('ssh_user')
                    break
            save_devices(devices)
        return redirect(url_for('admin'))
        
    ts_devices = get_tailscale_devices()
    for d in devices:
        ts_info = ts_devices.get(d.get('hostname'), {})
        d['ip'] = ts_info.get('ip')
        
    return render_template('admin.html', devices=devices)

@app.route('/proxy/<device_id>/', methods=['GET', 'POST'])
@app.route('/proxy/<device_id>/<path:subpath>', methods=['GET', 'POST'])
@csrf.exempt
def proxy(device_id, subpath=""):
    """Secure proxy wrapper around the device's web interface."""
    if not session.get('logged_in'):
        # Redirect to login page with the target URL as the 'next' parameter
        target_path = f"/proxy/{device_id}/" if not subpath else f"/proxy/{device_id}/{subpath}"
        return redirect(url_for('login', next=target_path))
        
    # Prevent directory traversal
    if '..' in subpath.split('/') or subpath.startswith('/'):
        return "Invalid path requested", 400
        
    # Lookup the device IP via tailscale status
    configured_devices = load_devices()
    device = next((d for d in configured_devices if d.get('id') == device_id), None)
    
    if not device:
         return "Device not found", 404
         
    ts_devices = get_tailscale_devices()
    ts_info = ts_devices.get(device.get('hostname'))
    if not ts_info or not ts_info.get('online') or not ts_info.get('ip'):
         return "Device is offline or unreachable", 502
         
    target_url = f"http://{ts_info['ip']}:{device.get('web_port', 8080)}/{subpath}"
    
    try:
        if request.method == 'POST':
            # Forward POST request
            resp = requests.post(
                target_url,
                data=request.form,
                files=request.files,
                timeout=10
            )
        else:
            # Forward GET request
            resp = requests.get(target_url, params=request.args, timeout=10)
            
        # Rewrite links in HTML so they stay within the proxy
        content = resp.content
        if 'text/html' in resp.headers.get('Content-Type', ''):
             # Highly naive replacement for prototyping; beautifulsoup or proper HTML rewriting is better
             content_str = content.decode('utf-8', 'ignore')
             content_str = content_str.replace('action="/', f'action="/proxy/{device_id}/')
             content_str = content_str.replace('href="/', f'href="/proxy/{device_id}/')
             content = content_str.encode('utf-8')
             
        excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
        headers = [(name, value) for (name, value) in resp.headers.items()
                   if name.lower() not in excluded_headers]
                   
        return Response(content, resp.status_code, headers)
        
    except Exception as e:
        return f"Proxy Error: {e}", 502

@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    
    # Apply strict CSP to our app views, but exempt the proxy views since they
    # load external HTML that we can't reliably inline-permit or hash.
    if not request.path.startswith('/proxy/'):
         response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'none';"
         
    return response

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
