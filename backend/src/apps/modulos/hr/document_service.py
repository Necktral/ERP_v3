"""Documentos del expediente del trabajador — validación y guardado.

Mismo criterio que photo_service: el archivo se guarda en base64 en la DB (el
expediente viaja completo en respaldos/sync). El tipo se valida por los BYTES
(magic numbers), no por el content-type del cliente (que miente fácil). Se
aceptan PDF, JPEG y PNG hasta 8 MB.
"""
from __future__ import annotations

import base64

from django.core.exceptions import ValidationError

from apps.modulos.audit.writer import write_event

from .models import Employee, EmployeeDocument

MAX_UPLOAD_BYTES = 8 * 1024 * 1024


def _sniff_content_type(raw: bytes) -> str | None:
    """Detecta PDF/JPEG/PNG por magic number; None si no es soportado."""
    if raw[:5] == b"%PDF-":
        return "application/pdf"
    if raw[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return None


def list_employee_documents(employee: Employee) -> list[EmployeeDocument]:
    return list(
        employee.documents.only(
            "id", "category", "title", "content_type", "byte_size",
            "original_filename", "notes", "uploaded_at", "uploaded_by",
        ).select_related("uploaded_by")
    )


def attach_employee_document(
    *,
    request,
    actor,
    employee: Employee,
    raw: bytes,
    category: str,
    title: str,
    filename: str = "",
    notes: str = "",
) -> EmployeeDocument:
    if not raw:
        raise ValidationError({"file": "Adjuntá un archivo."})
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValidationError({"file": "El documento supera el máximo de 8 MB."})
    content_type = _sniff_content_type(raw)
    if content_type is None:
        raise ValidationError({"file": "Formato no soportado. Subí un PDF, JPG o PNG."})
    if category not in EmployeeDocument.Category.values:
        raise ValidationError({"category": "Categoría inválida."})
    if not (title or "").strip():
        raise ValidationError({"title": "Indicá un título para el documento."})

    doc = EmployeeDocument.objects.create(
        employee=employee,
        category=category,
        title=title.strip(),
        file_data=base64.b64encode(raw).decode("ascii"),
        content_type=content_type,
        byte_size=len(raw),
        original_filename=(filename or "")[:255],
        notes=(notes or "")[:255],
        uploaded_by=actor,
    )
    write_event(
        request=request,
        module="HR",
        event_type="HR_EMPLOYEE_DOCUMENT_ATTACHED",
        reason_code="OK",
        actor_user=actor,
        subject_type="EMPLOYEE_DOCUMENT",
        subject_id=str(doc.id),
        metadata={
            "employee_id": employee.id,
            "category": category,
            "content_type": content_type,
            "byte_size": len(raw),
        },
    )
    return doc


def get_document_data(doc: EmployeeDocument) -> tuple[bytes, str]:
    return base64.b64decode(doc.file_data), doc.content_type


def remove_employee_document(*, request, actor, doc: EmployeeDocument) -> bool:
    employee_id = doc.employee_id
    doc_id = doc.id
    deleted, _ = EmployeeDocument.objects.filter(id=doc.id).delete()
    if deleted:
        write_event(
            request=request,
            module="HR",
            event_type="HR_EMPLOYEE_DOCUMENT_REMOVED",
            reason_code="OK",
            actor_user=actor,
            subject_type="EMPLOYEE_DOCUMENT",
            subject_id=str(doc_id),
            metadata={"employee_id": employee_id},
        )
    return bool(deleted)
