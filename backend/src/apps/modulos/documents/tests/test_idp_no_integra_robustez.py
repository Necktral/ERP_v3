"""ROBUSTEZ del invariante DURO de IDP: "EXTRAER JAMÁS INTEGRA".

La extracción de un documento (PDF/remisión/factura) produce datos extraídos
(borrador EXTRACTED) pero NUNCA crea ni modifica objetos de negocio por sí sola:
- 0 JournalEntry (contabilidad)
- 0 StockMovement (inventario)
- 0 BillingDocument (facturación)
- `linked_object_*` queda VACÍO hasta la integración (F4), que es posterior y manual.

También: entrada basura (texto que parece factura, montos europeos, cédula sin
etiqueta, doc rezagado) → borrador con confianzas, sin tocar nada de negocio y sin 500.
Y la máquina de estados: solo PROCESSED → EXTRACTED; extraer fuera de PROCESSED es
error de negocio (ValueError → 409), no crash.
"""
from __future__ import annotations

import uuid

import pytest
from django.contrib.auth import get_user_model

from apps.kernels.accounting.models import JournalEntry
from apps.kernels.facturacion.models import BillingDocument
from apps.kernels.inventarios.models import StockMovement
from apps.modulos.documents import ocr as ocr_module
from apps.modulos.documents.models import DocumentType, ScannedDocument, ScanStatus
from apps.modulos.documents.services import (
    create_scanned_document,
    extract_fields_on_document,
    process_pending_documents,
    process_pending_extractions,
)
from apps.modulos.iam.models import OrgUnit

User = get_user_model()
UT = OrgUnit.UnitType

_FACTURA = """COMERCIAL EL CAFETAL S.A.
RUC: J0310000003457
FACTURA No. 0012345
Fecha: 15/05/2026
Quintal de fertilizante     2,500.00
SUBTOTAL                    2,850.00
TOTAL C$                    3,277.50
"""

_REMISION = """GUIA DE REMISION No. 000789
Fecha: 20/05/2026
Origen: Finca El Porvenir
Destino: Beneficio Central
Producto: Café pergamino oreado
45 quintales
"""


def _company() -> OrgUnit:
    t = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=UT.HOLDING, name=f"H{t}", code=f"H-{t}")
    return OrgUnit.objects.create(unit_type=UT.COMPANY, parent=holding, name=f"C{t}", code=f"C-{t}")


def _doc(company, *, ocr_text, doc_type=DocumentType.GENERAL):
    doc = create_scanned_document(
        company=company, branch=None, doc_type=doc_type, raw_bytes=b"img", content_type="image/png"
    )
    doc.ocr_text = ocr_text
    doc.status = ScanStatus.PROCESSED
    doc.save(update_fields=["ocr_text", "status", "updated_at"])
    return doc


def _business_counts():
    return (
        JournalEntry.objects.count(),
        StockMovement.objects.count(),
        BillingDocument.objects.count(),
    )


# --------------------------------------------------------------------------- #
# INVARIANTE DURO: extraer no crea NADA de negocio
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
def test_extraer_factura_no_crea_objetos_de_negocio():
    company = _company()
    before = _business_counts()
    doc = _doc(company, ocr_text=_FACTURA, doc_type=DocumentType.INVOICE)
    doc = extract_fields_on_document(doc)
    # El borrador SÍ trae campos…
    assert doc.status == ScanStatus.EXTRACTED
    assert doc.extracted_fields["fields"]["total"]["value"] == "3277.50"
    # …pero CERO efecto en los kernels de negocio.
    assert _business_counts() == before
    assert doc.linked_object_type == ""
    assert doc.linked_object_id == ""


