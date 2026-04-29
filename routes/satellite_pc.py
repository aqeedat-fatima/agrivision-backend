# routes/satellite_pc.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from satellite.pc import compute_farm_metrics
import logging

router = APIRouter(prefix="/satellite", tags=["satellite"])
logger = logging.getLogger("uvicorn.error")


class MonitorRequest(BaseModel):
    geometry: dict
    start_date: str
    end_date: str


def classify_health(ndvi, ndmi=None):
    if ndvi is None:
        return {
            "status": "Unknown",
            "message": "Not enough satellite data available."
        }

    if ndvi >= 0.6:
        status = "Healthy"
        message = "Vegetation health looks strong."
    elif ndvi >= 0.35:
        status = "Moderate"
        message = "Crop health is moderate. Keep monitoring the field."
    elif ndvi >= 0.2:
        status = "Stressed"
        message = "Vegetation appears stressed. Check irrigation, pests, or disease symptoms."
    else:
        status = "Critical"
        message = "Vegetation health is very low. Immediate field inspection is recommended."

    if ndmi is not None and ndmi < 0:
        message += " Moisture stress may also be present."

    return {
        "status": status,
        "message": message
    }


@router.post("/ndvi/mvp")
def ndvi_mvp(req: MonitorRequest):
    try:
        result = compute_farm_metrics(req.geometry, req.start_date, req.end_date)

        summary = result["summary"]
        health = classify_health(summary.get("ndvi"), summary.get("ndmi"))

        return {
            "summary": summary,
            "health": health,
            "timeseries": result["timeseries"],
            "change": result["change"],
            "tiles_url": None
        }

    except HTTPException:
        raise

    except ValueError as e:
        logger.warning(f"[satellite] ValueError: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        logger.exception(f"[satellite] Unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Satellite processing failed (see server logs).")