"""Contratos a fondo: versionado del texto, renovaciones encadenadas y firmas.

Complementa los servicios base (`create_contract_draft`/`issue_contract`/
`annul_contract` en services.py). No importa de services.py a nivel de módulo
para evitar import circular; las dependencias se resuelven perezosamente.
"""
from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.modulos.audit.writer import write_event

from .models import ContractSignature, ContractVersion, EmploymentContract


# ---------------------------------------------------------------------------
# Versionado del texto
# ---------------------------------------------------------------------------

def snapshot_contract_version(
    *, contract: EmploymentContract, reason: str = "", actor=None, body: str | None = None
) -> ContractVersion:
    """Congela una versión inmutable del texto del contrato.

    v1 se captura al EMITIR; las adendas crean versiones siguientes.
    """
    last = contract.versions.aggregate(m=Max("version_no"))["m"] or 0
    return ContractVersion.objects.create(
        contract=contract,
        version_no=last + 1,
        body=body if body is not None else contract.body,
        salary_amount=contract.salary_amount,
        salary_period=contract.salary_period,
        reason=reason or "",
        created_by=actor,
    )


@transaction.atomic
def amend_contract(
    *, contract: EmploymentContract, body: str, reason: str, request=None, actor=None
) -> ContractVersion:
    """Adenda sobre un contrato EMITIDO: nueva versión + texto vigente actualizado."""
    contract = EmploymentContract.objects.select_for_update().get(pk=contract.pk)
    if contract.status != EmploymentContract.Status.EMITIDO:
        raise ValueError("CONTRACT_NOT_ISSUED")
    if not (body or "").strip():
        raise ValueError("AMENDMENT_EMPTY_BODY")
    if not (reason or "").strip():
        raise ValueError("AMENDMENT_REASON_REQUIRED")

    contract.body = body
    contract.save(update_fields=["body", "updated_at"])
    version = snapshot_contract_version(contract=contract, reason=reason, actor=actor, body=body)

    write_event(
        request=request,
        module="HR",
        event_type="HR_CONTRACT_AMENDED",
        reason_code="OK",
        actor_user=actor,
        subject_type="CONTRACT",
        subject_id=str(contract.id),
        metadata={"contract_id": contract.id, "version_no": version.version_no, "reason": reason},
    )
    return version


# ---------------------------------------------------------------------------
# Renovación encadenada
# ---------------------------------------------------------------------------

@transaction.atomic
def renew_contract(
    *,
    contract: EmploymentContract,
    start_date,
    end_date=None,
    salary_amount=None,
    salary_period: str | None = None,
    position=None,
    request=None,
    actor=None,
) -> EmploymentContract:
    """Renueva un contrato: FINALIZA el previo (si está EMITIDO) y crea un BORRADOR
    encadenado (`renews`) heredando datos del anterior salvo los que se sobrescriban.
    """
    from .services import create_contract_draft  # perezoso: evita import circular

    prev = EmploymentContract.objects.select_for_update().get(pk=contract.pk)
    if prev.status not in (EmploymentContract.Status.EMITIDO, EmploymentContract.Status.FINALIZADO):
        raise ValueError("CONTRACT_NOT_RENEWABLE")

    if prev.status == EmploymentContract.Status.EMITIDO:
        prev.status = EmploymentContract.Status.FINALIZADO
        prev.save(update_fields=["status", "updated_at"])

    new = create_contract_draft(
        employee=prev.employee,
        contract_type=prev.contract_type,
        start_date=start_date,
        end_date=end_date,
        position=position if position is not None else prev.position,
        salary_amount=salary_amount if salary_amount is not None else prev.salary_amount,
        salary_period=salary_period or prev.salary_period,
        request=request,
        actor=actor,
    )
    new.renews = prev
    new.save(update_fields=["renews"])

    write_event(
        request=request,
        module="HR",
        event_type="HR_CONTRACT_RENEWED",
        reason_code="OK",
        actor_user=actor,
        subject_type="CONTRACT",
        subject_id=str(new.id),
        metadata={"contract_id": new.id, "renews_id": prev.id, "employee_id": prev.employee_id},
    )
    return new


# ---------------------------------------------------------------------------
# Control de firmas (ambas partes)
# ---------------------------------------------------------------------------

@transaction.atomic
def register_signature(
    *,
    contract: EmploymentContract,
    party_role: str,
    signer_name: str,
    method: str = ContractSignature.Method.FISICA,
    request=None,
    actor=None,
) -> EmploymentContract:
    """Registra la firma de una de las partes sobre un contrato EMITIDO.

    Cuando ambas partes firmaron, marca `fully_signed_at`.
    """
    contract = EmploymentContract.objects.select_for_update().get(pk=contract.pk)
    if contract.status != EmploymentContract.Status.EMITIDO:
        raise ValueError("CONTRACT_NOT_ISSUED")
    if party_role not in ContractSignature.PartyRole.values:
        raise ValueError("INVALID_PARTY_ROLE")
    if method not in ContractSignature.Method.values:
        raise ValueError("INVALID_SIGNATURE_METHOD")
    if not (signer_name or "").strip():
        raise ValueError("SIGNER_NAME_REQUIRED")

    now = timezone.now()
    ContractSignature.objects.update_or_create(
        contract=contract,
        party_role=party_role,
        defaults={
            "signer_name": signer_name.strip(),
            "method": method,
            "signed_at": now,
            "signed_by": actor,
        },
    )

    fields = ["updated_at"]
    if party_role == ContractSignature.PartyRole.EMPLEADOR:
        contract.signed_employer_at = now
        fields.append("signed_employer_at")
    else:
        contract.signed_employee_at = now
        fields.append("signed_employee_at")
    if contract.signed_employer_at and contract.signed_employee_at and contract.fully_signed_at is None:
        contract.fully_signed_at = now
        fields.append("fully_signed_at")
    contract.save(update_fields=fields)

    write_event(
        request=request,
        module="HR",
        event_type="HR_CONTRACT_SIGNED",
        reason_code="OK",
        actor_user=actor,
        subject_type="CONTRACT",
        subject_id=str(contract.id),
        metadata={
            "contract_id": contract.id,
            "party_role": party_role,
            "fully_signed": contract.fully_signed_at is not None,
        },
    )
    return contract


# ---------------------------------------------------------------------------
# Alertas de vencimiento
# ---------------------------------------------------------------------------

def expiring_contracts(*, company, within_days: int = 30):
    """Contratos EMITIDOS con fecha de fin dentro de `within_days` (o ya vencidos)."""
    cutoff = timezone.localdate() + timedelta(days=int(within_days))
    return list(
        EmploymentContract.objects.filter(
            employee__company=company,
            status=EmploymentContract.Status.EMITIDO,
            end_date__isnull=False,
            end_date__lte=cutoff,
        )
        .select_related("employee", "position")
        .order_by("end_date", "id")
    )
