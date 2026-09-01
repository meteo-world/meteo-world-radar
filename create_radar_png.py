#!/usr/bin/env python3

from pathlib import Path
import subprocess
import json
import math

import numpy as np
from PIL import Image
from osgeo import gdal


# ============================================================
# DOSSIERS
# ============================================================

ROOT = Path(__file__).resolve().parent

OUTPUT = ROOT / "output"
DATA = ROOT / "data"

OUTPUT.mkdir(exist_ok=True)
DATA.mkdir(exist_ok=True)


# ============================================================
# RECHERCHE DU TIFF ORIGINAL
# ============================================================

files = sorted(
    [
        p for p in OUTPUT.glob("radar_*.tif")
        if p.name not in {
            "radar-latest.tif",
            "radar-latest-3857.tif",
            "radar-latest-4326.tif",
        }
    ],
    key=lambda p: p.stat().st_mtime,
    reverse=True
)


if files:

    source_tif = files[0]

else:

    source_tif = OUTPUT / "radar-latest.tif"


if not source_tif.exists():

    raise SystemExit(
        "ERREUR : aucun GeoTIFF radar disponible."
    )


print("")
print("==============================================")
print("METEO WORLD - CREATION RADAR")
print("==============================================")
print("")
print("TIFF source :", source_tif)


# ============================================================
# REPROJECTION VERS WEB MERCATOR
# ============================================================

mercator_tif = OUTPUT / "radar-latest-3857.tif"


print("")
print("Reprojection vers EPSG:3857...")


commande = [

    "gdalwarp",

    "-overwrite",

    "-t_srs",
    "EPSG:3857",

    "-r",
    "near",

    "-dstnodata",
    "-9999",

    "-ot",
    "Float32",

    "-multi",

    "-wo",
    "NUM_THREADS=ALL_CPUS",

    str(source_tif),

    str(mercator_tif),

]


subprocess.run(
    commande,
    check=True
)


print("Reprojection terminee.")


# ============================================================
# OUVERTURE DU TIFF 3857
# ============================================================

dataset = gdal.Open(
    str(mercator_tif)
)


if dataset is None:

    raise SystemExit(
        "ERREUR : impossible d'ouvrir le TIFF EPSG:3857."
    )


band = dataset.GetRasterBand(1)

array = band.ReadAsArray().astype(
    np.float32
)


width = dataset.RasterXSize
height = dataset.RasterYSize


print("")
print("Dimensions :", width, "x", height)


# ============================================================
# GEOREFERENCEMENT EPSG:3857
# ============================================================

gt = dataset.GetGeoTransform()


xmin = gt[0]

ymax = gt[3]

xmax = (
    xmin
    + gt[1] * width
    + gt[2] * height
)

ymin = (
    ymax
    + gt[4] * width
    + gt[5] * height
)


print("")
print("Bounds EPSG:3857 :")
print("xmin :", xmin)
print("xmax :", xmax)
print("ymin :", ymin)
print("ymax :", ymax)


# ============================================================
# CONVERSION WEB MERCATOR -> LAT/LON
# ============================================================

R = 6378137.0


def mercator_to_lonlat(x, y):

    lon = math.degrees(
        x / R
    )

    lat = math.degrees(
        math.atan(
            math.sinh(
                y / R
            )
        )
    )

    return lon, lat


west, north = mercator_to_lonlat(
    xmin,
    ymax
)

east, south = mercator_to_lonlat(
    xmax,
    ymin
)


print("")
print("Bounds Leaflet :")
print("south :", south)
print("west  :", west)
print("north :", north)
print("east  :", east)


# ============================================================
# MASQUE DES DONNEES VALIDES
# ============================================================

valid = (

    np.isfinite(array)

    &

    (array > -9990)

)


if not np.any(valid):

    raise SystemExit(
        "ERREUR : aucune donnee radar valide."
    )


minimum = float(
    np.min(array[valid])
)

maximum = float(
    np.max(array[valid])
)


print("")
print(
    "Reflectivite min/max :",
    minimum,
    "/",
    maximum,
    "dBZ"
)


