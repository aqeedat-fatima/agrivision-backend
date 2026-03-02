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

# ... classify_health unchanged ...

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
        # if compute_farm_metrics ever raises HTTPException, preserve it
        raise

    except ValueError as e:
        # "user input / data unavailable" style errors
        logger.warning(f"[satellite] ValueError: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        # real server bug — log full traceback
        logger.exception(f"[satellite] Unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Satellite processing failed (see server logs).")