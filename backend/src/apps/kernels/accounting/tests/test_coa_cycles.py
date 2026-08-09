from __future__ import annotations

import uuid
import threading

import pytest

from apps.kernels.accounting.models import ChartOfAccount
from apps.kernels.accounting.phase7 import Phase7ValidationError, upsert_chart_of_accounts
from apps.modulos.iam.models import OrgUnit


def _company() -> OrgUnit:
    suffix = uuid.uuid4().hex[:8]
    holding = OrgUnit.objects.create(
        unit_type=OrgUnit.UnitType.HOLDING,
        name=f"H-{suffix}",
        code=f"H-{suffix}",
    )
    return OrgUnit.objects.create(
        unit_type=OrgUnit.UnitType.COMPANY,
        parent=holding,
        name=f"C-{suffix}",
        code=f"C-{suffix}",
    )


@pytest.mark.django_db
def test_coa_upsert_rejects_two_node_cycle_atomically():
    company = _company()

    with pytest.raises(Phase7ValidationError, match="ciclo"):
        upsert_chart_of_accounts(
            company=company,
            rows=[
                {"code": "A", "name": "A", "account_type": "ASSET", "parent_code": "B"},
                {"code": "B", "name": "B", "account_type": "ASSET", "parent_code": "A"},
            ],
        )

    assert not ChartOfAccount.objects.filter(company=company).exists()


@pytest.mark.django_db
def test_coa_upsert_rejects_cycle_through_existing_accounts():
    company = _company()
    upsert_chart_of_accounts(
        company=company,
        rows=[
            {"code": "A", "name": "A", "account_type": "ASSET"},
            {"code": "B", "name": "B", "account_type": "ASSET", "parent_code": "A"},
        ],
    )

    with pytest.raises(Phase7ValidationError, match="ciclo"):
        upsert_chart_of_accounts(
            company=company,
            rows=[
                {"code": "A", "name": "A", "account_type": "ASSET", "parent_code": "B"},
                {"code": "B", "name": "B", "account_type": "ASSET", "parent_code": "A"},
            ],
        )

    a = ChartOfAccount.objects.get(company=company, code="A")
    b = ChartOfAccount.objects.get(company=company, code="B")
    assert a.parent_id is None
    assert b.parent_id == a.id


@pytest.mark.django_db(transaction=True)
def test_coa_concurrent_upserts_cannot_commit_a_cycle():
    from django.db import connection

    company = _company()
    upsert_chart_of_accounts(
        company=company,
        rows=[
            {"code": "A", "name": "A", "account_type": "ASSET"},
            {"code": "B", "name": "B", "account_type": "ASSET"},
        ],
    )
    barrier = threading.Barrier(2, timeout=10)
    errors: list[Exception] = []
    errors_lock = threading.Lock()

    def update_parent(code: str, parent_code: str) -> None:
        try:
            barrier.wait()
            upsert_chart_of_accounts(
                company=company,
                rows=[
                    {
                        "code": code,
                        "name": code,
                        "account_type": "ASSET",
                        "parent_code": parent_code,
                    }
                ],
            )
        except Exception as exc:  # noqa: BLE001 - el test clasifica al perdedor
            with errors_lock:
                errors.append(exc)
        finally:
            connection.close()

    threads = [
        threading.Thread(target=update_parent, args=("A", "B")),
        threading.Thread(target=update_parent, args=("B", "A")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not any(thread.is_alive() for thread in threads)
    assert len(errors) == 1
    assert isinstance(errors[0], Phase7ValidationError)
    assert "ciclo" in str(errors[0]).lower()

    accounts = {row.code: row for row in ChartOfAccount.objects.filter(company=company)}
    assert not (accounts["A"].parent_id == accounts["B"].id and accounts["B"].parent_id == accounts["A"].id)
