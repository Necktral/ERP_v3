"""Lector tabular mínimo (.xlsx / .csv).

Mismo precedente que `planilla_export`: el proyecto no agrega librerías para
Office — el .xlsx se lee como lo que es (zip + XML). Cubre lo que exporta un
aparato biométrico: una hoja simple con encabezados y filas.

Limitación deliberada: .xls binario viejo NO se soporta (no es XML); el mensaje
de error pide re-guardarlo como .xlsx o .csv.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import datetime, timedelta

from defusedxml import ElementTree

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_ZIP_MEMBERS = 100
MAX_ZIP_MEMBER_BYTES = 16 * 1024 * 1024
MAX_ZIP_TOTAL_BYTES = 32 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 100
MAX_ROWS = 50_000
MAX_CELLS = 500_000
MAX_COLUMNS = 256
MAX_SHARED_STRINGS = 200_000

# Base de fechas seriales de Excel (sistema 1900, con su bug del 1900-02-29)
_EXCEL_EPOCH = datetime(1899, 12, 30)


class TabularReadError(ValueError):
    """Archivo ilegible o formato no soportado (mensaje apto para el usuario)."""


def _limit_error(detail: str) -> TabularReadError:
    return TabularReadError(f"El archivo excede los límites permitidos ({detail}).")


def _validate_zip(zf: zipfile.ZipFile) -> None:
    infos = zf.infolist()
    if len(infos) > MAX_ZIP_MEMBERS:
        raise _limit_error(f"máx {MAX_ZIP_MEMBERS} componentes ZIP")
    total_uncompressed = 0
    for info in infos:
        if info.flag_bits & 0x1:
            raise TabularReadError("El .xlsx no puede estar cifrado.")
        if info.file_size > MAX_ZIP_MEMBER_BYTES:
            raise _limit_error(f"componente ZIP mayor a {MAX_ZIP_MEMBER_BYTES // (1024 * 1024)} MB")
        total_uncompressed += info.file_size
        if total_uncompressed > MAX_ZIP_TOTAL_BYTES:
            raise _limit_error(f"contenido descomprimido mayor a {MAX_ZIP_TOTAL_BYTES // (1024 * 1024)} MB")
        if info.file_size and info.file_size / max(1, info.compress_size) > MAX_ZIP_COMPRESSION_RATIO:
            raise _limit_error(f"ratio ZIP mayor a {MAX_ZIP_COMPRESSION_RATIO}:1")


def _read_member_limited(zf: zipfile.ZipFile, name: str) -> bytes:
    try:
        stream = zf.open(name)
    except KeyError:
        raise
    chunks: list[bytes] = []
    total = 0
    with stream:
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_ZIP_MEMBER_BYTES:
                raise _limit_error(f"componente ZIP mayor a {MAX_ZIP_MEMBER_BYTES // (1024 * 1024)} MB")
            chunks.append(chunk)
    return b"".join(chunks)


def excel_serial_to_datetime(value: float) -> datetime:
    """Convierte un serial de Excel (días desde 1899-12-30) a datetime naive."""
    return _EXCEL_EPOCH + timedelta(days=float(value))


def _col_index(cell_ref: str) -> int:
    """'B3' -> 1 (índice de columna 0-based)."""
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch.upper()) - ord("A") + 1)
    return idx - 1


def _read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        data = _read_member_limited(zf, "xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ElementTree.fromstring(data)
    out: list[str] = []
    for si in root.findall("m:si", _NS):
        if len(out) >= MAX_SHARED_STRINGS:
            raise _limit_error(f"máx {MAX_SHARED_STRINGS} textos compartidos")
        # un <si> puede tener <t> directo o runs <r><t>
        text = "".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t"))
        out.append(text)
    return out


def _read_xlsx(content: bytes) -> list[list[str]]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise TabularReadError(
            "El archivo no es un .xlsx válido. Si el aparato exporta .xls viejo, "
            "abrilo y guardalo como .xlsx o .csv."
        ) from exc

    _validate_zip(zf)

    sheet_names = sorted(n for n in zf.namelist() if re.match(r"^xl/worksheets/sheet\d+\.xml$", n))
    if not sheet_names:
        raise TabularReadError("El .xlsx no contiene hojas legibles.")

    shared = _read_shared_strings(zf)
    root = ElementTree.fromstring(_read_member_limited(zf, sheet_names[0]))

    rows: list[list[str]] = []
    cell_count = 0
    for row_el in root.iter(f"{{{_NS['m']}}}row"):
        if len(rows) >= MAX_ROWS:
            raise _limit_error(f"máx {MAX_ROWS} filas")
        cells: dict[int, str] = {}
        for c in row_el.findall("m:c", _NS):
            cell_count += 1
            if cell_count > MAX_CELLS:
                raise _limit_error(f"máx {MAX_CELLS} celdas")
            ref = c.get("r") or ""
            idx = _col_index(ref) if ref else len(cells)
            if idx < 0 or idx >= MAX_COLUMNS:
                raise _limit_error(f"máx {MAX_COLUMNS} columnas")
            ctype = c.get("t") or "n"
            value = ""
            if ctype == "inlineStr":
                is_el = c.find("m:is", _NS)
                if is_el is not None:
                    value = "".join(t.text or "" for t in is_el.iter(f"{{{_NS['m']}}}t"))
            else:
                v = c.find("m:v", _NS)
                raw = v.text if v is not None and v.text is not None else ""
                if ctype == "s":
                    try:
                        value = shared[int(raw)]
                    except (ValueError, IndexError):
                        value = raw
                else:
                    value = raw
            cells[idx] = value.strip()
        if not cells:
            continue
        width = max(cells.keys()) + 1
        rows.append([cells.get(i, "") for i in range(width)])
    return rows


def _read_csv(content: bytes) -> list[list[str]]:
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - latin-1 nunca falla
        raise TabularReadError("No se pudo decodificar el archivo CSV.")

    sample = text[:2048]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows: list[list[str]] = []
    cell_count = 0
    for row in reader:
        if not any((cell or "").strip() for cell in row):
            continue
        if len(rows) >= MAX_ROWS:
            raise _limit_error(f"máx {MAX_ROWS} filas")
        if len(row) > MAX_COLUMNS:
            raise _limit_error(f"máx {MAX_COLUMNS} columnas")
        cell_count += len(row)
        if cell_count > MAX_CELLS:
            raise _limit_error(f"máx {MAX_CELLS} celdas")
        rows.append([(cell or "").strip() for cell in row])
    return rows


def read_tabular_file(file_name: str, content: bytes) -> list[list[str]]:
    """Devuelve las filas (lista de listas de str) de un .xlsx o .csv."""
    if len(content) > MAX_UPLOAD_BYTES:
        raise _limit_error(f"máx {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    name = (file_name or "").lower()
    if name.endswith(".xlsx"):
        return _read_xlsx(content)
    if name.endswith(".csv") or name.endswith(".txt"):
        return _read_csv(content)
    if name.endswith(".xls"):
        raise TabularReadError(
            "El formato .xls (Excel viejo) no se soporta: guardá el archivo como .xlsx o .csv."
        )
    # sin extensión clara: probar xlsx (zip) y caer a csv
    if content[:2] == b"PK":
        return _read_xlsx(content)
    return _read_csv(content)
