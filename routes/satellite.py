from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from satellite.gee import (
    init_ee,
    geojson_to_ee_geometry,
    ndvi_image_for_range,
    get_ndvi_tiles_url,
    reduce_ndvi_stats,
    weekly_timeseries,
)

router = APIRouter(prefix="/satellite", tags=["satellite"])


class NDVIRequest(BaseModel):
    geometry: dict = Field(..., description="GeoJSON geometry: Polygon/MultiPolygon")
    start_date: str = Field(..., description="YYYY-MM-DD")
    end_date: str = Field(..., description="YYYY-MM-DD")


def classify_health(mean_ndvi):
    if mean_ndvi is None:
        return {"label": "No Data", "level": "unknown",
                "advice": ["Try a wider date range.", "Cloudy days can hide crops."]}

    if mean_ndvi >= 0.60:
        return {"label": "Healthy", "level": "good",
                "advice": ["Maintain irrigation schedule.", "Scout weekly for pests.", "Upload leaf photo if you see spots."]}

    if mean_ndvi >= 0.40:
        return {"label": "Moderate", "level": "warn",
                "advice": ["Check irrigation/water stress.", "Inspect field edges for early disease/pests.", "Compare with last week for drops."]}

    return {"label": "Stressed", "level": "bad",
            "advice": ["Inspect field within 24–48 hours.", "Check water availability & drainage.", "Upload leaf photo for diagnosis."]}


@router.post("/ndvi/mvp")
def ndvi_mvp(req: NDVIRequest):
    try:
        init_ee()
        geom = geojson_to_ee_geometry(req.geometry)

        ndvi_img = ndvi_image_for_range(geom, req.start_date, req.end_date)
        tiles_url = get_ndvi_tiles_url(ndvi_img)
        summary = reduce_ndvi_stats(ndvi_img, geom)
        ts = weekly_timeseries(geom, req.start_date, req.end_date)

        health = classify_health(summary.get("mean"))

        return {
            "tiles_url": tiles_url,
            "summary": summary,
            "health": health,
            "timeseries": ts
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))