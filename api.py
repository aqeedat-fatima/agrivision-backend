# api.py
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from model_def import CottonDiseaseModel
import uvicorn
from pathlib import Path

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from routes.satellite import router as satellite_router
app.include_router(satellite_router)

# ---- LOAD MODEL ONCE ----
BASE_DIR = Path(__file__).resolve().parent
WEIGHTS_PATH = BASE_DIR / "efficientnet_b3_cotton_best.pth"   # 👈 your actual file

model = CottonDiseaseModel(str(WEIGHTS_PATH))


@app.post("/predict")
async def predict(file: UploadFile = File(...)):
    """Receives an image file and returns predicted disease + confidence."""
    contents = await file.read()
    result = model.predict(contents)
    return result


if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
