"""Tests del asistente CONVERSACIONAL (multi-turno).

Hermético: en `config.settings.test` la IA está apagada → el chat degrada a la respuesta determinista
de la skill (sin llamar al LLM). El camino con LLM se prueba mockeando la red.
"""
from __future__ import annotations

import uuid

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.modulos.hr.models import Employee
from apps.modulos.iam.models import OrgUnit, UserMembership
from apps.modulos.knowledge import chat as chatmod
from apps.modulos.rbac.models import Permission, Role, RoleAssignment, RolePermission

User = get_user_model()
UT = OrgUnit.UnitType
BASE = "knowledge.docs.read"


def _mk(perm_codes, *, employees=0):
    t = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=UT.HOLDING, name=f"H{t}")
    company = OrgUnit.objects.create(unit_type=UT.COMPANY, name=f"Empresa{t}", parent=holding)
    user = User.objects.create_user(username=f"ch_{t}", email=f"ch_{t}@t.local", password="pass12345")
    UserMembership.objects.create(user=user, org_unit=company, is_active=True)
    role = Role.objects.create(name=f"ch_role_{t}", is_active=True)
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


def _chat(client, messages):
    r = client.post("/api/knowledge/chat/", {"messages": messages}, format="json")
    assert r.status_code == 200, r.data
    return r.data


@pytest.mark.django_db
def test_chat_ia_off_degrada_a_respuesta_determinista():
    client, _ = _mk(["hr.employee.read"], employees=3)
    data = _chat(client, [{"role": "user", "content": "cuántos empleados hay"}])
    assert data["ai_used"] is False           # IA apagada en tests
    assert data["used_skills"] == ["rh.empleados_total"]
    assert "3" in (data["reply"] or "")       # la cifra real de la skill


@pytest.mark.django_db
def test_chat_endpoint_valida_messages():
    client, _ = _mk([])
    r = client.post("/api/knowledge/chat/", {"messages": []}, format="json")
    assert r.status_code == 400


@pytest.mark.django_db
def test_chat_seguridad_skill_sin_permiso_no_se_ejecuta():
    # Sin hr.employee.read la skill no está disponible → no se ejecuta (cae a docs).
    client, _ = _mk([], employees=3)
    data = _chat(client, [{"role": "user", "content": "cuántos empleados hay"}])
    assert "rh.empleados_total" not in data["used_skills"]


class _FakeResp:
    def __init__(self, content):
        self._content = content

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


@pytest.mark.django_db
def test_chat_con_llm_compone_desde_la_evidencia(monkeypatch):
    client, _ = _mk(["hr.employee.read"], employees=3)

    monkeypatch.setattr(chatmod, "ai_features_enabled", lambda: True)
    monkeypatch.setattr(chatmod, "_llm_config", lambda: ("http://fake", "m", 1.0))

    def fake_post(url, json=None, timeout=None, **kw):
        system = (json or {}).get("messages", [{}])[0].get("content", "")
        if "planificador" in system:      # _PLAN_SYSTEM
            return _FakeResp('{"skills": ["rh.empleados_total"], "docs": false}')
        # _SYSTEM (compose): redacta usando la evidencia (el último mensaje trae el contexto)
        return _FakeResp("Actualmente tenés 3 empleados activos en la empresa.")

    monkeypatch.setattr(chatmod.requests, "post", fake_post)

    data = _chat(client, [{"role": "user", "content": "cuántos empleados hay"}])
    assert data["ai_used"] is True
    assert data["used_skills"] == ["rh.empleados_total"]
    assert "3" in data["reply"]


@pytest.mark.django_db
def test_chat_sin_contexto_instruye_declinar(monkeypatch):
    # Pregunta ajena al ERP (sin skill ni docs): el motor debe inyectar la directiva de declinar
    # al LLM, para que NO responda con conocimiento general ni invente cifras.
    client, _ = _mk([])

    monkeypatch.setattr(chatmod, "ai_features_enabled", lambda: True)
    monkeypatch.setattr(chatmod, "_llm_config", lambda: ("http://fake", "m", 1.0))

    captured: dict = {}

    def fake_post(url, json=None, timeout=None, **kw):
        system = (json or {}).get("messages", [{}])[0].get("content", "")
        if "planificador" in system:      # _PLAN_SYSTEM → no elige skills, sin docs
            return _FakeResp('{"skills": [], "docs": false}')
        captured["user"] = (json or {}).get("messages", [])[-1].get("content", "")
        return _FakeResp("No tengo ese dato en el sistema.")

    monkeypatch.setattr(chatmod.requests, "post", fake_post)

    data = _chat(client, [{"role": "user", "content": "cuál es la distancia de la Tierra a la Luna"}])
    assert data["used_skills"] == []
    assert "conocimiento general" in captured["user"]   # la directiva llegó al LLM
    assert "inventes cifras" in captured["user"]


@pytest.mark.django_db
def test_chat_multiturno_pasa_historial():
    # Un follow-up: el segundo turno enruta a su propia skill (el historial llega al motor).
    client, _ = _mk(["hr.employee.read", "billing.invoice.read"], employees=2)
    hist = [
        {"role": "user", "content": "cuántos empleados hay"},
        {"role": "assistant", "content": "Hay 2 empleados."},
        {"role": "user", "content": "cuánto vendí hoy"},
    ]
    data = _chat(client, hist)
    assert data["used_skills"] == ["ventas.hoy"]
    assert data["ai_used"] is False
