import os
import io
import gzip
import json
import tarfile
import re
from pathlib import Path
from datetime import datetime, timezone

import requests

API_URL = (
    "https://public-api.meteofrance.fr/"
    "public/DPPaquetRadar/v1/mosaique/paquet"
)

API_KEY = os.environ.get("METEOFRANCE_RADAR_API_KEY")

OUTPUT_DIR = Path("data")
HISTORY_DIR = OUTPUT_DIR / "imfr27"
OUTPUT_DIR.mkdir(exist_ok=True)
HISTORY_DIR.mkdir(exist_ok=True)

BUFR_FILE = OUTPUT_DIR / "latest-imfr27.bufr"
INFO_FILE = OUTPUT_DIR / "latest-imfr27.json"
CANDIDATES_FILE = OUTPUT_DIR / "imfr27-candidates.json"

if not API_KEY:
    raise RuntimeError("Le secret METEOFRANCE_RADAR_API_KEY est absent.")

print("=====================================")
print("MÉTÉO WORLD - RADAR IMFR27")
print("=====================================")
print("Téléchargement du paquet radar...")

response = requests.get(
    API_URL,
    headers={
        "apikey": API_KEY,
        "Accept": "application/gzip",
    },
    timeout=120,
)
response.raise_for_status()
archive_data = response.content

print(f"Paquet téléchargé : {len(archive_data) / 1024 / 1024:.2f} Mo")

archive = io.BytesIO(archive_data)
pattern = re.compile(
    r"T_IMFR27_C_LFPW_(\d{14})\.bufr\.gz$",
    re.IGNORECASE
)

saved = []

with tarfile.open(fileobj=archive, mode="r:gz") as tar:
    candidates = []

    for member in tar.getmembers():
        if not member.isfile():
            continue

        filename = Path(member.name).name
        match = pattern.match(filename)

        if match:
            candidates.append((match.group(1), member, filename))

    candidates.sort(key=lambda item: item[0])

    print(f"Produits IMFR27 trouvés : {len(candidates)}")

    if not candidates:
        raise RuntimeError("Aucun produit IMFR27 trouvé.")

    # On garde les 24 derniers produits du paquet (jusqu'à 2 h à 5 min).
    recent = candidates[-24:]

    for timestamp, member, filename in recent:
        extracted = tar.extractfile(member)
        if extracted is None:
            continue

        compressed_bufr = extracted.read()
        bufr_data = gzip.decompress(compressed_bufr)

        if not bufr_data.startswith(b"BUFR"):
            print("Ignoré, signature BUFR invalide :", filename)
            continue

        dt = datetime.strptime(timestamp, "%Y%m%d%H%M%S").replace(
            tzinfo=timezone.utc
        )

        short_name = f"imfr27-{dt.strftime('%Y%m%d-%H%M')}.bufr"
        target = HISTORY_DIR / short_name
        target.write_bytes(bufr_data)

        saved.append({
            "timestamp": timestamp,
            "datetime": dt.isoformat().replace("+00:00", "Z"),
            "source_file": filename,
            "bufr_file": str(target),
            "size_bytes": len(bufr_data),
        })

        print("IMFR27 disponible :", dt.isoformat().replace("+00:00", "Z"))

if not saved:
    raise RuntimeError("Aucun IMFR27 valide n'a pu être extrait.")

latest = saved[-1]
latest_path = Path(latest["bufr_file"])
BUFR_FILE.write_bytes(latest_path.read_bytes())

info = {
    "product": "IMFR27",
    "source_file": latest["source_file"],
    "observation_time_utc": latest["datetime"],
    "bufr_file": BUFR_FILE.name,
    "bufr_size_bytes": latest["size_bytes"],
    "updated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
}

INFO_FILE.write_text(
    json.dumps(info, indent=2, ensure_ascii=False),
    encoding="utf-8",
)

CANDIDATES_FILE.write_text(
    json.dumps(saved, indent=2, ensure_ascii=False),
    encoding="utf-8",
)

print()
print("Dernier produit :", latest["source_file"])
print("Date radar :", latest["datetime"])
print("Produits récents extraits :", len(saved))
print("=====================================")
print("EXTRACTION IMFR27 TERMINÉE")
print("=====================================")
