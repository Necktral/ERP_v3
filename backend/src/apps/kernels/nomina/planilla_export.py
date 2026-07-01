"""Export de la planilla legal (norma INSS) — reproduce TODAS las casillas en .xlsx.

Genera el .xlsx por OOXML crudo (zipfile + XML), sin dependencias nuevas, igual que
`apps.kernels.reporting.exports`. Reproduce la planilla legal con: bloque de título,
encabezados AGRUPADOS (INGRESOS / RETENCIONES / COSTOS PATRONALES) con celdas
combinadas, una fila por empleado con cada casilla (incluido el SÉPTIMO DÍA), fila de
totales, y firmas (ELABORADO / REVISADO / AUTORIZADO).

El PDF (WeasyPrint) se construye aparte (requiere dependencia + imagen); este módulo
expone `build_planilla_matrix` para que ambos formatos compartan la misma fuente.
"""
from __future__ import annotations

from decimal import Decimal
from html import escape as xml_escape
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

# Filas de empleado por HOJA de la planilla impresa (papel Legal, horizontal — como los
# Excel reales en /excel). Es la fuente ÚNICA de la paginación: el PDF fuerza el salto cada
# ROWS_PER_PAGE filas y la app del Pagador (CO-PA) calcula la MISMA hoja con `print_page`,
# así "Hoja 2, No. 34" coincide con el papel. Ajustable si cambia el papel/escala.
ROWS_PER_PAGE = 30


def print_page(no: int) -> int:
    """Hoja (1-indexada) donde cae el trabajador No. `no` en la planilla impresa."""
    if no <= 0:
        return 1
    return (no - 1) // ROWS_PER_PAGE + 1

# --------------------------------------------------------------------------- #
# Planilla CON INSS — FIEL al Excel (layout + grilla de asistencia día-por-día)
# --------------------------------------------------------------------------- #
# Reproduce las columnas/nombres/orden del Excel `COMISARIATO CON INSS`, con la grilla de días
# del período (domingos marcados). Los NÚMEROS son legales (los del sistema): no se replican las
# fórmulas raras del Excel. NO incluye FINCA ni cobros internos (eso es lógica del CO-PA, no del
# documento legal). ALIMENTOS = alimentación de la empresa: SUMA al neto (beneficio, no descuento).

_DOW_LETTER = ["L", "M", "M", "J", "V", "S", "D"]  # lunes..domingo (weekday(): lun=0)


def _period_dates(period) -> list:
    out, d = [], period.start_date
    while d <= period.end_date:
        out.append(d)
        d = d + __import__("datetime").timedelta(days=1)
    return out


def _entry_day_marks(entry, period) -> dict:
    """Marcas día-por-día de la línea: la captura manual (`daily_attendance`) o, si está vacía,
    se reconstruye de la consolidación de cuadrilla (campo). Devuelve {iso_date: código}."""
    if entry.daily_attendance:
        return {str(k): str(v).strip().upper() for k, v in entry.daily_attendance.items()}
    if not entry.employee_id:
        return {}
    try:
        from .models import FieldAttendanceConsolidation, FieldAttendanceConsolidationStatus, FieldWorkerEventType
    except ImportError:
        return {}
    marks: dict = {}
    rows = FieldAttendanceConsolidation.objects.filter(
        payroll_period=period, employee_id=entry.employee_id,
        status__in=[FieldAttendanceConsolidationStatus.APPROVED, FieldAttendanceConsolidationStatus.LOCKED_FOR_PAYROLL],
    ).select_related("work_day")
    for c in rows:
        iso = c.work_day.work_date.isoformat()
        if c.primary_event_type == FieldWorkerEventType.ABSENT:
            marks[iso] = "A"
        elif c.day_value and Decimal(str(c.day_value)) >= Decimal("1"):
            marks[iso] = "P"
        elif c.day_value and Decimal(str(c.day_value)) > 0:
            marks[iso] = "M"
        else:
            marks[iso] = "A"
    return marks


