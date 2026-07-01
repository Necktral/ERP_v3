"""Recibo imprimible 'COMPLEMENTO DE SALARIO' (HTML → PDF con WeasyPrint).

Calca la hoja de complemento de los Excel: No | Nombre | Devengado | Neto a pagar | Recibido
conforme, con subtotal. Devengado = neto (bruto en recibo, sin deducciones).

`build_complement_recibo_html` es Python puro (testeable sin dependencias del sistema);
`render_complement_recibo_pdf` importa WeasyPrint de forma perezosa y degrada a RuntimeError
si faltan las libs nativas (cairo/pango), para que el endpoint responda 503 limpio en vez de
500 (en CI/producción la imagen del Dockerfile sí trae las libs).
"""
from __future__ import annotations

from decimal import Decimal
from html import escape

_CSS = """
@page { size: A4 portrait; margin: 14mm 12mm; }
* { font-family: "DejaVu Sans", sans-serif; }
body { font-size: 9px; color: #111; }
.company { font-size: 12px; font-weight: bold; text-align: center; }
h1 { font-size: 12px; margin: 2px 0; text-align: center; }
.subtitle { font-size: 9px; text-align: center; margin: 2px 0 8px; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 0.5px solid #555; padding: 2px 4px; }
th { background: #e9e9e9; text-align: center; }
td.num { text-align: right; }
td.sig { text-align: center; }
tr.totals td { font-weight: bold; background: #f2f2f2; }
"""


def _money(v) -> str:
    return f"{Decimal(v).quantize(Decimal('0.01')):,.2f}"


def build_complement_recibo_html(sheet) -> str:
    """HTML del recibo. Python puro — no depende de WeasyPrint."""
    period = sheet.period
    company_name = getattr(getattr(period, "company", None), "name", "") or ""
    lines = list(sheet.lines.order_by("full_name", "id"))
    subtotal = sum((ln.amount_nio for ln in lines), Decimal("0.00"))

    rows = []
    for i, ln in enumerate(lines, start=1):
        rows.append(
            f"<tr><td>{i}</td><td>{escape(ln.full_name)}</td>"
            f"<td class='num'>{_money(ln.amount_nio)}</td>"
            f"<td class='num'>{_money(ln.amount_nio)}</td>"
            f"<td class='sig'></td></tr>"
        )
    body = "".join(rows) or "<tr><td colspan='5'>Sin líneas</td></tr>"
    title = sheet.name or "COMPLEMENTO DE SALARIO"
    subtitle = ""
    if getattr(period, "start_date", None) and getattr(period, "end_date", None):
        subtitle = f"DEL {period.start_date:%d/%m/%Y} AL {period.end_date:%d/%m/%Y}"

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>{_CSS}</style></head><body>
<div class="company">{escape(company_name)}</div>
<h1>COMPLEMENTO DE SALARIO</h1>
<div class="subtitle">{escape(title)} {escape(subtitle)}</div>
<table>
<thead><tr><th>No.</th><th>NOMBRES Y APELLIDOS</th><th>DEVENGADO</th><th>NETO A PAGAR</th><th>RECIBIDO CONFORME</th></tr></thead>
<tbody>
{body}
<tr class="totals"><td colspan="2">Subtotal</td><td class="num">{_money(subtotal)}</td><td class="num">{_money(subtotal)}</td><td></td></tr>
</tbody>
</table>
</body></html>"""


def render_complement_recibo_pdf(sheet) -> bytes:
    """Renderiza el recibo a PDF. Requiere WeasyPrint + libs de sistema (cairo/pango);
    si faltan, levanta RuntimeError (el endpoint lo traduce a 503)."""
    try:
        from weasyprint import HTML  # import perezoso: depende de libs del sistema

        return HTML(string=build_complement_recibo_html(sheet)).write_pdf()
    except (ImportError, OSError) as exc:
        raise RuntimeError(f"Render PDF no disponible (WeasyPrint/libs nativas): {exc}") from exc
