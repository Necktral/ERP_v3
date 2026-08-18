"""U9: numeración fiscal y recuperación de contingencia sobre PostgreSQL real."""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, wait
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.db import connection

from apps.kernels.facturacion.models import (
    BillingDocument,
    BillingSequence,
    BranchFiscalConfig,
    DocStatus,
    DocType,
    FiscalMode,
    FiscalPrintJob,
    FiscalStatus,
)
from apps.kernels.facturacion.services import (
    BillingConflictError,
    create_draft,
    issue_doc,
    mark_doc_contingency,
    process_fiscal_print_jobs,
    resolve_doc_contingency,
)
from apps.modulos.iam.models import OrgUnit
from apps.modulos.integration.models import OutboxEvent

User = get_user_model()


def _scope():
    token = uuid.uuid4().hex[:8]
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H-{token}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, parent=holding, name=f"C-{token}")
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, parent=company, name=f"B-{token}")
    actor = User.objects.create_user(username=f"u9-{token}", password="Secret123!")
    BranchFiscalConfig.objects.create(
        company=company,
        branch=branch,
        fiscal_mode=FiscalMode.B,
        adapter_code="EMULATED_B",
        print_required=True,
        strict_integrity=True,
        contingency_max_attempts=2,
    )
    return company, branch, actor


def _request(company, branch, actor):
    return SimpleNamespace(
        company=company,
        branch=branch,
        user=actor,
        META={},
        headers={},
        path="/test/u9/fiscal/",
        method="POST",
        request_id=f"req-{uuid.uuid4().hex}",
        data={},
    )


def _draft(company, branch, actor, *, key: str) -> int:
    return create_draft(
        request=_request(company, branch, actor),
        actor=actor,
        doc_type=DocType.INVOICE,
        series="F",
        currency="NIO",
        customer_name="Cliente fiscal",
        customer_ref="",
        is_fiscal=True,
        lines=[{"description": "Servicio", "quantity": "1", "unit_price": "100", "tax_rate": "0.15"}],
        idempotency_key=key,
    ).doc_id


@pytest.mark.django_db(transaction=True)
def test_emision_concurrente_reserva_numeros_unicos_y_contiguos():
    company, branch, actor = _scope()
    doc_ids = [_draft(company, branch, actor, key=f"draft-{idx}-{uuid.uuid4().hex}") for idx in range(8)]
    barrier = threading.Barrier(len(doc_ids), timeout=20)
    errors: list[str] = []
    lock = threading.Lock()

    def issue(doc_id: int) -> None:
        try:
            # Impide que una regresión de locks deje hilos vivos y convierta el
            # test en una espera acumulativa por cada join.
            with connection.cursor() as cursor:
                cursor.execute("SET statement_timeout = '15s'")
                cursor.execute("SET lock_timeout = '10s'")
            barrier.wait()
            issue_doc(
                request=_request(company, branch, actor),
                actor=actor,
                doc_id=doc_id,
                print_after_issue=False,
            )
        except Exception as exc:  # pragma: no cover - el assert reporta el tipo real
            with lock:
                errors.append(f"{doc_id}: {exc!r}")
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=len(doc_ids), thread_name_prefix="u9-fiscal") as pool:
        futures = [pool.submit(issue, doc_id) for doc_id in doc_ids]
        done, pending = wait(futures, timeout=25)
        assert not pending, "la reserva fiscal excedió el timeout global de 25s"
        for future in done:
            future.result()
    assert not errors, errors
    numbers = list(
        BillingDocument.objects.filter(id__in=doc_ids).order_by("number").values_list("number", flat=True)
    )
    assert numbers == list(range(1, len(doc_ids) + 1))
    assert len(numbers) == len(set(numbers))
    seq = BillingSequence.objects.get(company=company, branch=branch, doc_type=DocType.INVOICE, series="F")
    assert seq.next_number == len(doc_ids) + 1


@pytest.mark.django_db
@pytest.mark.parametrize("next_number", [7, 2_147_483_647])
def test_colision_o_agotamiento_fiscal_es_conflicto_controlado_y_atomico(next_number: int):
    company, branch, actor = _scope()
    doc_id = _draft(company, branch, actor, key=f"target-{uuid.uuid4().hex}")
    BillingSequence.objects.create(
        company=company,
        branch=branch,
        doc_type=DocType.INVOICE,
        series="F",
        next_number=next_number,
    )
    if next_number == 7:
        BillingDocument.objects.create(
            company=company,
            branch=branch,
            doc_type=DocType.INVOICE,
            status=DocStatus.ISSUED,
            series="F",
            number=7,
            currency="NIO",
            customer_name="Número preexistente",
            subtotal="1.00",
            total="1.00",
        )

    with pytest.raises(BillingConflictError):
        issue_doc(
            request=_request(company, branch, actor),
            actor=actor,
            doc_id=doc_id,
            print_after_issue=False,
        )

    target = BillingDocument.objects.get(id=doc_id)
    assert target.status == DocStatus.DRAFT
    assert target.number == 0
    assert BillingSequence.objects.get(
        company=company, branch=branch, doc_type=DocType.INVOICE, series="F"
    ).next_number == next_number


@pytest.mark.django_db
def test_contingencia_reintenta_una_vez_y_reconcilia_consecuencias_sin_renumerar():
    company, branch, actor = _scope()
    doc_id = _draft(company, branch, actor, key=f"cont-{uuid.uuid4().hex}")
    issued = issue_doc(
        request=_request(company, branch, actor),
        actor=actor,
        doc_id=doc_id,
        print_after_issue=False,
    )
    number = issued["number"]

    marked = mark_doc_contingency(
        request=_request(company, branch, actor),
        actor=actor,
        doc_id=doc_id,
        reason="IMPRESORA_DESCONECTADA",
    )
    assert marked["fiscal_status"] == FiscalStatus.CONTINGENCY

    first = resolve_doc_contingency(
        request=_request(company, branch, actor),
        actor=actor,
        doc_id=doc_id,
        action="RETRY_PRINT",
        idempotency_key="u9-contingency-retry",
    )
    replay = resolve_doc_contingency(
        request=_request(company, branch, actor),
        actor=actor,
        doc_id=doc_id,
        action="RETRY_PRINT",
        idempotency_key="u9-contingency-retry",
    )
    assert replay["job_id"] == first["job_id"]
    assert FiscalPrintJob.objects.filter(doc_id=doc_id).count() == 1

    summary = process_fiscal_print_jobs(limit=10, actor=actor)
    assert summary.printed == 1
    doc = BillingDocument.objects.get(id=doc_id)
    assert doc.number == number
    assert doc.status == DocStatus.ISSUED
    assert doc.fiscal_status == FiscalStatus.PRINTED
    assert doc.printed_at is not None
    assert doc.contingency_reason == "IMPRESORA_DESCONECTADA"
    assert OutboxEvent.objects.filter(
        company=company,
        branch=branch,
        source_module="BILLING",
        event_type="BILLING.FiscalContingencyRecorded",
    ).count() == 1
    assert OutboxEvent.objects.filter(
        company=company,
        branch=branch,
        source_module="BILLING",
        event_type="BILLING.FiscalPrinted",
    ).count() == 1
