from datetime import datetime, timezone
from . import db


def utcnow():
    return datetime.now(timezone.utc)


class Building(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="")
    latitude = db.Column(db.Float)   # reference point for geo-matching
    longitude = db.Column(db.Float)
    geo_radius = db.Column(db.Float, default=100.0)  # meters — how close counts as "at this building"
    created_at = db.Column(db.DateTime, default=utcnow)

    locations = db.relationship("Location", backref="building", lazy="dynamic")
    sessions = db.relationship("Session", backref="building", lazy="dynamic")


class Location(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    building_id = db.Column(db.Integer, db.ForeignKey("building.id"), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey("location.id"))
    name = db.Column(db.String(200), nullable=False)
    type = db.Column(db.String(50), default="room")  # building, floor, corridor, room, cabinet, wall, corner
    environment = db.Column(db.String(10), default="auto")  # auto, indoor, outdoor
    sort_order = db.Column(db.Integer, default=0)
    notes = db.Column(db.Text, default="")

    # Auto-inference rules for environment
    INDOOR_TYPES = {"room", "corridor", "cabinet", "wall", "corner", "basement", "attic", "closet"}
    OUTDOOR_TYPES = {"grounds", "parking", "facade", "garden", "roof", "yard", "terrace", "balcony"}

    @property
    def effective_environment(self):
        """Resolve 'auto' to indoor/outdoor based on type and parent chain."""
        if self.environment != "auto":
            return self.environment
        if self.type in self.INDOOR_TYPES:
            return "indoor"
        if self.type in self.OUTDOOR_TYPES:
            return "outdoor"
        # Inherit from parent
        if self.parent:
            return self.parent.effective_environment
        # Floor/building level — ambiguous, default indoor
        return "indoor"

    children = db.relationship(
        "Location", backref=db.backref("parent", remote_side=[id]),
        order_by="Location.sort_order",
    )
    observations = db.relationship("Observation", backref="location", lazy="dynamic")
    apriltags = db.relationship("AprilTag", backref="linked_location", lazy="dynamic")


class Session(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    building_id = db.Column(db.Integer, db.ForeignKey("building.id"), nullable=False)
    label = db.Column(db.String(200), default="")
    start_time = db.Column(db.DateTime, default=utcnow)
    end_time = db.Column(db.DateTime)
    source_type = db.Column(db.String(50), default="file_upload")  # manual_capture, file_upload, video_import
    device_name = db.Column(db.String(200), default="")
    notes = db.Column(db.Text, default="")

    assets = db.relationship("Asset", backref="session", lazy="dynamic")


class Asset(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("session.id"), nullable=False)
    type = db.Column(db.String(20), default="image")  # image, video
    original_filename = db.Column(db.String(500), nullable=False)
    storage_path = db.Column(db.String(1000), nullable=False)
    hash_sha256 = db.Column(db.String(64), nullable=False)
    file_size = db.Column(db.Integer)
    mime_type = db.Column(db.String(100), default="")
    created_at = db.Column(db.DateTime, default=utcnow)
    import_source = db.Column(db.String(50), default="upload")  # upload, clipboard, burst, extracted_from_video

    frames = db.relationship("Frame", backref="asset", lazy="dynamic")


class Frame(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey("asset.id"), nullable=False)
    frame_index = db.Column(db.Integer)  # null for still images
    timestamp_original = db.Column(db.DateTime)
    timestamp_imported = db.Column(db.DateTime, default=utcnow)
    preview_path = db.Column(db.String(1000), default="")
    width = db.Column(db.Integer)
    height = db.Column(db.Integer)
    blur_score = db.Column(db.Float)
    duplicate_score = db.Column(db.Float)
    metadata_json = db.Column(db.Text, default="{}")
    sensor_json = db.Column(db.Text, default="{}")  # accelerometer, gyro, magnetometer, GPS, barometer at capture time
    processing_status = db.Column(db.String(20), default="pending")  # pending, processing, done, failed

    observations = db.relationship("Observation", backref="frame", lazy="dynamic")
    tag_detections = db.relationship("AprilTagDetection", backref="frame", lazy="dynamic")


class Observation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    frame_id = db.Column(db.Integer, db.ForeignKey("frame.id"), nullable=False)
    assigned_location_id = db.Column(db.Integer, db.ForeignKey("location.id"))
    assignment_method = db.Column(db.String(20), default="manual")  # manual, apriltag, inferred, corrected
    confidence = db.Column(db.Float)
    notes = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=utcnow)


class AprilTag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tag_family = db.Column(db.String(50), default="tag36h11")
    tag_code = db.Column(db.Integer, nullable=False)
    linked_location_id = db.Column(db.Integer, db.ForeignKey("location.id"))
    label = db.Column(db.String(200), default="")
    notes = db.Column(db.Text, default="")


class AprilTagDetection(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    frame_id = db.Column(db.Integer, db.ForeignKey("frame.id"), nullable=False)
    apriltag_id = db.Column(db.Integer, db.ForeignKey("april_tag.id"))
    detected_family = db.Column(db.String(50))
    detected_code = db.Column(db.Integer)
    confidence = db.Column(db.Float)
    corner_points_json = db.Column(db.Text, default="")
    pose_json = db.Column(db.Text, default="")
