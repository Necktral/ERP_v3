"""Robustez del asistente IA con el KILL-SWITCH del LLM ENCENDIDO (A3).

En `config.settings.test` el LLM está apagado (`AI_FEATURES_ENABLED=False` y sin URL),
así que la SÍNTESIS y el manejo de fallos del proveedor nunca se ejercían. Aquí
ENCENDEMOS la IA (monkeypatch de `ai_features_enabled` + un `_llm_config` con base_url
fake) y MOCKEAMOS el cliente HTTP (`requests.post`) para simular los 4 fallos típicos
del proveedor:

  (a) TIMEOUT / el LLM tarda más del límite.
  (b) respuesta VACÍA.
  (c) markdown / bloque `<think>` SIN cerrar (parser robusto, no explota).
  (d) proveedor CAÍDO (conexión rechazada / excepción del cliente).

Invariante que verificamos: el endpoint/servicio DEGRADA HONESTO — nunca 500 crudo,
nunca traceback al usuario, nunca dato inventado. Cae a la respuesta determinista
(retrieval / skill) y marca `ai_used=False`.

Se cubren las TRES superficies con LLM:
  - `synthesis.synthesize_answer`  (usada por /api/knowledge/search/ y assistant docs)
  - `chat.answer_chat`             (POST /api/knowledge/chat/  — endpoint end-to-end)
  - `assistant._route_with_llm`    (GET  /api/knowledge/assistant/)
"""
from __future__ import annotations

import uuid

import pytest
import requests
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.modulos.hr.models import Employee
from apps.modulos.iam.models import OrgUnit, UserMembership
from apps.modulos.knowledge import assistant as assistantmod
from apps.modulos.knowledge import chat as chatmod
from apps.modulos.knowledge import synthesis as synthmod
from apps.modulos.rbac.models import Permission, Role, RoleAssignment, RolePermission

User = get_user_model()
UT = OrgUnit.UnitType
BASE = "knowledge.docs.read"
FAKE_CFG = ("http://llm.fake", "modelo-x", 1.0)


# --------------------------------------------------------------------------- #
# Setup
# --------------------------------------------------------------------------- #

def _mk(perm_codes, *, employees=0):
    t = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=UT.HOLDING, name=f"H{t}")
    company = OrgUnit.objects.create(unit_type=UT.COMPANY, name=f"Empresa{t}", parent=holding)
    user = User.objects.create_user(username=f"ll_{t}", email=f"ll_{t}@t.local", password="pass12345")
    UserMembership.objects.create(user=user, org_unit=company, is_active=True)
    role = Role.objects.create(name=f"ll_role_{t}", is_active=True)
    for code in [BASE, *perm_codes]:
        perm, _ = Permission.objects.get_or_create(code=code, defaults={"description": code, "is_active": True})
        RolePermission.objects.get_or_create(role=role, permission=perm)
    RoleAssignment.objects.create(user=user, role=role, org_unit=company, is_active=True)
    for i in range(employees):
        Employee.objects.create(company=company, first_name=f"Emp{i}")
    client = APIClient()
    login = client.post("/api/auth/login/", {"username": user.username, "password": "pass12345"}, format="json")
    assert login.status_code == 200, login.data
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    client.defaults["HTTP_X_COMPANY_ID"] = str(company.id)
    return client, company


class _FakeResp:
    """Respuesta OpenAI-compat configurable."""

    def __init__(self, content="", *, raise_http=False, bad_json=False):
        self._content = content
        self._raise_http = raise_http
        self._bad_json = bad_json

    def raise_for_status(self):
        if self._raise_http:
            raise requests.exceptions.HTTPError("500 Server Error")

    def json(self):
        if self._bad_json:
            raise ValueError("No JSON could be decoded")
        return {"choices": [{"message": {"content": self._content}}]}


