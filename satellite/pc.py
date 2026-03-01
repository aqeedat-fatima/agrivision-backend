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
    """
    Reproject a GeoJSON geometry (assumed EPSG:4326 lon/lat) into dst_crs.
    Returns GeoJSON geometry dict in dst_crs coordinates.
    """
    from shapely.geometry import shape, mapping
    from shapely.ops import transform
    from pyproj import Transformer

    geom = shape(geom_geojson)
    transformer = Transformer.from_crs("EPSG:4326", dst_crs, always_xy=True)

    def _tx(x, y, z=None):
        return transformer.transform(x, y)

    geom2 = transform(_tx, geom)
    return mapping(geom2)


def _mask_band_mean(asset_href: str, geom_geojson_wgs84: dict) -> float:
    """
    Open a band asset, reproject geometry to band CRS, mask, return mean of valid pixels.
    """
    import numpy as np
    import rasterio
    from rasterio.mask import mask

    with rasterio.open(asset_href) as src:
        geom_in_src = _reproject_geom_to_crs(geom_geojson_wgs84, src.crs)

        data, _ = mask(src, [geom_in_src], crop=True)
        arr = data[0].astype("float32")

        # Handle nodata
        nodata = src.nodata
        if nodata is not None:
            arr = np.where(arr == nodata, np.nan, arr)

        arr = np.where(arr == 0, np.nan, arr)  # S2 sometimes has zeros outside
        return float(np.nanmean(arr))


def _compute_indices_for_item(item, geometry_geojson: dict) -> Dict[str, Any]:
    """
    Compute NDVI, NDMI, EVI for a single Sentinel-2 item (signed already).
    Uses surface reflectance bands:
      B02 (Blue), B04 (Red), B08 (NIR), B11 (SWIR1)
    """
    import numpy as np

    # Band URLs (signed)
    blue_url = item.assets["B02"].href
    red_url  = item.assets["B04"].href
    nir_url  = item.assets["B08"].href
    swir_url = item.assets["B11"].href

    # Means inside polygon
    blue = _mask_band_mean(blue_url, geometry_geojson)
    red  = _mask_band_mean(red_url, geometry_geojson)
    nir  = _mask_band_mean(nir_url, geometry_geojson)
    swir = _mask_band_mean(swir_url, geometry_geojson)

    # Indices
    ndvi = (nir - red) / (nir + red + 1e-6)
    ndmi = (nir - swir) / (nir + swir + 1e-6)

    # EVI = 2.5*(NIR-RED) / (NIR + 6*RED - 7.5*BLUE + 1)
    evi = 2.5 * (nir - red) / (nir + 6.0 * red - 7.5 * blue + 1.0 + 1e-6)

    # Clip to sane bounds (optional but helps UI)
    def clip(v, lo=-1.0, hi=1.0):
        try:
            return float(np.clip(v, lo, hi))
        except Exception:
            return float(v)

    return {
        "ndvi": clip(ndvi),
        "ndmi": clip(ndmi),
        "evi":  clip(evi, lo=-2.0, hi=2.0),
        "cloud_cover": float(item.properties.get("eo:cloud_cover", 100.0)),
        "scene_date": item.datetime.isoformat(),
    }


def _search_items(geometry_geojson: dict, start_date: str, end_date: str, limit: int = 30):
    catalog = Client.open(STAC_URL)

    search = catalog.search(
        collections=["sentinel-2-l2a"],
        intersects=geometry_geojson,
        datetime=f"{start_date}/{end_date}",
        limit=limit,
    )
    items = list(search.get_items())
    return items


def _compute_change_pct(timeseries: List[dict]) -> Dict[str, Any]:
    """
    NDVI change%: compares last 30 days mean NDVI vs previous 30 days mean NDVI
    Uses available points only.
    """
    if not timeseries:
        return {"ndvi_change_pct": None, "period_days": 30}

    # Convert to dt
    pts = []
    for p in timeseries:
        dt = _parse_dt(p["date"])
        pts.append((dt, p.get("ndvi")))

    pts.sort(key=lambda x: x[0])
    end_dt = pts[-1][0]
    last_start = end_dt - timedelta(days=30)
    prev_start = end_dt - timedelta(days=60)

    last_vals = [v for (d, v) in pts if d >= last_start and v is not None]
    prev_vals = [v for (d, v) in pts if (d >= prev_start and d < last_start) and v is not None]

    if len(last_vals) < 2 or len(prev_vals) < 2:
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
    """
    Main function used by your route.
    Returns:
      summary: latest/best scene stats
      timeseries: [{date, ndvi, ndmi, evi, cloud_cover}]
      change: NDVI % change last 30d vs previous 30d
    """
    items = _search_items(geometry_geojson, start_date, end_date, limit=30)
    if not items:
        raise Exception("No Sentinel-2 scenes found for this polygon/date range.")

    # Prefer lower clouds
    items.sort(key=lambda x: x.properties.get("eo:cloud_cover", 100.0))

    # Build timeseries from top N cleanest but also spread by time
    # We'll take up to 12 scenes among the best 25 by cloud (then sort by date)
    best = items[:25]
    best_signed = [pc.sign(it) for it in best]

    series = []
    for it in best_signed:
        try:
            stats = _compute_indices_for_item(it, geometry_geojson)
            series.append({
                "date": stats["scene_date"],
                "ndvi": stats["ndvi"],
                "ndmi": stats["ndmi"],
                "evi":  stats["evi"],
                "cloud_cover": stats["cloud_cover"],
            })
        except Exception:
            # Skip problematic scenes
            continue

    if not series:
        raise Exception("Scenes found, but none could be processed for this polygon.")

    # Sort by date and keep last 12 points for chart
    series.sort(key=lambda p: p["date"])
    series_for_chart = series[-12:]

    # Summary = latest point (more intuitive for user)
    summary = series_for_chart[-1].copy()

    change = _compute_change_pct(series)

    return {
        "summary": summary,
        "timeseries": series_for_chart,
        "change": change,
    }