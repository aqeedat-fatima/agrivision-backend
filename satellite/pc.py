# satellite/pc.py
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Any, List

from pystac_client import Client
import planetary_computer as pc

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _reproject_geom_to_crs(geom_geojson: dict, dst_crs) -> dict:
    from shapely.geometry import shape, mapping
    from shapely.ops import transform
    from pyproj import Transformer

    geom = shape(geom_geojson)
    transformer = Transformer.from_crs("EPSG:4326", dst_crs, always_xy=True)

    def _tx(x, y, z=None):
        return transformer.transform(x, y)

    return mapping(transform(_tx, geom))


def _mask_band_mean(asset_href: str, geom_geojson_wgs84: dict) -> float:
    import numpy as np
    import rasterio
    from rasterio.mask import mask

    with rasterio.open(asset_href) as src:
        geom_in_src = _reproject_geom_to_crs(geom_geojson_wgs84, src.crs)

        data, _ = mask(src, [geom_in_src], crop=True)
        arr = data[0].astype("float32")

        nodata = src.nodata
        if nodata is not None:
            arr = np.where(arr == nodata, np.nan, arr)

        arr = np.where(arr == 0, np.nan, arr)

        mean_val = np.nanmean(arr)

        if np.isnan(mean_val):
            raise ValueError("No valid pixels found inside polygon for this band.")

        return float(mean_val)


def _compute_indices_for_item(item, geometry_geojson: dict) -> Dict[str, Any]:
    import numpy as np

    blue_url = item.assets["B02"].href
    red_url = item.assets["B04"].href
    nir_url = item.assets["B08"].href
    swir_url = item.assets["B11"].href

    blue = _mask_band_mean(blue_url, geometry_geojson)
    red = _mask_band_mean(red_url, geometry_geojson)
    nir = _mask_band_mean(nir_url, geometry_geojson)
    swir = _mask_band_mean(swir_url, geometry_geojson)

    ndvi = (nir - red) / (nir + red + 1e-6)
    ndmi = (nir - swir) / (nir + swir + 1e-6)
    evi = 2.5 * (nir - red) / (nir + 6.0 * red - 7.5 * blue + 1.0 + 1e-6)

    def clip(v, lo=-1.0, hi=1.0):
        return float(np.clip(v, lo, hi))

    return {
        "ndvi": clip(ndvi),
        "ndmi": clip(ndmi),
        "evi": clip(evi, lo=-2.0, hi=2.0),
        "cloud_cover": float(item.properties.get("eo:cloud_cover", 100.0)),
        "scene_date": item.datetime.isoformat(),
    }


def _search_items(geometry_geojson: dict, start_date: str, end_date: str, limit: int = 3):
    from shapely.geometry import shape

    catalog = Client.open(STAC_URL)

    geom = shape(geometry_geojson)
    minx, miny, maxx, maxy = geom.bounds

    search = catalog.search(
        collections=["sentinel-2-l2a"],
        bbox=[minx, miny, maxx, maxy],
        datetime=f"{start_date}/{end_date}",
        query={
            "eo:cloud_cover": {"lt": 60}
        },
        limit=limit,
        max_items=limit,
    )

    items = list(search.items())
    return items[:limit]


def _compute_change_pct(timeseries: List[dict]) -> Dict[str, Any]:
    if not timeseries:
        return {"ndvi_change_pct": None, "period_days": 30}

    pts = []
    for p in timeseries:
        dt = _parse_dt(p["date"])
        pts.append((dt, p.get("ndvi")))

    pts.sort(key=lambda x: x[0])
    end_dt = pts[-1][0]

    last_start = end_dt - timedelta(days=30)
    prev_start = end_dt - timedelta(days=60)

    last_vals = [v for (d, v) in pts if d >= last_start and v is not None]
    prev_vals = [v for (d, v) in pts if prev_start <= d < last_start and v is not None]

    if len(last_vals) < 1 or len(prev_vals) < 1:
        return {"ndvi_change_pct": None, "period_days": 30}

    last_mean = sum(last_vals) / len(last_vals)
    prev_mean = sum(prev_vals) / len(prev_vals)

    if abs(prev_mean) < 1e-6:
        return {"ndvi_change_pct": None, "period_days": 30}

    pct = ((last_mean - prev_mean) / abs(prev_mean)) * 100.0

    return {
        "ndvi_change_pct": float(pct),
        "period_days": 30,
        "last_mean": float(last_mean),
        "prev_mean": float(prev_mean),
    }


def compute_farm_metrics(geometry_geojson: dict, start_date: str, end_date: str) -> Dict[str, Any]:
    items = _search_items(geometry_geojson, start_date, end_date, limit=3)

    if not items:
        raise Exception("No Sentinel-2 scenes found for this polygon/date range.")

    items.sort(key=lambda x: x.properties.get("eo:cloud_cover", 100.0))

    best = items[:3]
    best_signed = [pc.sign(it) for it in best]

    series = []

    for it in best_signed:
        try:
            print("Processing scene:", it.id, it.datetime)

            stats = _compute_indices_for_item(it, geometry_geojson)

            series.append({
                "date": stats["scene_date"],
                "ndvi": stats["ndvi"],
                "ndmi": stats["ndmi"],
                "evi": stats["evi"],
                "cloud_cover": stats["cloud_cover"],
            })

            print("Scene processed successfully:", stats)

        except Exception as e:
            print("Scene processing failed:", str(e))
            import traceback
            traceback.print_exc()
            continue

    if not series:
        raise Exception("Scenes found, but none could be processed for this polygon.")

    series.sort(key=lambda p: p["date"])
    series_for_chart = series[-3:]

    summary = series_for_chart[-1].copy()
    change = _compute_change_pct(series)

    return {
        "summary": summary,
        "timeseries": series_for_chart,
        "change": change,
    }