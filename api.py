from fastapi import FastAPI, UploadFile, File, Form, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import uvicorn
from uuid import uuid4
from pydantic import BaseModel
from datetime import date
import json
import io
from PIL import Image

from model_def import CottonDiseaseModel
from cotton_validator import cotton_validator

from database import engine, SessionLocal
from models import Base, DiseaseReport, User, Farm, SatelliteReport

from routes.satellite_pc import router as satellite_router
from routes.auth import router as auth_router
from routes.history import router as history_router


app = FastAPI(
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(satellite_router)
app.include_router(auth_router)
app.include_router(history_router)


# ---- LOAD DISEASE MODEL ONCE ----
BASE_DIR = Path(__file__).resolve().parent
WEIGHTS_PATH = BASE_DIR / "efficientnet_b3_cotton_best.pth"
model = CottonDiseaseModel(str(WEIGHTS_PATH))

UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


@app.post("/predict")
async def predict(
    file: UploadFile = File(...),
    user_id: int = Form(...),
):
    contents = await file.read()

    # ----------------------------
    # Cotton validation first
    # ----------------------------
    try:
        image = Image.open(io.BytesIO(contents)).convert("RGB")
    except Exception:
        return {
            "valid": False,
            "message": "Invalid image file. Please upload a clear cotton leaf image."
        }

    validation = cotton_validator.predict(image)

    if not validation["is_valid"]:
        return {
            "valid": False,
            "message": "Invalid image. Please upload a cotton leaf image.",
            "validator": validation
        }

    # ----------------------------
    # Run disease model only if cotton is valid
    # ----------------------------
    result = model.predict(contents)

    # ----------------------------
    # Save image to disk
    # ----------------------------
    ext = Path(file.filename).suffix.lower() or ".jpg"
    fname = f"{uuid4().hex}{ext}"
    fpath = UPLOAD_DIR / fname

    with open(fpath, "wb") as f:
        f.write(contents)

    # ----------------------------
    # Normalize model keys
    # ----------------------------
    label = (
        result.get("pred_label")
        or result.get("label")
        or result.get("disease")
        or result.get("disease_name")
        or "Unknown"
    )

    disease_key = (
        result.get("label_key")
        or result.get("disease_key")
        or (str(label).strip().lower().replace(" ", "_") if label else "unknown")
    )

    conf_val = result.get("confidence")
    confidence = "" if conf_val is None else str(conf_val)

    # ----------------------------
    # Store report in DB for this user
    # ----------------------------
    db = SessionLocal()

    try:
        user = db.query(User).filter(User.id == user_id).first()

        if user:
            row = DiseaseReport(
                user_id=user_id,
                disease_name=str(label),
                disease_key=str(disease_key),
                confidence=confidence,
                image_path=str(fpath).replace("\\", "/"),
                symptoms=result.get("symptoms"),
                cause=result.get("cause"),
                prevention=result.get("prevention"),
            )

            db.add(row)
            db.commit()

    finally:
        db.close()

    result["valid"] = True
    result["validator"] = validation
    result["image_path"] = str(fpath).replace("\\", "/")
    result["disease_key"] = str(disease_key)
    result["disease_name"] = str(label)

    return result


class CropStageRequest(BaseModel):
    farm_id: int | None = None
    farm_name: str | None = None
    sowing_date: str


def get_cotton_stage(days: int):
    if days <= 15:
        return {
            "name": "Seedling",
            "icon": "🌱",
            "advice": [
                "Ensure light and frequent irrigation.",
                "Protect young seedlings from pests and early stress."
            ]
        }

    if days <= 35:
        return {
            "name": "Vegetative",
            "icon": "🌿",
            "advice": [
                "Support strong leaf and stem growth with balanced nutrition.",
                "Monitor weeds because competition is high in this stage."
            ]
        }

    if days <= 55:
        return {
            "name": "Budding",
            "icon": "🌾",
            "advice": [
                "Monitor square formation carefully.",
                "Check for sucking pests and early bollworm activity."
            ]
        }

    if days <= 80:
        return {
            "name": "Flowering",
            "icon": "🌸",
            "advice": [
                "Maintain proper irrigation during flowering.",
                "Monitor pest attacks because flowering is a sensitive stage."
            ]
        }

    if days <= 120:
        return {
            "name": "Boll Formation",
            "icon": "🟢",
            "advice": [
                "Avoid water stress during boll development.",
                "Monitor bollworm and nutrient deficiency symptoms."
            ]
        }

    return {
        "name": "Harvesting",
        "icon": "🌾",
        "advice": [
            "Prepare for picking when bolls are mature and open.",
            "Avoid unnecessary irrigation close to harvesting."
        ]
    }


def safe_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def evaluate_stage_support(stage_name: str, ndvi, evi, ndmi, has_real_satellite: bool):
    if not has_real_satellite:
        return {
            "confidence": "Medium",
            "satellite_support": "Limited",
            "note": "No saved satellite run was found for this farm. Stage is estimated mainly from sowing date."
        }

    ndvi = safe_float(ndvi)
    evi = safe_float(evi)
    ndmi = safe_float(ndmi)

    if ndvi is None:
        confidence = "Medium"
        satellite_support = "Limited"
        note = "Satellite report exists, but NDVI was unavailable. Stage is estimated mainly from sowing date."

    elif ndvi < 0.25:
        confidence = "Low"
        satellite_support = "Weak"
        note = "Vegetation signal appears weak for this stage. Field inspection is recommended."

    elif ndvi < 0.5:
        confidence = "Medium"
        satellite_support = "Moderate"
        note = "Satellite indicators partially support the estimated crop stage."

    else:
        confidence = "High"
        satellite_support = "Strong"
        note = "Satellite vegetation indicators strongly support the estimated crop stage."

    return {
        "confidence": confidence,
        "satellite_support": satellite_support,
        "note": note
    }


@app.post("/crop-stage/detect")
def detect_crop_stage(
    req: CropStageRequest,
    x_user_id: str = Header(None, alias="X-User-Id")
):
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-Id header")

    try:
        user_id = int(x_user_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user id")

    try:
        sowing = date.fromisoformat(req.sowing_date)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid sowing_date. Use YYYY-MM-DD.")

    today = date.today()
    days = (today - sowing).days

    if days < 0:
        raise HTTPException(status_code=400, detail="Sowing date cannot be in the future.")

    db = SessionLocal()

    try:
        farm = None

        if req.farm_id:
            farm = (
                db.query(Farm)
                .filter(Farm.id == req.farm_id, Farm.user_id == user_id)
                .first()
            )

            if not farm:
                raise HTTPException(status_code=404, detail="Farm not found for this user")

        latest_sat = None

        if req.farm_id:
            latest_sat = (
                db.query(SatelliteReport)
                .filter(
                    SatelliteReport.user_id == user_id,
                    SatelliteReport.farm_id == req.farm_id
                )
                .order_by(SatelliteReport.created_at.desc())
                .first()
            )

        if not latest_sat and farm:
            latest_sat = (
                db.query(SatelliteReport)
                .filter(
                    SatelliteReport.user_id == user_id,
                    SatelliteReport.farm_name == farm.name
                )
                .order_by(SatelliteReport.created_at.desc())
                .first()
            )

        summary = {}

        if latest_sat:
            try:
                summary = json.loads(latest_sat.summary_json or "{}")
            except Exception:
                summary = {}

        ndvi = summary.get("ndvi", summary.get("mean"))
        evi = summary.get("evi")
        ndmi = summary.get("ndmi")

        has_real_satellite = latest_sat is not None

        stage = get_cotton_stage(days)

        evaluation = evaluate_stage_support(
            stage_name=stage["name"],
            ndvi=ndvi,
            evi=evi,
            ndmi=ndmi,
            has_real_satellite=has_real_satellite
        )

        return {
            "farm": {
                "id": farm.id if farm else req.farm_id,
                "name": farm.name if farm else req.farm_name
            },
            "sowing_date": req.sowing_date,
            "crop_age_days": days,
            "stage": stage["name"],
            "icon": stage["icon"],
            "confidence": evaluation["confidence"],
            "satellite_support": evaluation["satellite_support"],
            "satellite_note": evaluation["note"],
            "satellite": {
                "available": has_real_satellite,
                "report_id": latest_sat.id if latest_sat else None,
                "created_at": latest_sat.created_at.isoformat() if latest_sat else None,
                "ndvi": safe_float(ndvi),
                "evi": safe_float(evi),
                "ndmi": safe_float(ndmi),
                "source": "saved_satellite_run" if latest_sat else "none"
            },
            "recommendations": [
                f"Estimated cotton stage is {stage['name']} based on {days} days after sowing.",
                *stage["advice"]
            ]
        }

    finally:
        db.close()


@app.get("/ping")
def ping():
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8001, reload=True)