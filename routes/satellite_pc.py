# routes/satellite_pc.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from satellite.pc import compute_farm_metrics

router = APIRouter(prefix="/satellite", tags=["satellite"])

class MonitorRequest(BaseModel):
    geometry: dict
    start_date: str
    end_date: str

def classify_health(ndvi: float | None, ndmi: float | None):
    # Fallback
    if ndvi is None:
        return {"label": "Unknown", "level": "unknown", "advice": ["No data returned. Try a different date range or polygon."]}

    # NDVI vegetation health (rough general-purpose thresholds)
    if ndvi >= 0.60:
        ndvi_level = "good"
    elif ndvi >= 0.40:
        ndvi_level = "warn"
    else:
        ndvi_level = "bad"

    # NDMI moisture stress (rough)
    # lower NDMI => drier vegetation/soil
    moisture_flag = None
    if ndmi is not None:
        if ndmi < 0.10:
            moisture_flag = "dry"
        elif ndmi < 0.25:
            moisture_flag = "low"
        else:
            moisture_flag = "ok"

    # Combine
    if ndvi_level == "good" and moisture_flag in (None, "ok"):
        return {"label": "Healthy", "level": "good", "advice": ["Vegetation looks strong.", "Keep monitoring weekly for drops."]}

    if ndvi_level == "good" and moisture_flag in ("low", "dry"):
        return {"label": "Moisture Stress", "level": "warn", "advice": ["Vegetation is strong but moisture is low.", "Consider irrigation checks / water scheduling."]}

    if ndvi_level == "warn":
        return {"label": "Moderate", "level": "warn", "advice": ["Vegetation is moderate.", "Watch for downward trend and check field conditions."]}

    return {"label": "Stressed", "level": "bad", "advice": ["Vegetation signal is low.", "Check for bare soil, urban area, harvest period, or crop stress."]}


@router.post("/ndvi/mvp")
def ndvi_mvp(req: MonitorRequest):
    try:
        result = compute_farm_metrics(req.geometry, req.start_date, req.end_date)

        summary = result["summary"]
        health = classify_health(summary.get("ndvi"), summary.get("ndmi"))

        return {
            "summary": summary,              # ndvi, ndmi, evi, cloud_cover, date
            "health": health,                # label, level, advice[]
            "timeseries": result["timeseries"],
            "change": result["change"],      # ndvi_change_pct etc
            "tiles_url": None                # keep key for frontend safety
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))