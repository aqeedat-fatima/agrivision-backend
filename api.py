from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import uvicorn
from uuid import uuid4

from model_def import CottonDiseaseModel

from database import engine, SessionLocal
from models import Base, DiseaseReport, User

from routes.satellite_pc import router as satellite_router
from routes.auth import router as auth_router
from routes.history import router as history_router

app = FastAPI()

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

# ---- LOAD MODEL ONCE ----
BASE_DIR = Path(__file__).resolve().parent
WEIGHTS_PATH = BASE_DIR / "efficientnet_b3_cotton_best.pth"
model = CottonDiseaseModel(str(WEIGHTS_PATH))

UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


@app.post("/predict")
async def predict(
    file: UploadFile = File(...),
    user_id: int = Form(...),  # ✅ must be sent from frontend
):
    contents = await file.read()
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
    # Normalize model keys (avoid "Unknown" bugs)
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
    confidence = "" if conf_val is None else str(conf_val)  # matches your DB schema (VARCHAR)

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

    # return same result + image path so frontend can show it
    result["image_path"] = str(fpath).replace("\\", "/")
    result["disease_key"] = str(disease_key)
    result["disease_name"] = str(label)
    return result


@app.get("/ping")
def ping():
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8001, reload=True)