import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image


# ============================================================
# DOSSIERS
# ============================================================

OUTPUT = Path("output")
DATA = Path("data")

DATA.mkdir(exist_ok=True)


# ============================================================
# RECHERCHE DU TIFF RADAR
# ============================================================

files = sorted(
    OUTPUT.glob("radar_*.tif"),
    key=lambda p: p.stat().st_mtime,
    reverse=True,
)

if not files:
    raise SystemExit(
        "ERREUR : aucun TIFF radar_*.tif dans output/."
    )

source_tif = files[0]

warped_tif = OUTPUT / "radar-latest-4326.tif"

raw_bin = DATA / "radar-values.bin"

png = DATA / "radar-latest.png"

meta = DATA / "radar-latest.json"


print("=====================================")
print("METEO WORLD - REPROJECTION RADAR")
print("=====================================")

print("TIFF source :", source_tif)


# ============================================================
# INFORMATIONS DU TIFF SOURCE
# ============================================================

source_info = json.loads(
    subprocess.check_output(
        [
            "gdalinfo",
            "-json",
            str(source_tif)
        ],
        text=True,
    )
)

print("")
print("Taille source :", source_info.get("size"))

print(
    "Projection source détectée automatiquement par GDAL."
)


# ============================================================
# REPROJECTION
# ============================================================
#
# IMPORTANT :
#
# On NE FORCE PAS -s_srs.
#
# GDAL lit directement le système de coordonnées contenu
# dans le GeoTIFF créé par debufrizer.
#
# Destination :
#
# EPSG:4326
#
# Ce raster pourra ensuite être utilisé comme une image
# rectangulaire latitude / longitude dans Leaflet.
#
# ============================================================

print("")
print("Reprojection vers EPSG:4326...")


subprocess.run(
    [
        "gdalwarp",

        "-overwrite",

        "-t_srs",
        "EPSG:4326",

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

        str(warped_tif),
    ],
    check=True,
)


print("Reprojection terminée.")


# ============================================================
# INFORMATIONS DU TIFF REPROJETE
# ============================================================

info = json.loads(
    subprocess.check_output(
        [
            "gdalinfo",
            "-json",
            "-stats",
            str(warped_tif)
        ],
        text=True,
    )
)


width, height = info["size"]

band = info["bands"][0]


print("")
print("=====================================")
print("TIFF EPSG:4326")
print("=====================================")

print("Taille :", width, "x", height)

print(
    "Minimum :",
    band.get("minimum")
)

print(
    "Maximum :",
    band.get("maximum")
)

print(
    "NoData :",
    band.get("noDataValue")
)


# ============================================================
# EXTRACTION DES VALEURS
# ============================================================

print("")
print("Lecture des réflectivités...")


subprocess.run(
    [
        "gdal_translate",

        "-q",

        "-b",
        "1",

        "-of",
        "ENVI",

        "-ot",
        "Float32",

        str(warped_tif),

        str(raw_bin),
    ],
    check=True,
)


values = np.fromfile(
    raw_bin,
    dtype=np.float32
)


expected = width * height


if values.size != expected:

    raise SystemExit(
        "ERREUR : "
        f"{values.size} valeurs trouvées "
        f"au lieu de {expected}."
    )


values = values.reshape(
    (
        height,
        width
    )
)


# ============================================================
# MASQUE
# ============================================================

finite = np.isfinite(values)


nodata = band.get("noDataValue")


if nodata is not None:

    finite &= (
        values != float(nodata)
    )


# ============================================================
# PALETTE METEO WORLD
# ============================================================

levels = np.array(
    [
        0,
        5,
        10,
        15,
        20,
        25,
        30,
        35,
        40,
        45,
        50,
        55,
        60,
        65,
        75
    ],
    dtype=np.float32,
)


