import json
import subprocess
from pathlib import Path

OUTPUT = Path('output')
DATA = Path('data')
DATA.mkdir(exist_ok=True)

files = sorted(OUTPUT.glob('radar_*.tif'), key=lambda p: p.stat().st_mtime, reverse=True)
if not files:
    raise SystemExit('ERREUR : aucun TIFF radar_*.tif dans output/.')

tif = files[0]
png = DATA / 'radar-latest.png'
meta = DATA / 'radar-latest.json'
colors = DATA / 'radar-colors.txt'

print('TIFF sélectionné :', tif)

# Diagnostic GeoTIFF : projection, emprise, type et statistiques.
info_raw = subprocess.check_output([
    'gdalinfo', '-json', '-stats', str(tif)
], text=True)
info = json.loads(info_raw)

print('Taille raster :', info.get('size'))
print('Nombre de bandes :', len(info.get('bands', [])))
for band in info.get('bands', []):
    print(
        'Bande', band.get('band'),
        '- type:', band.get('type'),
        '- min:', band.get('minimum'),
        '- max:', band.get('maximum'),
        '- nodata:', band.get('noDataValue')
    )

# Palette de réflectivité dBZ. La première ligne rend les valeurs faibles transparentes.
colors.write_text('''nv 0 0 0 0\n-40 0 0 0 0\n-10 180 220 255 0\n0 120 190 255 90\n5 70 160 255 120\n10 30 120 255 145\n15 0 190 230 165\n20 0 200 150 180\n25 40 190 70 195\n30 130 210 40 210\n35 230 220 20 220\n40 255 175 0 230\n45 255 110 0 235\n50 245 40 20 240\n55 210 0 60 245\n60 180 0 140 250\n65 220 80 220 255\n75 255 255 255 255\n''', encoding='utf-8')

# Colorisation de la première bande du GeoTIFF et création directe d'un PNG RGBA.
subprocess.run([
    'gdaldem', 'color-relief',
    str(tif), str(colors), str(png),
    '-alpha', '-of', 'PNG'
], check=True)

# Emprise géographique fournie par GDAL, utile pour Leaflet.
cc = info.get('cornerCoordinates', {})
projection = info.get('coordinateSystem', {}).get('wkt', '')

metadata = {
    'source_tiff': tif.name,
    'png': png.name,
    'width': info.get('size', [None, None])[0],
    'height': info.get('size', [None, None])[1],
    'cornerCoordinates': cc,
    'projection_wkt': projection,
}
meta.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding='utf-8')

print('PNG créé :', png)
print('Métadonnées :', meta)
print('Taille PNG : %.2f Mo' % (png.stat().st_size / 1024 / 1024))
