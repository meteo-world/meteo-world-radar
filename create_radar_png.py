import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

OUTPUT = Path("output")
DATA = Path("data")
DATA.mkdir(exist_ok=True)

files = sorted(
    OUTPUT.glob("radar_*.tif"),
    key=lambda p: p.stat().st_mtime,
    reverse=True,
)

if not files:
    raise SystemExit("ERREUR : aucun TIFF radar_*.tif dans output/.")

tif = files[0]
png = DATA / "radar-latest.png"
meta = DATA / "radar-latest.json"
raw_bin = DATA / "radar-values.bin"

print("TIFF sélectionné :", tif)

# Informations géographiques et statistiques du GeoTIFF.
info = json.loads(
    subprocess.check_output(
        ["gdalinfo", "-json", "-stats", str(tif)],
        text=True,
    )
)

width, height = info["size"]
band = info["bands"][0]

print("Taille raster :", info["size"])
print("Nombre de bandes :", len(info.get("bands", [])))
print(
    "Bande 1 - type:", band.get("type"),
    "- min:", band.get("minimum"),
    "- max:", band.get("maximum"),
    "- nodata:", band.get("noDataValue"),
)

# Lecture brute de la réflectivité en Float32.
# Cela évite gdaldem color-relief : ici nous maîtrisons explicitement
# le canal alpha et pouvons rendre l'absence d'écho totalement transparente.
subprocess.run(
    [
        "gdal_translate",
        "-q",
        "-b", "1",
        "-of", "ENVI",
        "-ot", "Float32",
        str(tif),
        str(raw_bin),
    ],
    check=True,
)

values = np.fromfile(raw_bin, dtype=np.float32)

if values.size != width * height:
    raise SystemExit(
        f"ERREUR : taille raster inattendue ({values.size} valeurs "
        f"au lieu de {width * height})."
    )

values = values.reshape((height, width))

finite = np.isfinite(values)
print(
    "Valeurs finies :",
    int(finite.sum()),
    "/",
    values.size,
)

# Palette radar Météo-World.
# Seuls les échos >= 0 dBZ sont affichés.
# Les valeurs négatives correspondent ici à l'absence d'écho / échos
# trop faibles pour notre affichage public et deviennent transparentes.
levels = np.array(
    [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 75],
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

rgba = np.zeros((height, width, 4), dtype=np.uint8)

# Masque essentiel : pas d'écho => alpha 0.
echo = finite & (values >= 0.0)

# Affectation de la couleur correspondant au niveau inférieur.
idx = np.searchsorted(levels, values, side="right") - 1
idx = np.clip(idx, 0, len(palette) - 1)

rgba[echo] = palette[idx[echo]]

Image.fromarray(rgba, mode="RGBA").save(
    png,
    optimize=True,
)

# Nettoyage des fichiers temporaires ENVI.
for p in (
    raw_bin,
    raw_bin.with_suffix(".hdr"),
    Path(str(raw_bin) + ".aux.xml"),
):
    try:
        p.unlink()
    except FileNotFoundError:
        pass

cc = info.get("cornerCoordinates", {})
projection = info.get("coordinateSystem", {}).get("wkt", "")

metadata = {
    "source_tiff": tif.name,
    "png": png.name,
    "width": width,
    "height": height,
    "display_min_dbz": 0,
    "transparent_below_dbz": 0,
    "reflectivity_min_dbz": band.get("minimum"),
    "reflectivity_max_dbz": band.get("maximum"),
    "cornerCoordinates": cc,
    "projection_wkt": projection,
}

meta.write_text(
    json.dumps(metadata, indent=2, ensure_ascii=False),
    encoding="utf-8",
)

print("Pixels radar visibles :", int(echo.sum()))
print("Pixels transparents :", int((~echo).sum()))
print("PNG créé :", png)
print("Métadonnées :", meta)
print("Taille PNG : %.2f Mo" % (png.stat().st_size / 1024 / 1024))
