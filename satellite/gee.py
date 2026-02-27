import os
import ee

_EE_INITIALIZED = False

def init_ee():
    global _EE_INITIALIZED
    if _EE_INITIALIZED:
        return

    sa = os.getenv("GEE_SERVICE_ACCOUNT")
    key_path = os.getenv("GEE_PRIVATE_KEY_JSON")

    if not sa or not key_path:
        raise RuntimeError("Missing GEE_SERVICE_ACCOUNT or GEE_PRIVATE_KEY_JSON env vars.")

    credentials = ee.ServiceAccountCredentials(sa, key_path)
    ee.Initialize(credentials)
    _EE_INITIALIZED = True


def geojson_to_ee_geometry(geojson: dict) -> ee.Geometry:
    gtype = geojson.get("type")
    coords = geojson.get("coordinates")

    if gtype == "Polygon":
        return ee.Geometry.Polygon(coords)
    if gtype == "MultiPolygon":
        return ee.Geometry.MultiPolygon(coords)

    raise ValueError(f"Unsupported GeoJSON geometry type: {gtype}")


def _mask_s2_sr(image: ee.Image) -> ee.Image:
    # SCL: 3 shadow, 8/9 clouds, 10 cirrus, 11 snow
    scl = image.select("SCL")
    mask = (
        scl.neq(3)
        .And(scl.neq(8))
        .And(scl.neq(9))
        .And(scl.neq(10))
        .And(scl.neq(11))
    )
    return image.updateMask(mask)


def ndvi_image_for_range(geometry: ee.Geometry, start_date: str, end_date: str) -> ee.Image:
    col = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(geometry)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 60))
        .map(_mask_s2_sr)
    )

    ndvi_col = col.map(lambda img: img.normalizedDifference(["B8", "B4"]).rename("NDVI"))
    return ndvi_col.median().clip(geometry)


def get_ndvi_tiles_url(ndvi_img: ee.Image) -> str:
    # Simple farmer palette: red → yellow → green
    vis = {"min": 0.0, "max": 0.8, "palette": ["#d94b4b", "#f3c969", "#3cb371"]}
    map_id = ee.Image(ndvi_img).getMapId(vis)
    return map_id["tile_fetcher"].url_format


def reduce_ndvi_stats(ndvi_img: ee.Image, geometry: ee.Geometry) -> dict:
    stats = ndvi_img.reduceRegion(
        reducer=ee.Reducer.mean().combine(ee.Reducer.minMax(), sharedInputs=True),
        geometry=geometry,
        scale=10,
        maxPixels=1e9
    ).getInfo()

    return {
        "mean": stats.get("NDVI_mean"),
        "min": stats.get("NDVI_min"),
        "max": stats.get("NDVI_max"),
    }


def weekly_timeseries(geometry: ee.Geometry, start_date: str, end_date: str):
    start = ee.Date(start_date)
    end = ee.Date(end_date)
    n_weeks = end.difference(start, "week").ceil()

    def mk_feat(i):
        i = ee.Number(i)
        w_start = start.advance(i, "week")
        w_end = w_start.advance(1, "week")

        ndvi = ndvi_image_for_range(geometry, w_start.format("YYYY-MM-dd"), w_end.format("YYYY-MM-dd"))
        mean_dict = ndvi.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geometry,
            scale=10,
            maxPixels=1e9
        )
        mean_val = ee.Number(mean_dict.get("NDVI"))
        return ee.Feature(None, {"date": w_start.format("YYYY-MM-dd"), "mean_ndvi": mean_val})

    fc = ee.FeatureCollection(ee.List.sequence(0, n_weeks.subtract(1)).map(mk_feat))
    data = fc.getInfo()

    out = []
    for f in data["features"]:
        p = f["properties"]
        out.append({"date": p.get("date"), "mean_ndvi": p.get("mean_ndvi")})
    return out