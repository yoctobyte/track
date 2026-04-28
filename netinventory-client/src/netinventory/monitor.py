import logging
import threading
import time

from netinventory.config import get_app_paths
from netinventory.core.tasks import TaskTrigger
from netinventory.storage.db import Database
from netinventory.tasks import list_task_definitions, run_task_once

logger = logging.getLogger(__name__)


def run_monitor_worker() -> None:
    paths = get_app_paths()
    db = Database(paths)
    
    # Fire repeatedly every 5 minutes in the background
    while True:
        try:
            db.upsert_task_definitions(list_task_definitions())
            run = run_task_once(db, "current_network_probe", TaskTrigger.TIMER)
            logger.info(f"Background network monitor probe completed: {run.state.value}")
        except Exception as e:
            logger.warning(f"Background auto-monitor failed: {e}")
            
        time.sleep(10)


def start_monitor_worker() -> None:
    logger.info("Starting Auto-Monitor background worker...")
    t = threading.Thread(target=run_monitor_worker, daemon=True, name="AutoMonitorWorker")
    t.start()
