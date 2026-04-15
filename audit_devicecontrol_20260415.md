# Security Audit Report: DeviceControl Subproject
**Date:** 2026-04-15
**Target:** `/home/rene/track/devicecontrol`

## Executive Summary
A comprehensive security review of the `devicecontrol` web interface and its associated shell tooling was performed. The application allows users to execute pre-approved Ansible playbooks against distinct environments. 

The most critical vulnerabilities concern a "fail-open" design surrounding access control, meaning unauthenticated attackers reaching the application directly can invoke powerful Ansible actions. We also identified vulnerabilities around missing CSRF protection, SSH argument injection in shell tooling, and information disclosure within the web UI.

---

## Findings

### 1. Fail-Open Authentication Bypass (Critical)
**Description:** 
The application manages environments via proxy headers (using `X-Trackhub-Authenticated` and `X-Trackhub-Environment`). When inspecting these headers, if the request does not originate from a trusted proxy (`127.0.0.1`, `::1`) or if it lacks authentication headers, the `proxy_environment()` function silently returns `None`. The downstream wrapper `current_environment()` then falls back to a `default_environment` (defaulting to `testing`). 
Because none of the Flask routes (like the `@app.post("/run/<action_id>")` endpoint) restrict access, the application assumes any unauthenticated request should simply operate against the default environment.

**Impact:** 
An unauthenticated attacker who gains direct access to port `5021` (via the local network, VPC, or misconfigured firewall) can perform completely unauthenticated Remote Code Execution (RCE) against all targets stored in the default `testing` inventory by hitting `/run/update-and-reboot` or `/run/screenshot`.

**Remediation:** 
Do not fall back unconditionally to a default workspace for unauthenticated requests. Introduce explicit authorization blocks (e.g., `@login_required` or a before-request middleware) that return `401 Unauthorized` or `403 Forbidden` if valid tracked authentication headers are not provided.

### 2. Missing Cross-Site Request Forgery (CSRF) Protection (High)
**Description:** 
The web interface routes rely on form submission (`method="post"`) to invoke state-changing actions, but do not utilize CSRF tokens. Assuming the authentication is handled via session cookies managed by the upstream tracking proxy, the browser will automatically submit those authentication cookies along with cross-domain requests.

**Impact:** 
If an authenticated user visits a site controlled by an attacker, the attacker can silently invoke arbitrary actions against the user's active Ansible environment by dynamically generating a POST form pointing to `<devicecontrol-url>/run/reboot` and submitting it in the background.

**Remediation:** 
Implement CSRF protection (e.g., using `Flask-WTF`'s `CSRFProtect`) ensuring all state-changing `POST` routes require a valid token. Enforce `SameSite=Lax` or `Strict` on proxy authentication session cookies.

### 3. SSH Option Injection in Deployment Scripts (High)
**Description:** 
The administrator scripts `tools/bootstrap-host.sh` and `tools/autobootstrap.sh` dynamically invoke `ssh` commands incorporating variables populated from the Ansible inventory (such as `$login_user` and `$ANSIBLE_USER` variables). The scripts fail to use `--` to indicate the end of SSH option processing.
Example: `ssh "$login_user@$target_host" "$remote_cmd" <<'EOF'`

**Impact:** 
If a user is compromised or an attacker can append entries to the `.ini` inventory file, they can specify a maliciously crafted `login_user`, such as `-oProxyCommand=sh -c 'touch /tmp/pwned' #`. SSH will parse the username as options before connecting, subsequently executing arbitrary local shell commands on the administrator's operational workstation.

**Remediation:** 
Sanitize inputs or format SSH commands securely by using the double dash `--` marker (e.g., `ssh [options] -- "$login_user@$target_host" "$remote_cmd"`).

### 4. Sensitive Information Disclosure via Inventory Visualization (Medium)
**Description:** 
The `index.html` template parses the standard Ansible `.ini` inventory formats and renders every stored variable (`host.vars.items()`) in plain text. Ansible repositories commonly hold deployment secrets directly within the inventory such as `ansible_password`, `ansible_become_pass`, and various system authorization tokens.

**Impact:** 
Any individual with read access to the dashboard is able to inspect and compromise bare secrets meant strictly for mechanical deployment purposes, directly on the application homepage.

**Remediation:** 
Implement template filters to actively redact keys matching sensitive strings (e.g., `*pass*`, `*key*`, `*secret*`, `*token*`) before flushing them to the `index.html` template view.

### 5. Python Code Injection via Environment Variables (Medium)
**Description:** 
The `run.sh` entrypoint executes the primary Flask app via `$VENV/bin/python -c ...`. It directly interpolates the `$HOST` and `$PORT` environment variables into the Python `-c` string parameter without adequate sanitization (`host='$HOST'`).

**Impact:** 
If a local adversary or a malicious environment pipeline controls the `DEVICECONTROL_HOST` string, they can inject standard Python commands by breaking out of the interpreted quotes (e.g., `0.0.0.0', port=5021); import os; os.system('curl ...') #`).

**Remediation:** 
Fetch configuration exclusively through `os.environ.get()` directly inside the raw Python bootstrap string, instead of expanding bash variables into the python source syntax.

### 6. Weak Default Cryptographic Secret (Low)
**Description:** 
The application declares `app.config["SECRET_KEY"] = os.environ.get("DEVICECONTROL_SECRET_KEY", "devicecontrol-dev-shell")`. 

**Impact:** 
Using generic defaults drastically decreases session entropy. While `devicecontrol` does not store rich authentication sessions within Flask directly right now, utilizing session variables (such as Flask's `flash()` mechanism or moving future CSRF tokens to the session) leaves the session cookie structurally vulnerable to signature forgery.

**Remediation:** 
Use `os.urandom(32)` as a default fallback instead of a fixed string, or force the application to gracefully crash if the environment is strictly `production` and the secret is missing.
