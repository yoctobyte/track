import unittest
import tempfile
from pathlib import Path
from track_location import LocationDB

class TestLocationDB(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.sqlite"
        self.db = LocationDB(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_create_and_read_building(self):
        b = self.db.create_building("Test Building", "A test", 12.3, 45.6)
        self.assertIsNotNone(b['id'])
        self.assertEqual(b['name'], "Test Building")
        self.assertEqual(b['description'], "A test")
        
        b2 = self.db.get_building(b['id'])
        self.assertEqual(b['id'], b2['id'])

    def test_hierarchy(self):
        b = self.db.create_building("Building 1")
        l1 = self.db.create_location(b['id'], "Floor 1", "floor")
        l2 = self.db.create_location(b['id'], "Room 101", "room", parent_id=l1['id'])
        
        c1 = self.db.create_cabinet(l2['id'], "Cab A", 42)
        d1 = self.db.create_device("Switch 1", cabinet_id=c1['id'], kind="switch")
        
        self.assertEqual(self.db.list_locations(b['id'])[0]['id'], l1['id'])
        self.assertEqual(self.db.get_cabinet(c1['id'])['u_size'], 42)
        self.assertEqual(self.db.get_device(d1['id'])['name'], "Switch 1")

    def test_media_record(self):
        b = self.db.create_building("Building 1")
        m = self.db.create_media_record("building", b['id'], "quicktrack", "/photos/123.jpg")
        
        records = self.db.list_media_records("building", b['id'])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['uri'], "/photos/123.jpg")

if __name__ == '__main__':
    unittest.main()
