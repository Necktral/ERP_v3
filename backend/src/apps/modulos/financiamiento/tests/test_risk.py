"""Tests del motor ASESOR de riesgo de cartera (Random Forest opcional + Monte Carlo determinista).

El RF es opcional (scikit-learn) y en tests la IA está apagada (settings.test) → el serving usa
SIEMPRE la heurística determinista. Monte Carlo usa la stdlib con semilla fija → reproducible.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.modulos.financiamiento import risk, risk_ml
from apps.modulos.financiamiento import services as fin
from apps.modulos.iam.models import OrgUnit, UserMembership
from apps.modulos.parties.models import Party
from apps.modulos.rbac.models import Permission, Role, RoleAssignment, RolePermission

User = get_user_model()
UT = OrgUnit.UnitType


# --------------------------------------------------------------------------- #
# Motor puro (sin DB): heurística + Monte Carlo
# --------------------------------------------------------------------------- #

def test_heuristic_pd_monotona_en_atraso():
    pds = [risk.heuristic_pd(status="PENDING", days_overdue=d, producer_default_rate=0.0)
           for d in (0, 15, 45, 75, 100, 200)]
    assert pds == sorted(pds)
    assert pds[0] < pds[-1]


def test_heuristic_pd_sube_con_historial_de_mora():
    bajo = risk.heuristic_pd(status="PENDING", days_overdue=10, producer_default_rate=0.0)
    alto = risk.heuristic_pd(status="PENDING", days_overdue=10, producer_default_rate=0.8)
    assert alto > bajo


def test_recovery_sube_con_garantia_baja_lgd():
    sin_gar = risk.recovery_rate(garantia_cobertura=0.0)
    con_gar = risk.recovery_rate(garantia_cobertura=2.0)
    assert con_gar > sin_gar  # más garantía ⇒ más recuperación ⇒ menor LGD


def test_montecarlo_reproducible_misma_semilla():
    pos = [{"pd": 0.1, "loss_given_default": 1000.0}, {"pd": 0.3, "loss_given_default": 2000.0}]
    a = risk.simulate_portfolio_loss(pos, simulations=3000, seed=42)
    b = risk.simulate_portfolio_loss(pos, simulations=3000, seed=42)
    assert a == b
    # Otra semilla ⇒ resultado distinto (es estocástico, no constante).
    c = risk.simulate_portfolio_loss(pos, simulations=3000, seed=99)
    assert c["perdida_esperada"] != a["perdida_esperada"] or c["var_95"] != a["var_95"]


def test_montecarlo_var_ordenado_y_rho_cero_aprox_analitico():
    pos = [{"pd": 0.1, "loss_given_default": 1000.0},
           {"pd": 0.2, "loss_given_default": 2000.0},
           {"pd": 0.05, "loss_given_default": 5000.0}]
    r = risk.simulate_portfolio_loss(pos, simulations=20000, seed=7, rho=0.0)
    esperada = float(r["perdida_esperada"])
    # Percentiles ordenados y máxima ≥ esperada (invariantes que SIEMPRE valen).
    assert float(r["var_99"]) >= float(r["var_95"]) >= float(r["perdida_p50"]) >= 0.0
    assert float(r["perdida_maxima"]) >= esperada >= 0.0
    analitico = sum(p["pd"] * p["loss_given_default"] for p in pos)  # E[L] con rho=0
    assert abs(esperada - analitico) / analitico < 0.10  # MC ≈ analítico (±10%)


# --------------------------------------------------------------------------- #
# RF opcional: en tests la IA está apagada ⇒ predict_pd None ⇒ heurística
# --------------------------------------------------------------------------- #

def test_predict_pd_none_con_ia_apagada():
    feats = {k: 0.0 for k in risk_ml.FEATURE_ORDER}
    assert risk_ml.predict_pd(feats) is None


def test_rf_serving_usa_modelo_si_existe(tmp_path, monkeypatch):
    """Con sklearn + modelo + IA encendida, predict_pd devuelve la PD del RF (no None).

    Se salta si scikit-learn no está instalado (es una dependencia OPCIONAL)."""
    pytest.importorskip("sklearn")
    import joblib
    from sklearn.ensemble import RandomForestClassifier

    n = len(risk_ml.FEATURE_ORDER)
    X = [[float(i)] * n for i in range(20)]
    y = [0] * 10 + [1] * 10
    model = RandomForestClassifier(n_estimators=10, random_state=0).fit(X, y)
    path = tmp_path / "rf.joblib"
    joblib.dump(model, path)

    monkeypatch.setattr(risk_ml, "model_path", lambda: str(path))
    risk_ml._load_model.cache_clear()
    monkeypatch.setattr(risk_ml, "ai_features_enabled", lambda: True)

    pd = risk_ml.predict_pd({k: 5.0 for k in risk_ml.FEATURE_ORDER})
    assert pd is not None and 0.0 <= pd <= 1.0


# --------------------------------------------------------------------------- #
# build_risk_package + endpoint (con DB)
# --------------------------------------------------------------------------- #

def _scope():
    t = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=UT.HOLDING, name=f"H{t}", code=f"H-{t}")
    company = OrgUnit.objects.create(unit_type=UT.COMPANY, parent=holding, name=f"C{t}", code=f"C-{t}")
    branch = OrgUnit.objects.create(unit_type=UT.BRANCH, parent=company, name=f"B{t}", code=f"B-{t}")
    return holding, company, branch


def _user():
    t = uuid.uuid4().hex[:8]
    return User.objects.create_user(username=f"u_{t}", email=f"u_{t}@t.local", password="pass12345")


def _req(company, branch, user):
    return SimpleNamespace(
        company=company, branch=branch, user=user, META={}, headers={},
        path="/test/risk/", method="POST", request_id=f"req-{uuid.uuid4().hex[:8]}",
    )


def _make_active_loan(company, branch):
    """Solicitud → submit → approve → disburse (SoD por actor) ⇒ préstamo con créditos."""
    oficial, comite, admin = _user(), _user(), _user()
    party = Party.objects.create(
        company=company, party_type=Party.PartyType.NATURAL, display_name="Coop La Esperanza",
        national_id=f"001-{uuid.uuid4().hex[:9]}",
    )
    producer = fin.create_producer(company=company, party=party, acopio_code="01-001")
    app = fin.create_application(
        company=company, producer=producer, actor=oficial,
        requested_nio=Decimal("10000.00"), requested_usd=Decimal("1000.00"), term_months=8,
        credit_type="AVIO", activity="Mantenimiento de café",
        interest_rate=Decimal("12.00"), penalty_rate=Decimal("4.00"), commission_rate=Decimal("2.00"),
        guarantee_farm_area_mz=Decimal("25.00"), guarantee_coffee_qq=Decimal("150.00"),
    )
    fin.submit_application(application=app)
    fin.approve_application(application=app, actor=comite, request=_req(company, branch, comite))
    return fin.disburse_loan(request=_req(company, branch, admin), actor=admin, application=app)


@pytest.mark.django_db
def test_build_risk_package_con_un_prestamo():
    _h, company, branch = _scope()
    _make_active_loan(company, branch)
    pkg = risk.build_risk_package(company, simulations=2000, seed=1)
    assert pkg["prestamos_activos"] == 1
    assert float(pkg["exposicion_total"]) > 0
    assert pkg["ai_used"] is False  # IA apagada en tests
    assert pkg["detalle"][0]["fuente_pd"] == "heuristica"
    sim = pkg["simulacion"]
    assert sim is not None
    # VaR puede ser 0 con un solo préstamo sano (la mora es rara): solo valen estos invariantes.
    assert float(sim["var_99"]) >= float(sim["var_95"]) >= 0.0
    assert float(sim["perdida_maxima"]) >= float(sim["perdida_esperada"]) >= 0.0


def _api_user_con_permiso(company, perms):
    t = uuid.uuid4().hex[:6]
    user = User.objects.create_user(username=f"api_{t}", email=f"api_{t}@t.local", password="pass12345")
    UserMembership.objects.create(user=user, org_unit=company, is_active=True)
    role = Role.objects.create(name=f"role_{t}", is_active=True)
    for code in perms:
        perm, _ = Permission.objects.get_or_create(code=code, defaults={"description": code, "is_active": True})
        RolePermission.objects.get_or_create(role=role, permission=perm)
    RoleAssignment.objects.create(user=user, role=role, org_unit=company, is_active=True)
    client = APIClient()
    login = client.post("/api/auth/login/", {"username": user.username, "password": "pass12345"}, format="json")
    assert login.status_code == 200, login.data
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    client.defaults["HTTP_X_COMPANY_ID"] = str(company.id)
    return client


@pytest.mark.django_db
def test_endpoint_riesgo_200_con_permiso():
    _h, company, branch = _scope()
    _make_active_loan(company, branch)
    client = _api_user_con_permiso(company, ["financing.risk.read"])
    r = client.get("/api/financiamiento/risk/", {"simulations": 1000, "seed": 5})
    assert r.status_code == 200, r.data
    assert r.data["prestamos_activos"] == 1
    assert r.data["simulacion"] is not None


@pytest.mark.django_db
def test_endpoint_riesgo_sin_permiso_es_403():
    _h, company, _branch = _scope()
    client = _api_user_con_permiso(company, ["financing.loan.read"])  # sin financing.risk.read
    r = client.get("/api/financiamiento/risk/")
    assert r.status_code == 403
