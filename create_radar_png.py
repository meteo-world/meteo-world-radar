#!/usr/bin/env python3

from pathlib import Path
import subprocess
import json
import math
import shutil
import re
from datetime import datetime, timezone

import numpy as np
from PIL import Image


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
# DATE / HEURE DU RADAR
# ============================================================

radar_datetime = None


# ------------------------------------------------------------
# 1. Lecture du JSON produit par download_radar.py
# ------------------------------------------------------------

metadata_path = DATA / "latest-imfr27.json"


if metadata_path.exists():

    try:

        metadata = json.loads(
            metadata_path.read_text(
                encoding="utf-8"
            )
        )

        date_value = (
            metadata.get("datetime")
            or metadata.get("date")
            or metadata.get("radar_datetime")
            or metadata.get("observation_time")
            or metadata.get("time")
        )

        if date_value:

            try:

                radar_datetime = datetime.fromisoformat(
                    str(date_value).replace(
                        "Z",
                        "+00:00"
                    )
                )

            except Exception:

                pass

    except Exception as e:

        print(
            "Lecture metadata radar impossible :",
            e
        )


# ------------------------------------------------------------
# 2. Si nécessaire, récupération depuis le nom du TIFF
#
# Exemple :
# radar_2026-09-01_08-25-00.tif
# ------------------------------------------------------------

if radar_datetime is None:

    match = re.search(
        r"radar_(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})",
        source_tif.name
    )

    if match:

        radar_datetime = datetime(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            int(match.group(4)),
            int(match.group(5)),
            int(match.group(6)),
            tzinfo=timezone.utc
        )


# ------------------------------------------------------------
# 3. Dernier secours
# ------------------------------------------------------------

if radar_datetime is None:

    radar_datetime = datetime.now(
        timezone.utc
    )


# On s'assure que l'heure est UTC

if radar_datetime.tzinfo is None:

    radar_datetime = radar_datetime.replace(
        tzinfo=timezone.utc
    )

else:

    radar_datetime = radar_datetime.astimezone(
        timezone.utc
    )


radar_iso = (
    radar_datetime
    .replace(microsecond=0)
    .isoformat()
    .replace("+00:00", "Z")
)


# Nom utilisé pour l'historique Infomaniak

frame_filename = radar_datetime.strftime(
    "radar-%Y%m%d-%H%M.png"
)


print("")
print("Date radar :", radar_iso)
print("Frame      :", frame_filename)


# ============================================================
# REPROJECTION EPSG:3857
# ============================================================

mercator_tif = (
    OUTPUT
    / "radar-latest-3857.tif"
)


print("")
print("==============================================")
print("REPROJECTION EPSG:3857")
print("==============================================")


subprocess.run(
    [
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
    ],
    check=True
)


if not mercator_tif.exists():

    raise SystemExit(
        "ERREUR : le TIFF EPSG:3857 n'a pas ete cree."
    )


print("")
print(
    "TIFF EPSG:3857 cree :",
    mercator_tif
)


# ============================================================
# GDALINFO JSON
# ============================================================

gdalinfo_result = subprocess.run(
    [
        "gdalinfo",
        "-json",
        str(mercator_tif)
    ],
    check=True,
    capture_output=True,
    text=True
)


try:

    info = json.loads(
        gdalinfo_result.stdout
    )

except Exception as e:

    raise SystemExit(
        f"ERREUR lecture JSON gdalinfo : {e}"
    )


# ============================================================
# DIMENSIONS
# ============================================================

size = info.get("size")


if not size or len(size) != 2:

    raise SystemExit(
        "ERREUR : dimensions TIFF introuvables."
    )


width = int(size[0])
height = int(size[1])


print("")
print(
    "Dimensions :",
    width,
    "x",
    height
)


# ============================================================
# GEOTRANSFORM
# ============================================================

gt = info.get("geoTransform")


if not gt or len(gt) != 6:

    raise SystemExit(
        "ERREUR : GeoTransform introuvable."
    )


xmin = float(gt[0])
pixel_width = float(gt[1])
rotation_x = float(gt[2])

ymax = float(gt[3])
rotation_y = float(gt[4])
pixel_height = float(gt[5])


xmax = (
    xmin
    + pixel_width * width
    + rotation_x * height
)


ymin = (
    ymax
    + rotation_y * width
    + pixel_height * height
)


print("")
print("Bounds EPSG:3857 :")
print("xmin =", xmin)
print("xmax =", xmax)
print("ymin =", ymin)
print("ymax =", ymax)


# ============================================================
# EPSG:3857 -> LATITUDE / LONGITUDE
# ============================================================

EARTH_RADIUS = 6378137.0