# ============================================================
# IMAGE RGBA
# ============================================================

rgba = np.zeros(
    (
        height,
        width,
        4
    ),
    dtype=np.uint8
)


# ============================================================
# PALETTE RADAR
# ============================================================

palette = [

    (-40, (0, 0, 0, 0)),

    (0,   (100, 220, 255, 100)),

    (5,   (70, 190, 255, 120)),

    (10,  (40, 150, 255, 140)),

    (15,  (0, 110, 255, 160)),

    (20,  (0, 210, 120, 170)),

    (25,  (0, 180, 70, 180)),

    (30,  (180, 220, 0, 190)),

    (35,  (255, 230, 0, 200)),

    (40,  (255, 180, 0, 210)),

    (45,  (255, 110, 0, 220)),

    (50,  (255, 30, 0, 230)),

    (55,  (210, 0, 0, 235)),

    (60,  (180, 0, 180, 240)),

    (65,  (220, 0, 220, 245)),

    (70,  (255, 120, 255, 250)),

    (75,  (255, 255, 255, 255)),

]


# ============================================================
# COLORISATION
# ============================================================

for i in range(
    1,
    len(palette)
):

    low_value = palette[i][0]

    if i < len(palette) - 1:

        high_value = palette[i + 1][0]

        mask = (
            valid
            &
            (array >= low_value)
            &
            (array < high_value)
        )

    else:

        mask = (
            valid
            &
            (array >= low_value)
        )


    rgba[
        mask
    ] = palette[i][1]


# ============================================================
# TRANSPARENCE SOUS 0 DBZ
# ============================================================

rgba[
    ~valid
] = (
    0,
    0,
    0,
    0
)


rgba[
    valid
    &
    (array < 0)
] = (
    0,
    0,
    0,
    0
)


# ============================================================
# CREATION PNG
# ============================================================

png_path = DATA / "radar-latest.png"


image = Image.fromarray(
    rgba,
    mode="RGBA"
)


image.save(
    png_path,
    optimize=True
)


print("")
print(
    "PNG cree :",
    png_path
)


# ============================================================
# RECUPERATION DATE RADAR
# ============================================================

datetime_radar = None


metadata_path = (
    DATA
    / "latest-imfr27.json"
)


if metadata_path.exists():

    try:

        metadata = json.loads(
            metadata_path.read_text(
                encoding="utf-8"
            )
        )

        datetime_radar = (

            metadata.get("datetime")

            or metadata.get("date")

            or metadata.get(
                "radar_datetime"
            )

            or metadata.get(
                "observation_time"
            )

            or metadata.get("time")

        )

    except Exception as e:

        print(
            "Lecture date radar impossible :",
            e
        )


# ============================================================
# JSON POUR LEAFLET
# ============================================================

json_data = {

    "source_tiff":
        source_tif.name,

    "reprojected_tiff":
        mercator_tif.name,

    "png":
        "radar-latest.png",

    "projection":
        "EPSG:3857",

    "width":
        width,

    "height":
        height,

    "bounds": {

        "south":
            south,

        "west":
            west,

        "north":
            north,

        "east":
            east,

    },

    "display_min_dbz":
        0,

    "transparent_below_dbz":
        0,

    "reflectivity_min_dbz":
        minimum,

    "reflectivity_max_dbz":
        maximum,

}


if datetime_radar:

    json_data[
        "datetime"
    ] = datetime_radar


json_path = (
    DATA
    / "radar-latest.json"
)


json_path.write_text(

    json.dumps(
        json_data,
        indent=2,
        ensure_ascii=False
    ),

    encoding="utf-8"

)


print(
    "JSON cree :",
    json_path
)


# ============================================================
# RESULTAT
# ============================================================

print("")
print("==============================================")
print("RADAR METEO WORLD TERMINE")
print("==============================================")

print(
    "Projection : EPSG:3857"
)

print(
    "PNG        :",
    png_path
)

print(
    "JSON       :",
    json_path
)

print(
    "Bounds     :",
    json_data["bounds"]
)

print("==============================================")