def _con_inss_columns(period) -> list[tuple[str, str, str]]:
    cols: list[tuple[str, str, str]] = [
        ("no", "No.", ""),
        ("base_salary_nio", "Salario", ""),
        ("full_name", "Nombres y Apellidos", ""),
        ("gender", "Género", ""),
        ("daily_rate_nio", "Salario Diario", ""),
        ("cargo", "Actividad", ""),
    ]
    for d in _period_dates(period):
        cols.append((f"day_{d.isoformat()}", f"{d.day} {_DOW_LETTER[d.weekday()]}", "ASISTENCIA"))
    cols += [
        ("suma_dias", "Suma Días", ""),
        ("dias_lab", "Días Lab", ""),
        ("quincenal_salary", "Salario Básico", "INGRESOS"),
        ("seventh_day_amount", "Sept Día", "INGRESOS"),
        ("total_basico", "TOTAL", "INGRESOS"),
        ("vacation_provision", "Vacaciones", "INGRESOS"),
        ("thirteenth_month_provision", "13vo Mes", "INGRESOS"),
        ("total_income", "Total Ingresos", "INGRESOS"),
        ("inss_laboral", "INSS", "RETENCIONES"),
        ("ir_amount", "IR", "RETENCIONES"),
        ("total_devengado_neto", "Total Devengado", ""),
        ("alimentacion_amount", "Alimentos", ""),
        ("neto_pagar", "Total a Pagar", ""),
        ("recibi_conforme", "Recibe Conforme", ""),
    ]
    return cols


_CON_INSS_TOTALED = {
    "suma_dias", "dias_lab", "quincenal_salary", "seventh_day_amount", "total_basico",
    "vacation_provision", "thirteenth_month_provision", "total_income", "inss_laboral",
    "ir_amount", "total_devengado_neto", "alimentacion_amount", "neto_pagar",
}


def _con_inss_row(entry, index: int, period) -> dict[str, object]:
    """Fila CON INSS con números LEGALES + la grilla de días. Total a Pagar = devengado neto
    (cash − INSS/IR) + ALIMENTOS (beneficio que suma)."""
    total_basico = (entry.quincenal_salary or Decimal("0")) + (entry.seventh_day_amount or Decimal("0")) + (
        entry.holiday_amount or Decimal("0")
    )
    retencion = (entry.inss_laboral or Decimal("0")) + (entry.ir_amount or Decimal("0"))
    devengado_neto = (entry.total_devengado or Decimal("0")) - retencion
    alimentos = entry.alimentacion_amount or Decimal("0")
    row: dict[str, object] = {
        "no": index,
        "base_salary_nio": entry.base_salary_nio,
        "full_name": entry.full_name,
        "gender": entry.gender,
        "daily_rate_nio": entry.daily_rate_nio,
        "cargo": entry.cargo,
        "suma_dias": (entry.days_worked or Decimal("0")) + (entry.seventh_day_days or Decimal("0")),
        "dias_lab": entry.days_worked,
        "quincenal_salary": entry.quincenal_salary,
        "seventh_day_amount": entry.seventh_day_amount,
        "total_basico": total_basico,
        "vacation_provision": entry.vacation_provision,
        "thirteenth_month_provision": entry.thirteenth_month_provision,
        "total_income": entry.total_income,
        "inss_laboral": entry.inss_laboral,
        "ir_amount": entry.ir_amount,
        "total_devengado_neto": devengado_neto,
        "alimentacion_amount": alimentos,
        "neto_pagar": devengado_neto + alimentos,
        "recibi_conforme": "",
    }
    marks = _entry_day_marks(entry, period)
    for d in _period_dates(period):
        row[f"day_{d.isoformat()}"] = marks.get(d.isoformat(), "")
    return row


