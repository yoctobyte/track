# NetInventory Minimal

The `netinventory-minimal` client is a lightweight, non-invasive shell script designed to be distributed to active devices via Ansible (`devicecontrol`).

It runs on a cron interval and captures basic network diagnostics without keeping any local state or disrupting operations. 

**Features:**
- External IP retrieval.
- Local ARP tables / Neighbors.
- Network interface and route states.
- Wireless Link Speeds (wlan0).
- Utilizes `X-Track-Client-Id` authentication bypass against `netinventory-host`.

## Configuration Parameters

Typically managed via Ansible in `/etc/netinventory-minimal.conf`:

```bash
TRACK_SIMPLE_URL="https://your-public-track-url.com/netinventory/api/simple-ingest"
TRACK_CLIENT_ID="<ansible-generated-uuid>"
```