def _ai_on(monkeypatch, *modules):
    """Enciende el kill-switch (override) y cablea un base_url fake en cada módulo."""
    for mod in modules:
        monkeypatch.setattr(mod, "ai_features_enabled", lambda: True)
        monkeypatch.setattr(mod, "_llm_config", lambda: FAKE_CFG)


# Las 4 fábricas de fallo del proveedor -------------------------------------- #
def _timeout_post(*a, **k):
    raise requests.exceptions.Timeout("el LLM tardó demasiado")


def _conn_refused_post(*a, **k):
    raise requests.exceptions.ConnectionError("Connection refused")


def _empty_post(*a, **k):
    return _FakeResp("")


def _unclosed_think_post(*a, **k):
    # <think> sin cerrar + markdown sin cerrar: el parser no debe reventar.
    return _FakeResp("<think> razonando sin parar y sin cerrar **negrita sin cierre `code")


PROVIDER_FAILURES = [
    pytest.param(_timeout_post, id="a_timeout"),
    pytest.param(_empty_post, id="b_respuesta_vacia"),
    pytest.param(_unclosed_think_post, id="c_think_sin_cerrar"),
    pytest.param(_conn_refused_post, id="d_proveedor_caido"),
]


# --------------------------------------------------------------------------- #
# (1) synthesis.synthesize_answer — el seam del LLM en search/docs
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
@pytest.mark.parametrize("fail_post", PROVIDER_FAILURES)
def test_synthesize_degrada_a_none_ante_fallo_del_proveedor(monkeypatch, fail_post):
    _ai_on(monkeypatch, synthmod)
    monkeypatch.setattr(synthmod.requests, "post", fail_post)
    results = [{"source_path": "docs/caja.md", "heading": "Cierre", "content": "Conteo y aprobación.", "excerpt": "Conteo"}]
    out = synthmod.synthesize_answer("cómo cierro caja", results)
    # Degradación honesta: None → el endpoint responde con el retrieval determinista.
    assert out is None


@pytest.mark.django_db
def test_synthesize_http_500_del_proveedor_degrada(monkeypatch):
    _ai_on(monkeypatch, synthmod)
    monkeypatch.setattr(synthmod.requests, "post", lambda *a, **k: _FakeResp(raise_http=True))
    results = [{"source_path": "d.md", "heading": "H", "content": "x", "excerpt": "x"}]
    assert synthmod.synthesize_answer("q", results) is None


@pytest.mark.django_db
def test_synthesize_json_corrupto_degrada(monkeypatch):
    _ai_on(monkeypatch, synthmod)
    monkeypatch.setattr(synthmod.requests, "post", lambda *a, **k: _FakeResp(bad_json=True))
    results = [{"source_path": "d.md", "heading": "H", "content": "x", "excerpt": "x"}]
    assert synthmod.synthesize_answer("q", results) is None


# --------------------------------------------------------------------------- #
# (2) chat.answer_chat — endpoint /api/knowledge/chat/ END-TO-END
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
@pytest.mark.parametrize("fail_post", PROVIDER_FAILURES)
def test_chat_endpoint_degrada_con_proveedor_fallando(monkeypatch, fail_post):
    """Con la IA encendida pero el proveedor fallando, el POST al endpoint responde 200
    con la respuesta DETERMINISTA de la skill (cifra real) y ai_used=False — nunca 500."""
    client, _ = _mk(["hr.employee.read"], employees=3)
    _ai_on(monkeypatch, chatmod)
    monkeypatch.setattr(chatmod.requests, "post", fail_post)

    r = client.post(
        "/api/knowledge/chat/",
        {"messages": [{"role": "user", "content": "cuántos empleados hay"}]},
        format="json",
    )
    assert r.status_code == 200, r.data            # NO 500 crudo
    assert r.data["ai_used"] is False              # degradó: no usó el LLM
    # El plan LLM también falló → cae al fast-path determinista, que sí enruta la skill.
    assert r.data["used_skills"] == ["rh.empleados_total"]
    assert "3" in (r.data["reply"] or "")          # cifra real, no inventada


