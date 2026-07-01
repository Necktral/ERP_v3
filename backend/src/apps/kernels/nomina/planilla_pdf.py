"""PDF de la planilla legal (HTML→PDF con WeasyPrint).

Comparte la fuente única `build_planilla_matrix` con el export .xlsx, así el PDF y el
Excel muestran exactamente las mismas casillas (incluido el SÉPTIMO DÍA).

`build_planilla_html` es Python puro (testeable sin dependencias del sistema);
`render_planilla_pdf` importa WeasyPrint de forma perezosa, porque requiere libs de
sistema (cairo/pango) que se instalan en la imagen (ver docker/backend.Dockerfile.*).
"""
from __future__ import annotations

from decimal import Decimal
from html import escape

from .planilla_export import ROWS_PER_PAGE, _col_width, build_planilla_matrix

# Papel Legal HORIZONTAL (como los Excel reales en /excel: paperSize 5, landscape). El pie
# "Hoja X de Y" deja el número de hoja impreso para que el pagador lo confronte con la app.
_PDF_CSS = """
@page {
  size: legal landscape;
  margin: 9mm 8mm 12mm;
  @bottom-right { content: "Hoja " counter(page) " de " counter(pages); font-size: 7px; color: #444; }
}
* { font-family: "DejaVu Sans", sans-serif; }
body { font-size: 7px; color: #111; }
h1 { font-size: 12px; margin: 0; text-align: center; }
.company { font-size: 10px; font-weight: bold; text-align: center; }
.subtitle { font-size: 8px; text-align: center; margin: 2px 0 6px; }
/* table-layout: fixed + colgroup (anchos reales) → cada columna ocupa su % exacto, el texto
   largo ENVUELVE dentro de la celda y NADA se desborda/recorta fuera de la hoja Legal. */
table { border-collapse: collapse; width: 100%; table-layout: fixed; }
thead { display: table-header-group; }
th, td { border: 0.4px solid #555; padding: 1px 2px; overflow-wrap: break-word; word-break: break-word; }
th { background: #e9e9e9; text-align: center; }
th.grp { background: #d2d2d2; }
td.num { text-align: right; }
tr { page-break-inside: avoid; }
tr.brk td { border-bottom: 0.6px solid #000; }
tr.totals td { font-weight: bold; background: #f2f2f2; }
.signatures { margin-top: 18px; width: 100%; }
.signatures td { border: none; text-align: center; padding-top: 22px; font-size: 8px; }
.sig-line { border-top: 0.6px solid #333; padding-top: 2px; }
"""

# Columnas cuyo valor es numérico (se alinean a la derecha y se formatean a 2 decimales).
_NUMERIC_KEYS = {
    "daily_rate_nio", "base_salary_nio", "quincenal_salary", "days_worked",
    "seventh_day_days", "days_subsidy", "subsidy_amount", "total_basico",
    "vacation_provision", "thirteenth_month_provision", "total_income",
    "inss_laboral", "ir_amount", "total_retencion_legal",
    "total_devengado", "neto_legal", "inss_patronal", "vacation_cost",
    "thirteenth_month_cost", "inatec", "total_payroll_cost",
    # CON INSS fiel
    "suma_dias", "dias_lab", "seventh_day_amount", "total_devengado_neto",
    "alimentacion_amount", "neto_pagar",
}


def _fmt(value: object) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, Decimal):
        return f"{value:,.2f}"
    return escape(str(value))


def _group_bands(columns: list[tuple[str, str, str]]) -> list[tuple[str, int]]:
    """Agrupa columnas consecutivas con el mismo grupo en bandas (grupo, colspan)."""
    bands: list[list] = []
    for _key, _label, group in columns:
        if bands and bands[-1][0] == group:
            bands[-1][1] += 1
        else:
            bands.append([group, 1])
    return [(g, n) for g, n in bands]


def build_planilla_html(sheet) -> str:
    """Documento HTML de la planilla legal a partir de la matriz compartida."""
    data = build_planilla_matrix(sheet)
    columns = data["columns"]
    rows = data["rows"]
    totals = data["totals"]

    # <colgroup>: cada columna toma su ancho REAL (del Excel de referencia) como % del total, así
    # con table-layout: fixed las proporciones son fieles y el contenido entra completo en la hoja.
    total_w = sum(_col_width(key) for key, _l, _g in columns) or 1.0
    colgroup = "".join(
        f'<col style="width:{_col_width(key) / total_w * 100:.3f}%"/>' for key, _l, _g in columns
    )

    band_row = "".join(
        f'<th class="grp" colspan="{n}">{escape(g)}</th>' for g, n in _group_bands(columns)
    )
    label_row = "".join(f"<th>{escape(label)}</th>" for _key, label, _g in columns)

    body = []
    for i, row in enumerate(rows, start=1):
        cells = []
        for key, _label, _g in columns:
            cls = ' class="num"' if key in _NUMERIC_KEYS else ""
            cells.append(f"<td{cls}>{_fmt(row.get(key))}</td>")
        # Salto determinista: cada ROWS_PER_PAGE filas cierra hoja, así "Hoja X, No. Y"
        # del Pagador (CO-PA) coincide con el papel (misma fuente: planilla_export.print_page).
        is_break = i % ROWS_PER_PAGE == 0 and i != len(rows)
        attrs = ' class="brk" style="page-break-after: always"' if is_break else ""
        body.append(f"<tr{attrs}>{''.join(cells)}</tr>")

    total_cells = []
    for idx, (key, _label, _g) in enumerate(columns):
        if key == "full_name":
            total_cells.append("<td>TOTALES</td>")
        elif key in totals:
            total_cells.append(f'<td class="num">{_fmt(totals[key])}</td>')
        else:
            total_cells.append("<td></td>")
    totals_row = f"<tr class='totals'>{''.join(total_cells)}</tr>"

    signatures = (
        "<table class='signatures'><tr>"
        "<td><div class='sig-line'>ELABORADO POR</div></td>"
        "<td><div class='sig-line'>REVISADO POR</div></td>"
        "<td><div class='sig-line'>AUTORIZADO POR</div></td>"
        "</tr></table>"
    )

    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<style>{_PDF_CSS}</style></head><body>"
        f"<div class='company'>{escape(data['company_name'])}</div>"
        f"<h1>{escape(data['title'])}</h1>"
        f"<div class='subtitle'>{escape(data['subtitle'])}</div>"
        f"<table><colgroup>{colgroup}</colgroup><thead><tr>{band_row}</tr><tr>{label_row}</tr></thead>"
        f"<tbody>{''.join(body)}{totals_row}</tbody></table>"
        f"{signatures}"
        "</body></html>"
    )


def render_planilla_pdf(sheet) -> bytes:
    """Renderiza la planilla a PDF. Requiere WeasyPrint + libs de sistema (cairo/pango)."""
    from weasyprint import HTML  # import perezoso: depende de libs del sistema

    return HTML(string=build_planilla_html(sheet)).write_pdf()