# --------------------------------------------------------------------------- #
# Planilla SIN INSS — FIEL al Excel "COMISARIATO SIN INSS"
# --------------------------------------------------------------------------- #
# Más simple que la CON INSS: SIN grilla de días y SIN columnas de INSS/IR ni costos patronales
# (en SIN INSS el INSS es 0 y la patronal no aplica → el Excel real los oculta). El IR, si aplica,
# se RESTA del total aunque no se muestre. ALIMENTACIÓN = beneficio de la empresa: SUMA al neto.
# NO lleva Cédula/No.INSS visibles ni FINCA/COMISARIATO (eso es lógica del CO-PA, no del documento).

_SIN_INSS_COLUMNS: list[tuple[str, str, str]] = [
    ("no", "No.", ""),
    ("full_name", "Nombres y Apellidos", ""),
    ("gender", "Género", ""),
    ("cargo", "Cargo", ""),
    ("daily_rate_nio", "Salario Diario", ""),
    ("base_salary_nio", "Salario Mensual", ""),
    ("quincenal_salary", "Salario Quincenal", "INGRESOS"),
    ("days_worked", "Días Laborados", "INGRESOS"),
    ("total_basico", "Total Básico", "INGRESOS"),
    ("vacation_provision", "Vacaciones", "INGRESOS"),
    ("thirteenth_month_provision", "13vo Mes", "INGRESOS"),
    ("total_income", "Total Ingresos", "INGRESOS"),
    ("alimentacion_amount", "Alimentación", ""),
    ("neto_pagar", "Total a Pagar", ""),
    ("recibi_conforme", "Recibí Conforme", ""),
]

_SIN_INSS_TOTALED = {
    "quincenal_salary", "days_worked", "total_basico", "vacation_provision",
    "thirteenth_month_provision", "total_income", "alimentacion_amount", "neto_pagar",
}


def _sin_inss_row(entry, index: int) -> dict[str, object]:
    """Fila SIN INSS fiel: números LEGALES. Total a Pagar = devengado − (INSS+IR) + ALIMENTOS.
    (En SIN INSS el INSS es 0; el IR se resta aunque no tenga columna propia.)"""
    total_basico = (entry.quincenal_salary or Decimal("0")) + (entry.seventh_day_amount or Decimal("0")) + (
        entry.holiday_amount or Decimal("0")
    )
    retencion = (entry.inss_laboral or Decimal("0")) + (entry.ir_amount or Decimal("0"))
    devengado_neto = (entry.total_devengado or Decimal("0")) - retencion
    alimentos = entry.alimentacion_amount or Decimal("0")
    return {
        "no": index,
        "full_name": entry.full_name,
        "gender": entry.gender,
        "cargo": entry.cargo,
        "daily_rate_nio": entry.daily_rate_nio,
        "base_salary_nio": entry.base_salary_nio,
        "quincenal_salary": entry.quincenal_salary,
        "days_worked": entry.days_worked,
        "total_basico": total_basico,
        "vacation_provision": entry.vacation_provision,
        "thirteenth_month_provision": entry.thirteenth_month_provision,
        "total_income": entry.total_income,
        "alimentacion_amount": alimentos,
        "neto_pagar": devengado_neto + alimentos,
        "recibi_conforme": "",
    }


def build_planilla_matrix(sheet) -> dict:
    """Fuente común (xlsx/PDF): título, columnas, filas por empleado y totales.

    CON INSS → layout fiel al Excel + grilla de días. SIN INSS → layout fiel SIN INSS (sin grilla,
    sin INSS/IR/patronal, con Alimentación).
    """
    period = sheet.period
    company = period.company
    entries = list(sheet.entries.select_related("employee").order_by("id"))

    if sheet.has_inss:
        columns = _con_inss_columns(period)
        totaled = _CON_INSS_TOTALED
        rows = [_con_inss_row(e, i, period) for i, e in enumerate(entries, start=1)]
    else:
        columns = _SIN_INSS_COLUMNS
        totaled = _SIN_INSS_TOTALED
        rows = [_sin_inss_row(e, i) for i, e in enumerate(entries, start=1)]

    totals = {key: Decimal("0.00") for key in totaled}
    for row in rows:
        for key in totaled:
            totals[key] += Decimal(str(row.get(key) or "0"))

    inss_label = "CON INSS" if sheet.has_inss else "SIN INSS"
    return {
        "company_name": str(company),
        "title": "PLANILLA DE SALARIO",
        "subtitle": f"{sheet.sheet_name} [{inss_label}] — {period.year}/{period.month:02d} {period.period_type}",
        "columns": columns,
        "rows": rows,
        "totals": totals,
    }


