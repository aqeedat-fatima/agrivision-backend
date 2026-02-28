from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from satellite.pc import compute_ndvi_stats

router = APIRouter(prefix="/satellite", tags=["satellite"])

class MonitorRequest(BaseModel):
    geometry: dict
    start_date: str
    end_date: str

@router.post("/ndvi/mvp")
def ndvi_mvp(req: MonitorRequest):
    try:
        stats = compute_ndvi_stats(
            req.geometry,
            req.start_date,
            req.end_date
        )

        return {
            "summary": stats,
            "health": classify(stats["mean"]),
            "timeseries": []
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


def classify(mean_ndvi):
    if mean_ndvi >= 0.6:
        return {"label": "Healthy", "level": "good"}
    if mean_ndvi >= 0.4:
        return {"label": "Moderate", "level": "warn"}
    return {"label": "Stressed", "level": "bad"}