palette = np.array(
    [
        [120, 190, 255, 80],
        [70, 160, 255, 110],
        [30, 120, 255, 140],
        [0, 190, 230, 165],
        [0, 200, 150, 180],
        [40, 190, 70, 195],
        [130, 210, 40, 210],
        [230, 220, 20, 220],
        [255, 175, 0, 230],
        [255, 110, 0, 235],
        [245, 40, 20, 240],
        [210, 0, 60, 245],
        [180, 0, 140, 250],
        [220, 80, 220, 255],
        [255, 255, 255, 255],
    ],
    dtype=np.uint8,
)


# ============================================================
# IMAGE TRANSPARENTE
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
# ECHOS RADAR
# ============================================================
#
# Pour le moment on conserve le seuil de 0 dBZ.
#
# On ne change PAS simultanément le seuil et le
# géoréférencement : cela permettra de vérifier uniquement
# le positionnement.
#
# ============================================================

echo = (
    finite
    &
    (values >= 0.0)
)


indices = np.searchsorted(
    levels,
    values,
    side="right"
) - 1


indices = np.clip(
    indices,
    0,
    len(palette) - 1
)


rgba[echo] = palette[
    indices[echo]
]


# ============================================================
# CREATION PNG
# ============================================================

image = Image.fromarray(
    rgba,
    "RGBA"
)


image.save(
    png,
    optimize=True
)


# ============================================================
# COORDONNEES EXACTES DU RASTER REPROJETE
# ============================================================

geo = info.get(
    "geoTransform"
)


if not geo:

    raise SystemExit(
        "ERREUR : geoTransform absent."
    )


#
# GeoTransform GDAL :
#
# [0] longitude bord gauche
# [1] largeur pixel
# [3] latitude bord supérieur
# [5] hauteur pixel (négative)
#
# On calcule les BORDS réels du raster.
#

west = float(
    geo[0]
)

north = float(
    geo[3]
)

east = (
    west
    +
    float(geo[1]) * width
)

south = (
    north
    +
    float(geo[5]) * height
)


# Sécurité

if south > north:

    south, north = north, south


if west > east:

    west, east = east, west


print("")
print("=====================================")
print("BOUNDS LEAFLET")
print("=====================================")

print("Sud   :", south)
print("Ouest :", west)
print("Nord  :", north)
print("Est   :", east)


# ============================================================
# DATE DU RADAR
# ============================================================

metadata_source = (
    source_info
    .get("metadata", {})
    .get("", {})
)


radar_datetime = (
    metadata_source.get(
        "TIFFTAG_DATETIME"
    )
)


# ============================================================
# JSON
# ============================================================

metadata = {

    "source_tiff":
        source_tif.name,

    "reprojected_tiff":
        warped_tif.name,

    "png":
        png.name,

    "projection":
        "EPSG:4326",

    "width":
        width,

    "height":
        height,

    "datetime":
        radar_datetime,

    "bounds": {

        "south":
            south,

        "west":
            west,

        "north":
            north,

        "east":
            east
    },

    "display_min_dbz":
        0,

    "transparent_below_dbz":
        0,

    "reflectivity_min_dbz":
        band.get("minimum"),

    "reflectivity_max_dbz":
        band.get("maximum"),
}


meta.write_text(

    json.dumps(
        metadata,
        indent=2,
        ensure_ascii=False
    ),

    encoding="utf-8",
)


# ============================================================
# NETTOYAGE
# ============================================================

temporary_files = [

    raw_bin,

    raw_bin.with_suffix(
        ".hdr"
    ),

    Path(
        str(raw_bin)
        +
        ".aux.xml"
    ),
]


for temporary in temporary_files:

    try:

        temporary.unlink()

    except FileNotFoundError:

        pass


# ============================================================
# RESULTAT
# ============================================================

print("")
print("=====================================")
print("RADAR METEO WORLD TERMINE")
print("=====================================")

print(
    "Pixels radar visibles :",
    int(
        echo.sum()
    )
)

print(
    "Pixels transparents :",
    int(
        (~echo).sum()
    )
)

print(
    "PNG :",
    png
)

print(
    "JSON :",
    meta
)

print(
    "Taille PNG : %.2f Mo"
    %
    (
        png.stat().st_size
        /
        1024
        /
        1024
    )
)
