"""Tests de la reversa GLOBAL de abonos de planilla en el kernel portfolio.

`reverse_payroll_abono` es la inversa simétrica de `apply_payroll_abono`. Opera sobre `Obligation`
(base de Receivable/Credit/Payable) → la capacidad es global a todos los portafolios. Acá se prueba
con Receivable (saldo = principal), que ejercita todas las ramas de la primitiva.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.kernels.portfolio.models import ObligationStatus
from apps.kernels.portfolio.services import (
    PortfolioDomainError,
    apply_payroll_abono,
    create_receivable,
    reverse_payroll_abono,
)
from apps.modulos.iam.models import OrgUnit
from apps.modulos.parties.models import Party


def _mk_scope(suffix=""):
    s = suffix or uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H_{s}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, name=f"C_{s}", parent=holding)
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, name=f"B_{s}", parent=company)
    return company, branch


def _mk_receivable(amount="1000.00"):
    company, branch = _mk_scope()
    party = Party.objects.create(
        company=company, party_type=Party.PartyType.NATURAL,
        display_name="Trabajador", status=Party.Status.ACTIVE,
    )
    today = timezone.localdate()
    return create_receivable(
        company=company, branch=branch, party=party,
        reference_type="INVOICE", reference_id=1,
        principal_amount=Decimal(amount), currency="NIO",
        issue_date=today, due_date=today + timedelta(days=30),
    )


@pytest.mark.django_db
def test_reversa_parcial_deja_partial():
    """Abono 600 sobre 1000 (PARTIAL) → reversa 600 → PENDING, saldo completo restaurado."""
    rec = _mk_receivable("1000.00")
    apply_payroll_abono(obligation=rec, amount=Decimal("600.00"))
    rec.refresh_from_db()
    assert rec.status == ObligationStatus.PARTIAL
    assert rec.outstanding_amount == Decimal("400.00")

    reversed_amount = reverse_payroll_abono(obligation=rec, amount=Decimal("600.00"))
    rec.refresh_from_db()
    assert reversed_amount == Decimal("600.00")
    assert rec.status == ObligationStatus.PENDING
    assert rec.outstanding_amount == Decimal("1000.00")
    assert rec.paid_date is None


@pytest.mark.django_db
def test_reversa_parcial_de_un_abono_mayor():
    """Abono 1000 (PAID) → reversa SOLO 300 → reabre a PARTIAL con saldo 300."""
    rec = _mk_receivable("1000.00")
    apply_payroll_abono(obligation=rec, amount=Decimal("1000.00"))
    rec.refresh_from_db()
    assert rec.status == ObligationStatus.PAID
    assert rec.paid_date is not None

    reverse_payroll_abono(obligation=rec, amount=Decimal("300.00"))
    rec.refresh_from_db()
    assert rec.status == ObligationStatus.PARTIAL  # se reabre el PAID
    assert rec.outstanding_amount == Decimal("300.00")
    assert rec.paid_date is None


@pytest.mark.django_db
def test_reversa_total_reabre_un_pagado():
    """Caso del pagador equivocado: abonó de más, se reversa por completo y vuelve a PENDING."""
    rec = _mk_receivable("1000.00")
    apply_payroll_abono(obligation=rec, amount=Decimal("1000.00"))
    reverse_payroll_abono(obligation=rec, amount=Decimal("1000.00"))
    rec.refresh_from_db()
    assert rec.status == ObligationStatus.PENDING
    assert rec.outstanding_amount == Decimal("1000.00")
    assert rec.allocated_amount == Decimal("0.00")


@pytest.mark.django_db
def test_reversa_clampa_a_lo_aplicado():
    """Reversar más de lo aplicado solo devuelve lo aplicado (segura ante doble reversa)."""
    rec = _mk_receivable("1000.00")
    apply_payroll_abono(obligation=rec, amount=Decimal("200.00"))

    first = reverse_payroll_abono(obligation=rec, amount=Decimal("999.00"))
    assert first == Decimal("200.00")  # topado a lo realmente aplicado

    second = reverse_payroll_abono(obligation=rec, amount=Decimal("50.00"))
    assert second == Decimal("0.00")  # ya no hay nada que reversar
    rec.refresh_from_db()
    assert rec.allocated_amount == Decimal("0.00")
    assert rec.status == ObligationStatus.PENDING


@pytest.mark.django_db
def test_reversa_monto_invalido_rechaza():
    rec = _mk_receivable("1000.00")
    with pytest.raises(PortfolioDomainError):
        reverse_payroll_abono(obligation=rec, amount=Decimal("0.00"))
    with pytest.raises(PortfolioDomainError):
        reverse_payroll_abono(obligation=rec, amount=Decimal("-10.00"))


# --------------------------------------------------------------------------- #
# INVARIANTE: aplicar + reversar TOTAL == estado original EXACTO
# (incluye last_payment_date, no solo allocated_amount/status/paid_date)
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
def test_reversa_total_restaura_estado_original_exacto_incluye_last_payment_date():
    """BUG cartera: la reversa total debe ser la INVERSA EXACTA del abono.

    Estado original de un Receivable recién creado: allocated=0, PENDING,
    paid_date=None y `last_payment_date`=None (nunca ha recibido un pago).

    `apply_payroll_abono` setea `last_payment_date = abono_date` (services.py:923).
    `reverse_payroll_abono` (services.py:976-985) limpia `paid_date` pero NUNCA
    restaura/limpia `last_payment_date`. Tras aplicar + revertir TOTAL, la
    obligación queda con `last_payment_date` poblado aunque ya no exista ningún
    abono vigente -> NO es la inversa exacta (la columna "último pago" miente).
    """
    rec = _mk_receivable("1000.00")
    # Estado original capturado ANTES de cualquier movimiento.
    rec.refresh_from_db()
    assert rec.last_payment_date is None  # recién creada, sin pagos
    assert rec.paid_date is None
    assert rec.allocated_amount == Decimal("0.00")
    assert rec.status == ObligationStatus.PENDING

    abono_date = timezone.localdate() - timedelta(days=5)
    apply_payroll_abono(obligation=rec, amount=Decimal("1000.00"), abono_date=abono_date)
    rec.refresh_from_db()
    assert rec.status == ObligationStatus.PAID
    assert rec.last_payment_date == abono_date

    # Reversa TOTAL -> debe volver EXACTAMENTE al estado original.
    reverse_payroll_abono(obligation=rec, amount=Decimal("1000.00"))
    rec.refresh_from_db()
    assert rec.allocated_amount == Decimal("0.00")
    assert rec.status == ObligationStatus.PENDING
    assert rec.paid_date is None
    # El cabo suelto: last_payment_date debería volver a None (no hay abono vigente).
    assert rec.last_payment_date is None, (
        "Reversa NO es inversa exacta: last_payment_date quedó en "
        f"{rec.last_payment_date} tras revertir todo el abono. "
        "apply_payroll_abono lo setea (services.py:923) pero "
        "reverse_payroll_abono NO lo restaura (services.py:976-985)."
    )
