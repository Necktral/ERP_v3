"""Tests del corpus de CÓDIGO del asistente de desarrollo (índice + retrieval + endpoint).

Fijan: el chunking de código determinista por ventanas de líneas; el AISLAMIENTO de corpus
(el asistente de usuario final por docs NUNCA ve código y una reingesta de código no poda los
docs); el gating del permiso `knowledge.dev.read` en el endpoint dev; y la degradación del
feedback IA (kill switch / sin URL / LLM caído → None, sin romper el retrieval). LLM mockeado.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.modulos.iam.models import OrgUnit, UserMembership
from apps.modulos.knowledge import code_feedback as cf_mod
from apps.modulos.knowledge.code_feedback import synthesize_code_feedback
from apps.modulos.knowledge.ingest import chunk_code, ingest_code_corpus, ingest_corpus
from apps.modulos.knowledge.models import KnowledgeChunk
from apps.modulos.knowledge import dev_chat as dc_mod
from apps.modulos.knowledge.dev_chat import answer_dev_chat
from apps.modulos.knowledge.dev_export import build_feedback_markdown, default_filename
from apps.modulos.knowledge.search import search_code, search_docs
from apps.modulos.rbac.models import Permission, Role, RoleAssignment, RolePermission

User = get_user_model()

_PY = '''\
def record_dispense(shift, liters):
    """Despacha combustible y descuenta del tanque."""
    tank = shift.tank
    tank.level -= liters
    tank.save()
    return tank.level
'''

_DOC = "# Política de caja\n\nEl cierre de caja requiere conteo físico y aprobación.\n"


def _mk_code_repo(tmp_path, *, rel="backend/src/apps/modulos/estacion_servicios/services.py", text=_PY):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return tmp_path


def _mk_docs(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "p.md").write_text(_DOC, encoding="utf-8")
    return tmp_path


# --- Chunking de código (puro) -------------------------------------------------------

def test_chunk_code_determinista_con_heading_de_simbolo():
    chunks = chunk_code(_PY)
    assert chunks
    assert chunks == chunk_code(_PY)  # determinista
    assert chunks[0].heading.startswith("def record_dispense")
    assert "tank.level" in chunks[0].content


def test_chunk_code_parte_en_ventanas_de_lineas():
    text = "\n".join(f"asignacion_{i} = {i}" for i in range(400))
    chunks = chunk_code(text)
    assert len(chunks) >= 3  # 400 líneas / 150 por ventana → 3 ventanas
    assert any(c.heading.startswith("L") for c in chunks)  # sin símbolo → heading por rango


def test_chunk_code_vacio_no_rompe():
    assert chunk_code("") == []
    assert chunk_code("   \n  \n") == []


# --- Aislamiento de corpus -----------------------------------------------------------

@pytest.mark.django_db
def test_corpus_aislados(tmp_path):
    _mk_docs(tmp_path)
    _mk_code_repo(tmp_path)
    ingest_corpus(root=tmp_path)       # docs
    ingest_code_corpus(root=tmp_path)  # code
    assert KnowledgeChunk.objects.filter(corpus="code").exists()
    assert KnowledgeChunk.objects.filter(corpus="docs").exists()

    # El asistente de usuario final (docs) NO devuelve código.
    for hit in search_docs("combustible tanque dispense"):
        assert hit["source_path"].endswith(".md")

    # El asistente de desarrollo (code) encuentra el símbolo y NO devuelve docs.
    code_hits = search_code("record_dispense")
    assert code_hits
    assert all(not h["source_path"].endswith(".md") for h in code_hits)
    assert any("estacion_servicios" in h["source_path"] for h in code_hits)


@pytest.mark.django_db
def test_reingesta_de_codigo_no_poda_los_docs(tmp_path):
    _mk_docs(tmp_path)
    _mk_code_repo(tmp_path)
    ingest_corpus(root=tmp_path)
    docs_antes = KnowledgeChunk.objects.filter(corpus="docs").count()
    assert docs_antes > 0
    ingest_code_corpus(root=tmp_path)  # la poda del corpus 'code' NO debe tocar 'docs'
    assert KnowledgeChunk.objects.filter(corpus="docs").count() == docs_antes


# --- Feedback IA: kill switch + degradación ------------------------------------------

_CODE_RESULTS = [{"source_path": "x.py", "heading": "def f", "content": "def f(): pass", "rank": 0.9}]


def test_feedback_apagado_sin_kill_switch(monkeypatch):
    monkeypatch.setattr(cf_mod, "ai_features_enabled", lambda: False)
    assert synthesize_code_feedback("flujo", _CODE_RESULTS) is None


def test_feedback_sin_url(monkeypatch, settings):
    monkeypatch.setattr(cf_mod, "ai_features_enabled", lambda: True)
    settings.KNOWLEDGE_LLM_BASE_URL = ""
    settings.DIAGNOSTICS_LLM_BASE_URL = ""
    assert synthesize_code_feedback("flujo", _CODE_RESULTS) is None


def test_feedback_degrada_si_llm_falla(monkeypatch, settings):
    monkeypatch.setattr(cf_mod, "ai_features_enabled", lambda: True)
    settings.KNOWLEDGE_LLM_BASE_URL = "http://llm.test:8080"

    def _boom(url, json=None, timeout=None):
        raise cf_mod.requests.ConnectionError("caído")

    monkeypatch.setattr(cf_mod.requests, "post", _boom)
    assert synthesize_code_feedback("flujo", _CODE_RESULTS) is None  # nunca lanza


def test_feedback_responde_con_citas(monkeypatch, settings):
    monkeypatch.setattr(cf_mod, "ai_features_enabled", lambda: True)
    settings.KNOWLEDGE_LLM_BASE_URL = "http://llm.test:8080"

    def _fake_post(url, json=None, timeout=None):
        assert url == "http://llm.test:8080/v1/chat/completions"
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"choices": [{"message": {"content": "Despacha y descuenta del tanque [1]."}}]},
        )

    monkeypatch.setattr(cf_mod.requests, "post", _fake_post)
    out = synthesize_code_feedback("dispense", _CODE_RESULTS)
    assert out is not None
    assert "[1]" in out["text"]
    assert out["sources"][0]["source_path"] == "x.py"


# --- Endpoint dev: gating del permiso ------------------------------------------------

def _mk_client(perm_codes: list[str]) -> APIClient:
    t = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H{t}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, name=f"C{t}", parent=holding)
    user = User.objects.create_user(username=f"dv_{t}", email=f"dv_{t}@t.local", password="pass12345")
    UserMembership.objects.create(user=user, org_unit=company, is_active=True)
    role = Role.objects.create(name=f"dv_role_{t}", is_active=True)
    for code in perm_codes:
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
def test_dev_endpoint_anonimo_o_sin_permiso_no_pasa():
    assert APIClient().get("/api/knowledge/dev/feedback/?q=x").status_code in (401, 403)
    # tener docs NO alcanza: el código exige el permiso de DESARROLLO
    c = _mk_client(["knowledge.docs.read"])
    assert c.get("/api/knowledge/dev/feedback/?q=x").status_code == 403


@pytest.mark.django_db
def test_dev_endpoint_con_permiso_devuelve_codigo_sin_ia(tmp_path):
    _mk_code_repo(tmp_path)
    ingest_code_corpus(root=tmp_path)
    c = _mk_client(["knowledge.dev.read"])
    r = c.get("/api/knowledge/dev/feedback/?q=record_dispense")
    assert r.status_code == 200, r.data
    assert r.data["results"]
    assert r.data["answer"] is None  # kill switch OFF por defecto → sin IA
    assert r.data["ai_used"] is False


@pytest.mark.django_db
def test_dev_endpoint_q_vacio_es_400():
    c = _mk_client(["knowledge.dev.read"])
    assert c.get("/api/knowledge/dev/feedback/").status_code == 400


# --- v2: dev-chat conversacional + export + retrieval por path -----------------------

@pytest.mark.django_db
def test_dev_chat_degrada_sin_ia_y_trae_fragmentos(tmp_path, monkeypatch):
    _mk_code_repo(tmp_path)
    ingest_code_corpus(root=tmp_path)
    monkeypatch.setattr(dc_mod, "ai_features_enabled", lambda: False)
    out = answer_dev_chat(messages=[{"role": "user", "content": "record_dispense"}])
    assert out["ai_used"] is False
    assert out["fragments"]  # el código REAL viaja (fuente de verdad para Claude)
    assert any("estacion_servicios" in p for p in out["used_files"])
    assert "record_dispense" in out["reply"] or "estacion_servicios" in out["reply"]


@pytest.mark.django_db
def test_dev_chat_sin_match_lo_dice(tmp_path, monkeypatch):
    _mk_code_repo(tmp_path)
    ingest_code_corpus(root=tmp_path)
    monkeypatch.setattr(dc_mod, "ai_features_enabled", lambda: False)
    out = answer_dev_chat(messages=[{"role": "user", "content": "zzz_inexistente_qwerty"}])
    assert out["fragments"] == []
    assert "No encontré" in out["reply"]


def test_export_packet_incluye_conversacion_y_codigo_real():
    msgs = [
        {"role": "user", "content": "¿cómo se asigna un cargo?"},
        {"role": "assistant", "content": "Se asigna vía EmploymentAssignment [1]."},
    ]
    frag = {
        "source_path": "backend/src/apps/modulos/hr/services.py",
        "heading": "def reconcile_employee_roles",
        "content": "def reconcile_employee_roles(employee): ...",
    }
    md = build_feedback_markdown(messages=msgs, fragments=[frag, dict(frag)], title="cargo")
    assert "¿cómo se asigna un cargo?" in md
    assert "reconcile_employee_roles" in md
    assert "```" in md  # bloque de código real
    assert md.count("### `backend/src/apps/modulos/hr/services.py`") == 1  # dedup por (path, heading)
    assert default_filename("cargo").startswith("FEEDBACK_cargo_")


@pytest.mark.django_db
def test_retrieval_por_path_tokenizado_encuentra_codigo_ingles(tmp_path):
    # archivo en estacion_servicios con contenido SOLO en inglés → se encuentra por el PATH
    _mk_code_repo(
        tmp_path,
        rel="backend/src/apps/modulos/estacion_servicios/pumps.py",
        text="def dispatch(pump, liters):\n    pump.total += liters\n    return pump.total\n",
    )
    ingest_code_corpus(root=tmp_path)
    hits = search_code("estacion servicios")
    assert hits and any("estacion_servicios" in h["source_path"] for h in hits)