def _col_letter(col_index: int) -> str:
    letters: list[str] = []
    n = col_index
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters.append(chr(65 + rem))
    return "".join(reversed(letters))


# Anchos REALES (caracteres de Excel) leídos del Excel de referencia /excel, hoja
# "COMISARIATO CON INSS": cada columna del documento legal con su medida fiel para que NADA se
# corte al imprimir en hoja Legal horizontal. Es la fuente ÚNICA del ancho: la usa el .xlsx
# (atributo width) y el PDF (porcentaje de columna en table-layout: fixed).
_COL_WIDTHS: dict[str, float] = {
    # Identidad / encabezado
    "no": 3.4,                          # "No."
    "inss_number": 7.4,                 # "No. INSS"
    "cedula": 8.0,
    "base_salary_nio": 7.1,             # "SALARIO"
    "full_name": 24.7,                  # "NOMBRES Y APELLIDOS"
    "gender": 4.9,                      # "GENERO"
    "daily_rate_nio": 7.1,             # "SALARIO DIARIO"
    "cargo": 8.7,                       # "Actividad"
    # Cálculo / ingresos (CON INSS fiel)
    "suma_dias": 5.0,
    "dias_lab": 4.9,                    # "DIAS TRAB"
    "days_worked": 4.9,
    "seventh_day_days": 5.0,
    "days_subsidy": 5.0,
    "subsidy_amount": 8.0,
    "quincenal_salary": 8.3,            # "SALARIO BASICO"
    "seventh_day_amount": 9.1,          # "SEPT DIA"
    "total_basico": 9.9,                # "TOTAL"
    "vacation_provision": 8.4,          # "VACASIONES"
    "thirteenth_month_provision": 8.7,  # "13VO MES"
    "total_income": 9.4,                # "TOTAL INGRESOS"
    # Retenciones
    "inss_laboral": 8.4,                # "INSS LAB"
    "ir_amount": 7.0,
    "total_retencion_legal": 8.4,
    # Neto
    "total_devengado": 9.7,             # "TOTAL DEVENGADO"
    "total_devengado_neto": 9.7,
    "neto_legal": 12.0,
    "alimentacion_amount": 8.0,         # "ALIMENTACION" (ensanchado para el monto)
    "neto_pagar": 12.0,                 # "NETO A PAGAR"
    "recibi_conforme": 20.0,            # "RECIBIDO CONFORME" (línea de firma; original 33.4)
    # Costos patronales (layout SIN INSS / legal)
    "inss_patronal": 12.0,              # "INSS PATRONAL"
    "vacation_cost": 8.4,
    "thirteenth_month_cost": 6.4,
    "inatec": 7.1,                      # "INATEC"
    "total_payroll_cost": 10.4,         # "GASTOS NOMINA"
}


def _col_width(key: str) -> float:
    """Ancho REAL de la columna (caracteres de Excel) según el Excel de referencia. La grilla de
    días lleva la marca de UN carácter (P/M/D…) + el encabezado "DD L" → 5.0 basta y no se corta.
    Default 9.0 para claves sin medida propia."""
    if key.startswith("day_"):
        return 5.0
    return _COL_WIDTHS.get(key, 9.0)


def _cell(ref: str, value: object) -> str:
    text = xml_escape("" if value is None else str(value))
    return f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'


