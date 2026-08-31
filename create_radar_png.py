import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

OUTPUT = Path('output')
DATA = Path('data')
DATA.mkdir(exist_ok=True)

files = sorted(OUTPUT.glob('radar_*.tif'), key=lambda p: p.stat().st_mtime, reverse=True)
if not files:
    raise SystemExit('ERREUR : aucun TIFF radar_*.tif dans output/.')

source_tif = files[0]
warped_tif = OUTPUT / 'radar-latest-4326.tif'
raw_bin = DATA / 'radar-values.bin'
png = DATA / 'radar-latest.png'
meta = DATA / 'radar-latest.json'

print('TIFF source :', source_tif)

# Reprojection vers EPSG:4326 avant création du PNG pour que Leaflet puisse
# utiliser un simple imageOverlay rectangulaire sans décalage géographique.
subprocess.run([
    'gdalwarp', '-q', '-overwrite',
    '-t_srs', 'EPSG:4326',
    '-r', 'near',
    '-dstnodata', '-9999',
    '-multi', '-wo', 'NUM_THREADS=ALL_CPUS',
    str(source_tif), str(warped_tif)
], check=True)

info = json.loads(subprocess.check_output(['gdalinfo', '-json', '-stats', str(warped_tif)], text=True))
width, height = info['size']
band = info['bands'][0]

print('Raster reprojeté :', warped_tif)
print('Taille raster :', info['size'])
print('Projection : EPSG:4326')
print('Bande 1 - type:', band.get('type'), '- min:', band.get('minimum'), '- max:', band.get('maximum'), '- nodata:', band.get('noDataValue'))

subprocess.run([
    'gdal_translate', '-q', '-b', '1', '-of', 'ENVI', '-ot', 'Float32',
    str(warped_tif), str(raw_bin)
], check=True)

values = np.fromfile(raw_bin, dtype=np.float32)
if values.size != width * height:
    raise SystemExit(f'ERREUR : taille raster inattendue ({values.size} au lieu de {width * height}).')
values = values.reshape((height, width))

finite = np.isfinite(values)
nodata = band.get('noDataValue')
if nodata is not None:
    finite &= values != float(nodata)

levels = np.array([0,5,10,15,20,25,30,35,40,45,50,55,60,65,75], dtype=np.float32)
palette = np.array([
    [120,190,255,80], [70,160,255,110], [30,120,255,140],
    [0,190,230,165], [0,200,150,180], [40,190,70,195],
    [130,210,40,210], [230,220,20,220], [255,175,0,230],
    [255,110,0,235], [245,40,20,240], [210,0,60,245],
    [180,0,140,250], [220,80,220,255], [255,255,255,255]
], dtype=np.uint8)

rgba = np.zeros((height, width, 4), dtype=np.uint8)
echo = finite & (values >= 0.0)
idx = np.searchsorted(levels, values, side='right') - 1
idx = np.clip(idx, 0, len(palette)-1)
rgba[echo] = palette[idx[echo]]
Image.fromarray(rgba, mode='RGBA').save(png, optimize=True)

cc = info.get('cornerCoordinates', {})
upper_left = cc.get('upperLeft')
lower_right = cc.get('lowerRight')
if not upper_left or not lower_right:
    raise SystemExit('ERREUR : coordonnées du raster reprojeté introuvables.')

west, north = map(float, upper_left)
east, south = map(float, lower_right)

metadata = {
    'source_tiff': source_tif.name,
    'reprojected_tiff': warped_tif.name,
    'png': png.name,
    'projection': 'EPSG:4326',
    'width': width,
    'height': height,
    'bounds': {'south': south, 'west': west, 'north': north, 'east': east},
    'display_min_dbz': 0,
    'transparent_below_dbz': 0,
    'reflectivity_min_dbz': band.get('minimum'),
    'reflectivity_max_dbz': band.get('maximum'),
}
meta.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding='utf-8')

for p in (raw_bin, raw_bin.with_suffix('.hdr'), Path(str(raw_bin) + '.aux.xml')):
    try:
        p.unlink()
    except FileNotFoundError:
        pass

print('Pixels radar visibles :', int(echo.sum()))
print('Pixels transparents :', int((~echo).sum()))
print('Bounds Leaflet :', metadata['bounds'])
print('PNG créé :', png)
print('Métadonnées :', meta)
print('Taille PNG : %.2f Mo' % (png.stat().st_size / 1024 / 1024))
