"""
FastAPI demo — same patterns as the Flask demo:
  - SQLite via SQLAlchemy
  - file upload + storage
  - template rendering (gallery)
  - JSON API endpoint
  - background processing (asyncio)
"""

import asyncio
import hashlib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session

# --- Database setup ---

UPLOAD_DIR = Path(__file__).parent / "uploads"
DATABASE_URL = "sqlite:///demo.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


# --- Models ---

class Location(Base):
    __tablename__ = "location"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    parent_id = Column(Integer, ForeignKey("location.id"))
    children = relationship("Location", backref="parent", remote_side=[id])
    photos = relationship("Photo", backref="location")


class Photo(Base):
    __tablename__ = "photo"
    id = Column(Integer, primary_key=True)
    filename = Column(String(255), nullable=False)
    storage_path = Column(String(500), nullable=False)
    sha256 = Column(String(64))
    location_id = Column(Integer, ForeignKey("location.id"))
    status = Column(String(20), default="pending")


# --- Pydantic schemas (request/response validation) ---

class LocationCreate(BaseModel):
    name: str
    parent_id: int | None = None

class LocationOut(BaseModel):
    id: int
    name: str
    parent_id: int | None

class PhotoOut(BaseModel):
    id: int
    filename: str
    sha256: str | None
    location: str | None
    status: str


# --- App setup ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    UPLOAD_DIR.mkdir(exist_ok=True)
    Base.metadata.create_all(bind=engine)
    # Seed locations if empty
    db = SessionLocal()
    if not db.query(Location).first():
        museum = Location(name="Museum")
        db.add(museum)
        db.flush()
        for room in ["Ground Floor", "First Floor", "Basement"]:
            db.add(Location(name=room, parent_id=museum.id))
        db.commit()
    db.close()
    yield

app = FastAPI(title="map3d demo", lifespan=lifespan)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


# --- Dependency: database session ---

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- Background task ---

async def process_photo(photo_id: int):
    """Simulate slow processing (metadata extraction, thumbnail, etc.)."""
    await asyncio.sleep(2)
    db = SessionLocal()
    photo = db.get(Photo, photo_id)
    if photo:
        photo.status = "done"
        db.commit()
    db.close()


# --- Routes: HTML pages ---

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, db: Session = Depends(get_db)):
    locations = db.query(Location).filter(Location.parent_id.is_(None)).all()
    return templates.TemplateResponse("index.html", {
        "request": request, "locations": locations,
    })


@app.get("/upload", response_class=HTMLResponse)
async def upload_form(request: Request, db: Session = Depends(get_db)):
    locations = db.query(Location).all()
    return templates.TemplateResponse("upload.html", {
        "request": request, "locations": locations,
    })


@app.post("/upload")
async def upload_file(
    photo: UploadFile,
    location_id: int = Form(...),
    db: Session = Depends(get_db),
):
    # Store original
    data = await photo.read()
    sha = hashlib.sha256(data).hexdigest()
    dest = UPLOAD_DIR / f"{sha}_{photo.filename}"
    dest.write_bytes(data)

    # Create record
    record = Photo(
        filename=photo.filename,
        storage_path=str(dest),
        sha256=sha,
        location_id=location_id,
        status="processing",
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    # Kick off background work
    asyncio.create_task(process_photo(record.id))

    return RedirectResponse(url="/gallery", status_code=303)


@app.get("/gallery", response_class=HTMLResponse)
async def gallery(request: Request, db: Session = Depends(get_db)):
    photos = db.query(Photo).order_by(Photo.id.desc()).all()
    return templates.TemplateResponse("gallery.html", {
        "request": request, "photos": photos,
    })


# --- Routes: JSON API ---

@app.get("/api/locations", response_model=list[LocationOut])
async def api_list_locations(db: Session = Depends(get_db)):
    return db.query(Location).all()


@app.post("/api/locations", response_model=LocationOut, status_code=201)
async def api_create_location(loc: LocationCreate, db: Session = Depends(get_db)):
    record = Location(name=loc.name, parent_id=loc.parent_id)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@app.get("/api/photos/{photo_id}", response_model=PhotoOut)
async def api_photo_detail(photo_id: int, db: Session = Depends(get_db)):
    photo = db.get(Photo, photo_id)
    if not photo:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="not found")
    return PhotoOut(
        id=photo.id,
        filename=photo.filename,
        sha256=photo.sha256,
        location=photo.location.name if photo.location else None,
        status=photo.status,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5001)
