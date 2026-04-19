import json
import logging
import threading
import time
import urllib.request

from netinventory.config import get_app_paths, get_hub_settings
from netinventory.storage.db import Database

logger = logging.getLogger(__name__)

def run_sync_worker() -> None:
    paths = get_app_paths()
    settings = get_hub_settings()
    db = Database(paths)
    
    # Run the worker cycle indefinitely every 60 seconds
    while True:
        try:
            last_sync = db.get_last_sync_time()
            bundle = db.export_bundle_data(since_iso=last_sync)
            
            records = bundle.get("records", [])
            if not records:
                time.sleep(60)
                continue
                
            payload = {
                "kind": "sync-bundle",
                "description": f"Delta Sync ({len(records)} records)",
                "payload": bundle
            }
            
            target_url = f"{settings.track_base_url}/netinventory/api/simple-ingest"
            client_id = str(bundle.get("source_device_id", "unknown"))
            
            req = urllib.request.Request(
                target_url,
                data=json.dumps(payload, ensure_ascii=True).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "X-Track-Client-Id": client_id
                },
                method="POST"
            )
            
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    newest: str | None = None
                    for rec in records:
                        if isinstance(rec, dict):
                            cat = rec.get("created_at") or rec.get("observed_at")
                            if isinstance(cat, str):
                                if newest is None or cat > newest:
                                    newest = cat
                    
                    if newest:
                        db.set_last_sync_time(newest)
                        logger.info(f"Sync complete. Updated last_sync_time to {newest}")
                        
        except Exception as e:
            logger.warning(f"Background auto-sync failed: {e}")
            
        time.sleep(60)


def start_sync_worker() -> None:
    logger.info("Starting Auto-Sync background worker...")
    t = threading.Thread(target=run_sync_worker, daemon=True, name="AutoSyncWorker")
    t.start()