def render_planilla_xlsx(sheet) -> bytes:
    """Genera el .xlsx legal con encabezados agrupados (celdas combinadas) + totales + firmas."""
    data = build_planilla_matrix(sheet)
    cols = data["columns"]
    ncols = len(cols)
    xml_rows: list[str] = []
    merges: list[str] = []

    def row_xml(r: int, cells: list[str]) -> None:
        xml_rows.append(f'<row r="{r}">{"".join(cells)}</row>')

    # Título (filas 1-3), combinadas sobre todo el ancho
    last_col = _col_letter(ncols)
    row_xml(1, [_cell("A1", data["company_name"])])
    row_xml(2, [_cell("A2", data["title"])])
    row_xml(3, [_cell("A3", data["subtitle"])])
    for r in (1, 2, 3):
        merges.append(f'<mergeCell ref="A{r}:{last_col}{r}"/>')

    # Fila 5: encabezados de GRUPO (combinados por rango contiguo del mismo grupo)
    group_cells: list[str] = []
    i = 0
    while i < ncols:
        grp = cols[i][2]
        j = i
        while j + 1 < ncols and cols[j + 1][2] == grp and grp:
            j += 1
        if grp:
            ref = _col_letter(i + 1)
            group_cells.append(_cell(f"{ref}5", grp))
            if j > i:
                merges.append(f'<mergeCell ref="{ref}5:{_col_letter(j + 1)}5"/>')
        i = j + 1
    row_xml(5, group_cells)

    # Fila 6: encabezados de columna
    row_xml(6, [_cell(f"{_col_letter(c + 1)}6", label) for c, (_k, label, _g) in enumerate(cols)])

    # Filas de datos
    r = 7
    for row in data["rows"]:
        row_xml(r, [_cell(f"{_col_letter(c + 1)}{r}", row.get(key, "")) for c, (key, _l, _g) in enumerate(cols)])
        r += 1

    # Fila de TOTALES
    total_cells: list[str] = [_cell(f"A{r}", "TOTALES")]
    for c, (key, _l, _g) in enumerate(cols):
        if key in data["totals"]:
            total_cells.append(_cell(f"{_col_letter(c + 1)}{r}", data["totals"][key]))
    row_xml(r, total_cells)

    # Firmas
    r += 3
    row_xml(r, [
        _cell("A" + str(r), "ELABORADO"),
        _cell("E" + str(r), "REVISADO"),
        _cell("I" + str(r), "AUTORIZADO"),
    ])

    merge_xml = f'<mergeCells count="{len(merges)}">{"".join(merges)}</mergeCells>' if merges else ""
    # Anchos de columna FIELES al Excel de referencia (hoja Legal horizontal) → nada se corta.
    col_defs = "".join(
        f'<col min="{c + 1}" max="{c + 1}" width="{_col_width(key):g}" customWidth="1"/>'
        for c, (key, _l, _g) in enumerate(cols)
    )
    cols_xml = f"<cols>{col_defs}</cols>" if col_defs else ""
    # Tamaño de impresión: hoja LEGAL/oficio (paperSize 5) HORIZONTAL, ajustada al ancho
    # (fitToWidth=1, fitToHeight=0) como los Excel reales de /excel. Así toda la planilla
    # —incluida la grilla de días de la CON INSS— entra en UNA hoja de ancho y las filas
    # fluyen a las hojas que hagan falta hacia abajo. El orden de los elementos respeta el
    # esquema OOXML (sheetPr → cols → sheetData → mergeCells → pageMargins → pageSetup).
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetPr><pageSetUpPr fitToPage="1"/></sheetPr>'
        f"{cols_xml}"
        f"<sheetData>{''.join(xml_rows)}</sheetData>"
        f"{merge_xml}"
        # Márgenes reales del Excel de referencia (izq/der=0 para aprovechar todo el ancho).
        '<pageMargins left="0" right="0" top="0.748" bottom="0.748" header="0.315" footer="0.315"/>'
        '<pageSetup paperSize="5" orientation="landscape" fitToWidth="1" fitToHeight="0"/>'
        "</worksheet>"
    )
    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Planilla" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )
    workbook_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )
    buffer = BytesIO()
    with ZipFile(buffer, mode="w", compression=ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("_rels/.rels", rels_xml)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buffer.getvalue()
