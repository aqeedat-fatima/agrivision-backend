from pystac_client import Client
import planetary_computer as pc

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"


def compute_ndvi_stats(geometry_geojson, start_date, end_date):
    """
    geometry_geojson: GeoJSON geometry in EPSG:4326 (Leaflet draw gives lon/lat)
    start_date/end_date: 'YYYY-MM-DD'
    Returns: dict with mean/min/max NDVI + scene metadata
    """
    import numpy as np
    import rasterio
    from rasterio.mask import mask
    from shapely.geometry import shape, mapping
    from shapely.ops import transform as shp_transform
    from pyproj import Transformer

    # --- helpers ---
    def _reproject_geom(geom_geojson_4326, dst_crs):
        """
        Reproject a GeoJSON geometry from EPSG:4326 -> dst_crs (raster CRS).
        rasterio.mask does NOT reproject automatically, so we must do it.
        """
        geom = shape(geom_geojson_4326)
        transformer = Transformer.from_crs("EPSG:4326", dst_crs, always_xy=True)
        geom2 = shp_transform(transformer.transform, geom)
        return mapping(geom2)

    def _masked_band(src, geom_geojson_4326):
        geom_in_raster = _reproject_geom(geom_geojson_4326, src.crs)
        try:
            data, _ = mask(src, [geom_in_raster], crop=True)
            return data[0].astype("float32")
        except ValueError as e:
            # rasterio raises ValueError("Input shapes do not overlap raster.")
            raise ValueError(
                "Input shapes do not overlap raster. "
                "This can happen if the polygon is outside the scene footprint "
                "or if reprojection failed."
            ) from e

    # --- STAC search ---
    catalog = Client.open(STAC_URL)
    search = catalog.search(
        collections=["sentinel-2-l2a"],
        intersects=geometry_geojson,
        datetime=f"{start_date}/{end_date}",
        limit=25,  # a bit more choice helps find overlap / lower cloud
    )

    items = list(search.get_items())
    if not items:
        raise Exception("No Sentinel-2 scenes found for the given date range/area.")

    # pick lowest cloud cover
    items.sort(key=lambda x: x.properties.get("eo:cloud_cover", 100))
    item = pc.sign(items[0])

    # Sentinel-2 bands
    if "B04" not in item.assets or "B08" not in item.assets:
        raise Exception("Selected Sentinel-2 item missing B04/B08 assets.")

    red_url = item.assets["B04"].href  # Red
    nir_url = item.assets["B08"].href  # NIR

    # --- read + clip ---
    with rasterio.open(red_url) as red_src:
        red = _masked_band(red_src, geometry_geojson)

    with rasterio.open(nir_url) as nir_src:
        nir = _masked_band(nir_src, geometry_geojson)

    # NDVI
    ndvi = (nir - red) / (nir + red + 1e-6)

    # mask invalids
    ndvi = np.ma.masked_invalid(ndvi)

    # If everything becomes masked (e.g., polygon only covers nodata)
    if ndvi.count() == 0:
        raise Exception(
            "No valid NDVI pixels inside the polygon (could be nodata/cloud mask/edge). "
            "Try a different date range or a slightly larger polygon."
        )

    return {
        "mean": float(ndvi.mean()),
        "min": float(ndvi.min()),
        "max": float(ndvi.max()),
        "cloud_cover": item.properties.get("eo:cloud_cover"),
        "scene_date": str(item.datetime),
    }