import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import SessionLocal
from models import Farm, DiseaseReport, SatelliteReport, User

router = APIRouter(prefix="/db", tags=["database"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_user_or_400(db: Session, user_id: int):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid user")
    return user

def require_user_id(x_user_id: str | None):
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-Id header")
    try:
        return int(x_user_id)
    except:
        raise HTTPException(status_code=401, detail="Invalid X-User-Id header")

# ---------- FARMS ----------
class FarmUpsert(BaseModel):
    name: str
    geometry: dict

@router.get("/farms")
def list_farms(db: Session = Depends(get_db), x_user_id: str | None = Header(default=None)):
    user_id = require_user_id(x_user_id)
    get_user_or_400(db, user_id)

    farms = db.query(Farm).filter(Farm.user_id == user_id).order_by(Farm.updated_at.desc()).all()
    return [{
        "id": f.id,
        "name": f.name,
        "geometry": json.loads(f.geometry_json),
        "createdAt": f.created_at.isoformat(),
        "updatedAt": f.updated_at.isoformat(),
    } for f in farms]

@router.post("/farms/upsert")
def upsert_farm(req: FarmUpsert, db: Session = Depends(get_db), x_user_id: str | None = Header(default=None)):
    user_id = require_user_id(x_user_id)
    get_user_or_400(db, user_id)

    name = req.name.strip()
    geom_str = json.dumps(req.geometry)

    farm = db.query(Farm).filter(Farm.user_id == user_id, Farm.name.ilike(name)).first()
    now = datetime.utcnow()

    if farm:
        farm.geometry_json = geom_str
        farm.updated_at = now
    else:
        farm = Farm(user_id=user_id, name=name, geometry_json=geom_str, created_at=now, updated_at=now)
        db.add(farm)

    db.commit()
    db.refresh(farm)
    return {"id": farm.id, "name": farm.name}

# ---------- DISEASE REPORTS ----------
class DiseaseReportCreate(BaseModel):
    disease_name: str
    disease_key: str | None = None
    confidence: str | None = None
    image_path: str | None = None
    symptoms: str | None = None
    cause: str | None = None
    prevention: str | None = None

@router.get("/history/disease")
def list_disease_reports(db: Session = Depends(get_db), x_user_id: str | None = Header(default=None)):
    user_id = require_user_id(x_user_id)
    get_user_or_400(db, user_id)

    rows = db.query(DiseaseReport).filter(DiseaseReport.user_id == user_id).order_by(DiseaseReport.created_at.desc()).all()
    return [{
        "id": r.id,
        "diseaseName": r.disease_name,
        "diseaseKey": r.disease_key,
        "confidence": r.confidence,
        "imagePath": r.image_path,
        "symptoms": r.symptoms,
        "cause": r.cause,
        "prevention": r.prevention,
        "createdAt": r.created_at.isoformat(),
    } for r in rows]

@router.post("/history/disease")
def create_disease_report(req: DiseaseReportCreate, db: Session = Depends(get_db), x_user_id: str | None = Header(default=None)):
    user_id = require_user_id(x_user_id)
    get_user_or_400(db, user_id)

    row = DiseaseReport(
        user_id=user_id,
        disease_name=req.disease_name,
        disease_key=req.disease_key,
        confidence=req.confidence,
        image_path=req.image_path,
        symptoms=req.symptoms,
        cause=req.cause,
        prevention=req.prevention,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"ok": True, "id": row.id}

# ---------- SATELLITE REPORTS ----------
class SatelliteReportCreate(BaseModel):
    farmName: str
    farmId: int | None = None
    geometry: dict
    summary: dict
    timeseries: list
    change: dict | None = None
    createdAt: str | None = None

@router.get("/history/satellite")
def list_satellite_reports(db: Session = Depends(get_db), x_user_id: str | None = Header(default=None)):
    user_id = require_user_id(x_user_id)
    get_user_or_400(db, user_id)

    rows = db.query(SatelliteReport).filter(SatelliteReport.user_id == user_id).order_by(SatelliteReport.created_at.desc()).all()
    return [{
        "id": r.id,
        "farmName": r.farm_name,
        "farmId": r.farm_id,
        "geometry": json.loads(r.geometry_json),
        "summary": json.loads(r.summary_json),
        "timeseries": json.loads(r.timeseries_json),
        "change": json.loads(r.change_json) if r.change_json else None,
        "createdAt": r.created_at.isoformat(),
    } for r in rows]

@router.post("/history/satellite")
def create_satellite_report(req: SatelliteReportCreate, db: Session = Depends(get_db), x_user_id: str | None = Header(default=None)):
    user_id = require_user_id(x_user_id)
    get_user_or_400(db, user_id)

    row = SatelliteReport(
        user_id=user_id,
        farm_name=req.farmName,
        farm_id=req.farmId,
        geometry_json=json.dumps(req.geometry),
        summary_json=json.dumps(req.summary),
        timeseries_json=json.dumps(req.timeseries),
        change_json=json.dumps(req.change) if req.change is not None else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"ok": True, "id": row.id}