@pytest.mark.django_db
def test_chat_endpoint_sin_evidencia_no_inventa(monkeypatch):
    """Proveedor caído + sin skill ni docs: respuesta honesta de 'no encontré dato',
    sin números inventados, 200."""
    client, _ = _mk([])  # sin permisos de skill
    _ai_on(monkeypatch, chatmod)
    monkeypatch.setattr(chatmod.requests, "post", _conn_refused_post)

    r = client.post(
        "/api/knowledge/chat/",
        {"messages": [{"role": "user", "content": "cuál es la distancia de la Tierra a la Luna"}]},
        format="json",
    )
    assert r.status_code == 200, r.data
    assert r.data["ai_used"] is False
    assert r.data["used_skills"] == []
    # Mensaje determinista honesto (de _fallback_reply); sin trivia ni cifras inventadas.
    assert "No encontré" in (r.data["reply"] or "")


@pytest.mark.django_db
def test_chat_plan_falla_pero_compose_funciona_no_explota(monkeypatch):
    """El PLAN del LLM revienta (think sin cerrar → JSON vacío) pero el COMPOSE responde
    bien: el sistema cae al plan determinista para la evidencia y compone con el LLM."""
    client, _ = _mk(["hr.employee.read"], employees=2)
    _ai_on(monkeypatch, chatmod)

    def mixed_post(url, json=None, timeout=None, **kw):
        system = (json or {}).get("messages", [{}])[0].get("content", "")
        if "planificador" in system:           # plan: devuelve basura sin JSON usable
            return _FakeResp("<think> no cierro el bloque y no doy json")
        return _FakeResp("Actualmente hay 2 empleados activos.")  # compose ok

    monkeypatch.setattr(chatmod.requests, "post", mixed_post)
    r = client.post(
        "/api/knowledge/chat/",
        {"messages": [{"role": "user", "content": "cuántos empleados hay"}]},
        format="json",
    )
    assert r.status_code == 200, r.data
    assert r.data["used_skills"] == ["rh.empleados_total"]   # fast-path determinista del plan
    assert "2" in (r.data["reply"] or "")


# --------------------------------------------------------------------------- #
# (3) assistant._route_with_llm — endpoint /api/knowledge/assistant/
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
@pytest.mark.parametrize("fail_post", PROVIDER_FAILURES)
def test_assistant_endpoint_degrada_con_proveedor_fallando(monkeypatch, fail_post):
    """Pregunta sin match determinista → intenta el router LLM; el proveedor falla →
    cae a documentación. 200, sin dato inventado."""
    client, _ = _mk(["hr.employee.read"])
    _ai_on(monkeypatch, assistantmod)
    monkeypatch.setattr(assistantmod.requests, "post", fail_post)
    # 'xyzzy' no dispara ninguna skill por keyword → fuerza el router LLM, que falla.
    r = client.get("/api/knowledge/assistant/", {"q": "xyzzy reporte raro inexistente"})
    assert r.status_code == 200, r.data
    assert r.data["kind"] == "docs"     # degradó a la búsqueda en el manual
    assert r.data["ai_used"] is False   # la síntesis del LLM tampoco corrió


@pytest.mark.django_db
def test_strip_reasoning_think_sin_cerrar_no_explota():
    """Guard unitario del parser: <think> sin cerrar y markdown roto no lanzan."""
    # synthesis._strip_reasoning: se queda con lo de después de </think>; sin cierre, devuelve crudo strip.
    assert isinstance(synthmod._strip_reasoning("<think> sin cerrar `code **bold"), str)
    assert synthmod._strip_reasoning("razonó</think>respuesta final").strip() == "respuesta final"
    # assistant._strip_reasoning idéntico contrato.
    assert isinstance(assistantmod._strip_reasoning("<think> roto"), str)