@pytest.mark.django_db
def test_extraer_remision_no_mueve_inventario():
    """Una remisión = movimiento entre fincas/bodegas. Extraerla NO debe generar
    StockMovement: el inventario solo se mueve tras la integración humana (F4)."""
    company = _company()
    before = _business_counts()
    doc = _doc(company, ocr_text=_REMISION, doc_type=DocumentType.REMISION)
    doc = extract_fields_on_document(doc)
    assert doc.extracted_fields["fields"]["cantidad"]["value"] == "45"
    assert StockMovement.objects.count() == before[1]
    assert _business_counts() == before
    assert doc.linked_object_type == ""


@pytest.mark.django_db
def test_batch_ocr_mas_extraccion_no_crea_negocio(monkeypatch):
    """El batch encadena OCR + extracción para varios documentos a la vez y aun así
    no toca ningún kernel de negocio."""
    monkeypatch.setattr(ocr_module, "run_ocr", lambda _b: _FACTURA)
    company = _company()
    before = _business_counts()
    for _ in range(3):
        create_scanned_document(company=company, branch=None, doc_type=DocumentType.INVOICE, raw_bytes=b"img")
    assert process_pending_documents() == 3
    assert ScannedDocument.objects.filter(status=ScanStatus.EXTRACTED).count() == 3
    assert _business_counts() == before  # extraer en lote tampoco integra


@pytest.mark.django_db
def test_batch_rezagados_no_crea_negocio():
    company = _company()
    before = _business_counts()
    _doc(company, ocr_text=_REMISION, doc_type=DocumentType.REMISION)
    assert process_pending_extractions() == 1
    assert _business_counts() == before
    assert not ScannedDocument.objects.exclude(linked_object_type="").exists()


# --------------------------------------------------------------------------- #
# MÁQUINA DE ESTADOS + ENTRADA BASURA (sin 500)
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
def test_extraer_fuera_de_processed_es_error_de_negocio_no_crash():
    company = _company()
    doc = create_scanned_document(
        company=company, branch=None, doc_type=DocumentType.GENERAL, raw_bytes=b"img"
    )  # PENDING_OCR
    with pytest.raises(ValueError):
        extract_fields_on_document(doc)  # 409 en la vista, no 500
    # No avanzó de estado ni integró.
    doc.refresh_from_db()
    assert doc.status == ScanStatus.PENDING_OCR
    assert doc.linked_object_type == ""


@pytest.mark.django_db
def test_texto_basura_no_inventa_campos_ni_integra():
    company = _company()
    before = _business_counts()
    doc = _doc(company, ocr_text="garabato ilegible $$$ ~`|^ sin estructura 99999999")
    doc = extract_fields_on_document(doc)
    assert doc.status == ScanStatus.EXTRACTED
    # No revienta; produce un borrador (posiblemente vacío de campos fuertes) sin integrar.
    assert isinstance(doc.extracted_fields.get("fields"), dict)
    assert _business_counts() == before
    assert doc.linked_object_type == ""


@pytest.mark.django_db
def test_texto_vacio_no_revienta_ni_integra():
    company = _company()
    before = _business_counts()
    doc = _doc(company, ocr_text="")
    doc = extract_fields_on_document(doc)
    assert doc.status == ScanStatus.EXTRACTED
    assert doc.extracted_fields["fields"] == {}
    assert _business_counts() == before


@pytest.mark.django_db
def test_doc_que_parece_factura_pero_es_remision_no_integra():
    """Una remisión que menciona 'factura' y montos: la heurística sugiere REMISION,
    pero — sea cual sea la sugerencia — extraer no crea ni factura ni movimiento."""
    company = _company()
    before = _business_counts()
    doc = _doc(company, ocr_text="GUIA DE REMISION 0001\nfactura adjunta\nTOTAL 1.234,56\n10 sacos")
    doc = extract_fields_on_document(doc)
    assert doc.extracted_fields["doc_type_suggested"] == "REMISION"
    assert doc.extracted_fields["fields"]["total"]["value"] == "1234.56"  # normaliza europeo
    assert _business_counts() == before
    assert doc.linked_object_type == ""
