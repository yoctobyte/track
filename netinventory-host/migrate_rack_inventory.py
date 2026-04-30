#!/usr/bin/env python3
import json
import sys
from pathlib import Path

# Add track_location to path
APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR.parent))

from track_location import LocationDB

def get_data_root() -> Path:
    # Mimics netinventory-host's data_root
    import os
    instance = os.environ.get("NETINVENTORY_HOST_INSTANCE", "testing").strip() or "testing"
    configured = os.environ.get("NETINVENTORY_HOST_DATA_DIR", "").strip()
    if configured:
        root = Path(configured).expanduser().resolve()
    else:
        root = (APP_DIR / "data" / "environments" / instance).resolve()
    return root

def main():
    root = get_data_root()
    rack_inventory_dir = root / "rack-inventory"
    db_path = root / "locations.sqlite"
    
    print(f"Migrating racks from {rack_inventory_dir}")
    print(f"To central LocationDB at {db_path}")
    
    db = LocationDB(db_path)
    
    if not rack_inventory_dir.exists():
        print("No rack_inventory directory found. Exiting.")
        return

    # Cache IDs to avoid creating duplicates
    b_cache = {}
    l_cache = {}

    for rack_file in rack_inventory_dir.glob("*.json"):
        with rack_file.open() as f:
            rack = json.load(f)
            
        b_name = rack.get("building", "").strip() or "Unknown Building"
        l_name = rack.get("location", "").strip() or "Unknown Location"
        
        if b_name not in b_cache:
            # Check if exists in db
            existing_b = next((b for b in db.list_buildings() if b['name'] == b_name), None)
            if not existing_b:
                existing_b = db.create_building(name=b_name)
            b_cache[b_name] = existing_b['id']
            
        b_id = b_cache[b_name]
        
        l_key = f"{b_id}::{l_name}"
        if l_key not in l_cache:
            existing_l = next((l for l in db.list_locations(b_id) if l['name'] == l_name), None)
            if not existing_l:
                existing_l = db.create_location(building_id=b_id, name=l_name, type="room")
            l_cache[l_key] = existing_l['id']
            
        l_id = l_cache[l_key]
        
        c_name = rack.get("name", "").strip() or "Unnamed Rack"
        c_desc = rack.get("description", "")
        # Create cabinet
        c = db.create_cabinet(
            location_id=l_id,
            name=c_name,
            notes=c_desc,
            id=rack.get("id") # try to preserve ID if possible
        )
        
        # Add devices
        for device in rack.get("devices", []):
            db.create_device(
                cabinet_id=c['id'],
                location_id=l_id,
                name=device.get("name", ""),
                kind=device.get("kind", ""),
                brand=device.get("brand", ""),
                model=device.get("model", ""),
                port_count=device.get("port_count") or 0,
                unit_size=device.get("unit_size") or 1,
                u_position=device.get("u_position"),
                notes=device.get("notes", ""),
                id=device.get("id")
            )
            
        print(f"Migrated rack: {c_name}")
        
    print("Migration complete!")

if __name__ == '__main__':
    main()