def mercator_to_lonlat(x, y):

    lon = math.degrees(
        x / EARTH_RADIUS
    )

    lat = math.degrees(
        math.atan(
            math.sinh(
                y / EARTH_RADIUS
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
print("==============================================")
print("BOUNDS LEAFLET")
print("==============================================")

print("south =", south)
print("west  =", west)
print("north =", north)
print("east  =", east)


# ============================================================
# EXPORT FLOAT32
# ============================================================

raw_file = (
    OUTPUT
    / "radar-latest.raw"
)

hdr_file = (
    OUTPUT
    / "radar-latest.hdr"
)


if raw_file.exists():
    raw_file.unlink()

if hdr_file.exists():
    hdr_file.unlink()


print("")
print("==============================================")
print("LECTURE DES VALEURS RADAR")
print("==============================================")


subprocess.run(
    [
        "gdal_translate",
        "-q",
        "-of",
        "ENVI",
        "-ot",
        "Float32",
        str(mercator_tif),
        str(raw_file),
    ],
    check=True
)


if not raw_file.exists():

    raise SystemExit(
        "ERREUR : fichier raster brut absent."
    )


# ============================================================
# LECTURE NUMPY
# ============================================================

expected_values = (
    width
    * height
)


array = np.fromfile(
    raw_file,
    dtype=np.float32
)


if array.size != expected_values:

    raise SystemExit(
        "ERREUR : taille raster inattendue. "
        f"Attendu={expected_values}, "
        f"obtenu={array.size}"
    )


array = array.reshape(
    (
        height,
        width
    )
)


# ============================================================
# DONNEES VALIDES
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
    np.min(
        array[valid]
    )
)


maximum = float(
    np.max(
        array[valid]
    )
)


print("")
print(
    "Reflectivite minimum :",
    minimum,
    "dBZ"
)

print(
    "Reflectivite maximum :",
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
# PALETTE METEO WORLD
# ============================================================

palette = [

    (0,  (100, 220, 255, 100)),
    (5,  (70, 190, 255, 120)),
    (10, (40, 150, 255, 140)),
    (15, (0, 110, 255, 160)),
    (20, (0, 210, 120, 170)),
    (25, (0, 180, 70, 180)),
    (30, (180, 220, 0, 190)),
    (35, (255, 230, 0, 200)),
    (40, (255, 180, 0, 210)),
    (45, (255, 110, 0, 220)),
    (50, (255, 30, 0, 230)),
    (55, (210, 0, 0, 235)),
    (60, (180, 0, 180, 240)),
    (65, (220, 0, 220, 245)),
    (70, (255, 120, 255, 250)),
    (75, (255, 255, 255, 255)),

]


# ============================================================
# COLORISATION
# ============================================================

for i, item in enumerate(palette):

    low_value = item[0]
    color = item[1]


    if i < len(palette) - 1:

        high_value = (
            palette[i + 1][0]
        )

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


    rgba[mask] = color


# ============================================================
# TRANSPARENCE < 0 DBZ
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
# CREATION RADAR-LATEST.PNG
# ============================================================

png_path = (
    DATA
    / "radar-latest.png"
)


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
    "PNG principal cree :",
    png_path
)


# ============================================================
# CREATION DE LA FRAME
#
# On crée simplement une copie locale.
# radar.yml décidera ensuite où l'envoyer sur Infomaniak.
# ============================================================

frame_path = (
    DATA
    / "frame-radar.png"
)


shutil.copyfile(
    png_path,
    frame_path
)


print(
    "Frame creee :",
    frame_path
)


# ============================================================
# JSON PRINCIPAL POUR LEAFLET
# ============================================================

bounds = {

    "south": south,
    "west": west,
    "north": north,
    "east": east,

}


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

    "bounds":
        bounds,

    "datetime":
        radar_iso,

    "display_min_dbz":
        0,

    "transparent_below_dbz":
        0,

    "reflectivity_min_dbz":
        minimum,

    "reflectivity_max_dbz":
        maximum,

}


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
    "JSON principal cree :",
    json_path
)


# ============================================================
# INFORMATIONS DE LA FRAME
# ============================================================

frame_info = {

    "filename":
        frame_filename,

    "datetime":
        radar_iso,

    "projection":
        "EPSG:3857",

    "bounds":
        bounds,

    "width":
        width,

    "height":
        height,

}


frame_info_path = (
    DATA
    / "frame-info.json"
)


frame_info_path.write_text(
    json.dumps(
        frame_info,
        indent=2,
        ensure_ascii=False
    ),
    encoding="utf-8"
)


print(
    "Informations frame :",
    frame_info_path
)


# ============================================================
# NETTOYAGE
# ============================================================

try:

    if raw_file.exists():
        raw_file.unlink()

    if hdr_file.exists():
        hdr_file.unlink()

except Exception as e:

    print(
        "Nettoyage fichiers temporaires :",
        e
    )


# ============================================================
# RESULTAT
# ============================================================

print("")
print("==============================================")
print("RADAR METEO WORLD TERMINE")
print("==============================================")

print(
    "Projection       : EPSG:3857"
)

print(
    "Date radar       :",
    radar_iso
)

print(
    "Radar principal  :",
    png_path
)

print(
    "JSON principal   :",
    json_path
)

print(
    "Frame locale     :",
    frame_path
)

print(
    "Nom future frame :",
    frame_filename
)

print(
    "Frame info       :",
    frame_info_path
)

print(
    "Bounds           :",
    bounds
)

print("==============================================")
