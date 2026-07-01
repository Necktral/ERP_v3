"""Robustez de `_coerce_day_value` (nomina/services.py) contra `day_value` BASURA.

Hallazgo del agente de robustez (A4): `_coerce_day_value` hace `Decimal(str(value))`.
La ÚNICA ruta de API que lo alimenta es `FieldCrewReportView` (POST a
`/api/nomina/field/crews/<id>/report/`), que valida la entrada con
`FieldCrewReportIn` → `FieldCrewReportLineIn.day_value = DecimalField(...)` ANTES de
construir las líneas que pasa al servicio. Es decir, la basura no-numérica se rechaza
con 400 en el serializer y JAMÁS llega a `_coerce_day_value`.

VEREDICTO: NO-BUG por la API (protegido aguas arriba). Estos tests lo DEMUESTRAN
mandando basura real por el cliente DRF y verificando 400 (no 500, no traceback).

Defensa en profundidad añadida en el servicio: `_coerce_day_value` ahora envuelve el
`Decimal(str(value))` y traduce `InvalidOperation` al error de dominio (→ 400) para
cualquier llamador interno futuro que no pase por el serializer. El último test golpea
el servicio directamente para cubrir ese guard.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.kernels.nomina.models import FieldWorkerEventType
from apps.kernels.nomina.services import _coerce_day_value
from apps.modulos.hr.models import Employee
from apps.modulos.iam.models import OrgUnit, UserMembership
from apps.modulos.rbac.models import Permission, Role, RoleAssignment, RolePermission

User = get_user_model()
BASE = "/api/nomina/field"
CAPTURE = ["nomina.field.capture", "nomina.field.read"]


def _scope():
    t = uuid.uuid4().hex[:8]
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H{t}", code=f"H-{t}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, parent=holding, name=f"C{t}", code=f"C-{t}")
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, parent=company, name=f"B{t}", code=f"B-{t}")
    return company, branch


def _client(*, company, branch, perms):
    u = User.objects.create_user(
        username=f"u_{uuid.uuid4().hex[:8]}", email=f"e_{uuid.uuid4().hex[:8]}@t.com", password="x"
    )
    UserMembership.objects.create(user=u, org_unit=company, is_active=True)
    UserMembership.objects.create(user=u, org_unit=branch, is_active=True)
    role = Role.objects.create(name=f"r_{uuid.uuid4().hex[:8]}", is_active=True)
    for p in perms:
        perm, _ = Permission.objects.get_or_create(code=p, defaults={"description": p, "is_active": True})
        RolePermission.objects.get_or_create(role=role, permission=perm)
    RoleAssignment.objects.create(user=u, role=role, org_unit=company, is_active=True)
    RoleAssignment.objects.create(user=u, role=role, org_unit=branch, is_active=True)
    c = APIClient()
    login = c.post("/api/auth/login/", {"username": u.username, "password": "x"}, format="json")
    assert login.status_code == 200, login.data
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    c.defaults["HTTP_X_COMPANY_ID"] = str(company.id)
    c.defaults["HTTP_X_BRANCH_ID"] = str(branch.id)
    return c


def _emp(company, name="Trabajador"):
    return Employee.objects.create(
        company=company, employee_code=f"E-{uuid.uuid4().hex[:6]}",
        first_name=name, last_name="Campo", is_active=True,
    )


def _open_crew(client, company, branch):
    """Abre día + cuadrilla; devuelve (crew_id, employee)."""
    e1 = _emp(company, "Juan")
    e2 = _emp(company, "Maria")
    r = client.post(f"{BASE}/work-days/", {"work_date": "2026-06-02", "branch_id": branch.id}, format="json")
    assert r.status_code == 201, r.data
    wd = r.data["id"]
    r = client.post(f"{BASE}/work-days/{wd}/rollcall/", {
        "lines": [{"employee_id": e1.id, "status": "PRESENT"}, {"employee_id": e2.id, "status": "PRESENT"}],
    }, format="json")
    assert r.status_code == 201, r.data
    r = client.post(f"{BASE}/work-days/{wd}/crews/", {"name": "Cuadrilla A", "supervisor_employee_id": e2.id}, format="json")
    assert r.status_code == 201, r.data
    return r.data["id"], e1


def _post_report(client, crew_id, employee_id, day_value):
    return client.post(f"{BASE}/crews/{crew_id}/report/", {
        "lines": [{"employee_id": employee_id, "event_type": "PRESENT", "day_value": day_value}],
        "labor_code": "COSECHA",
    }, format="json")


# --------------------------------------------------------------------------- #
# El serializer rechaza la basura ANTES de tocar el servicio (NO 500).
# --------------------------------------------------------------------------- #

# El proyecto mapea ValidationError de DRF a 422 (no 400). El gate de robustez es:
# error de CLIENTE (4xx), NUNCA 500 ni traceback. El serializer rechaza la basura aquí.
_CLIENT_ERROR = (400, 422)


# Nota: "" y "  " (vacío/espacios) los trata el serializer como AUSENTE → aplica el default
# por evento (no es basura que llegue a _coerce_day_value); ver test_day_value_null_*.
@pytest.mark.django_db
@pytest.mark.parametrize("garbage", ["abc", "1,5", "1.2.3", "NaN", "Infinity", "0x10"])
def test_day_value_string_basura_da_4xx_no_500(garbage):
    company, branch = _scope()
    client = _client(company=company, branch=branch, perms=CAPTURE)
    crew_id, emp = _open_crew(client, company, branch)
    r = _post_report(client, crew_id, emp.id, garbage)
    assert r.status_code in _CLIENT_ERROR, (garbage, r.status_code, getattr(r, "data", None))


@pytest.mark.django_db
@pytest.mark.parametrize("garbage", [[1, 2], {"x": 1}, True])
def test_day_value_tipo_no_escalar_da_4xx_no_500(garbage):
    company, branch = _scope()
    client = _client(company=company, branch=branch, perms=CAPTURE)
    crew_id, emp = _open_crew(client, company, branch)
    r = _post_report(client, crew_id, emp.id, garbage)
    assert r.status_code in _CLIENT_ERROR, (garbage, r.status_code, getattr(r, "data", None))


@pytest.mark.django_db
def test_day_value_fuera_de_rango_da_400():
    company, branch = _scope()
    client = _client(company=company, branch=branch, perms=CAPTURE)
    crew_id, emp = _open_crew(client, company, branch)
    # > 1.00 lo rechaza el dominio (_coerce_day_value), no el serializer.
    r = _post_report(client, crew_id, emp.id, "5.00")
    assert r.status_code == 400, r.data


@pytest.mark.django_db
def test_day_value_null_usa_default_por_evento():
    # null es válido (allow_null): el servicio aplica el default 1.00 para PRESENT.
    company, branch = _scope()
    client = _client(company=company, branch=branch, perms=CAPTURE)
    crew_id, emp = _open_crew(client, company, branch)
    r = _post_report(client, crew_id, emp.id, None)
    assert r.status_code == 201, r.data


@pytest.mark.django_db
def test_day_value_valido_pasa():
    company, branch = _scope()
    client = _client(company=company, branch=branch, perms=CAPTURE)
    crew_id, emp = _open_crew(client, company, branch)
    r = _post_report(client, crew_id, emp.id, "0.50")
    assert r.status_code == 201, r.data


# --------------------------------------------------------------------------- #
# Defensa en profundidad: el servicio NO revienta con InvalidOperation aunque
# lo llamen sin pasar por el serializer (llamador interno futuro: sync/import).
# --------------------------------------------------------------------------- #

def test_coerce_day_value_degrada_basura_a_error_de_dominio():
    from apps.kernels.nomina.services import FieldAttendanceError

    for bad in ["abc", "1,5", [1], {"x": 1}, object()]:
        with pytest.raises(FieldAttendanceError) as exc:
            _coerce_day_value(bad, event_type=FieldWorkerEventType.PRESENT)
        assert exc.value.code == "invalid_day_value"


def test_coerce_day_value_acepta_numero_valido():
    assert _coerce_day_value("0.50", event_type=FieldWorkerEventType.PRESENT) == Decimal("0.50")
    assert _coerce_day_value(None, event_type=FieldWorkerEventType.PRESENT) == Decimal("1.00")
    assert _coerce_day_value(None, event_type=FieldWorkerEventType.ABSENT) == Decimal("0.00")
