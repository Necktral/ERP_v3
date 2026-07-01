"""Tests del chatter: notas append-only, scoping por empresa y validación de la API."""
from __future__ import annotations

import uuid

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.modulos.chatter.models import RecordNote
from apps.modulos.chatter.views import NotesView
from apps.modulos.iam.models import OrgUnit

User = get_user_model()
UT = OrgUnit.UnitType


def _scope():
    t = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=UT.HOLDING, name=f"H{t}", code=f"H-{t}")
    company = OrgUnit.objects.create(unit_type=UT.COMPANY, parent=holding, name=f"C{t}", code=f"C-{t}")
    return holding, company


def _user():
    t = uuid.uuid4().hex[:8]
    return User.objects.create_user(username=f"u_{t}", email=f"u_{t}@t.local", password="pass12345")


class _OpenNotesView(NotesView):
    """Subclase de test: salta SOLO la capa de permisos RBAC (tiene su propia suite);
    el scoping por empresa de la vista SÍ se ejercita."""

    def get_permissions(self):
        return []


def _call(view, request, company, user):
    request.company = company
    request.branch = None
    force_authenticate(request, user=user)
    return view.as_view()(request)


@pytest.mark.django_db
def test_crear_y_listar_notas_por_registro():
    _h, company = _scope()
    user = _user()
    rf = APIRequestFactory()

    resp = _call(_OpenNotesView, rf.post("/api/chatter/notes/", {
        "subject_type": "FINANCING_LOAN", "subject_id": "7", "body": "Productor avisó que paga el viernes.",
    }, format="json"), company, user)
    assert resp.status_code == 201, resp.data

    resp = _call(_OpenNotesView, rf.get("/api/chatter/notes/?subject_type=FINANCING_LOAN&subject_id=7"),
                 company, user)
    assert resp.status_code == 200
    assert len(resp.data["results"]) == 1
    assert resp.data["results"][0]["author"] == user.username


@pytest.mark.django_db
def test_scoping_por_empresa_no_filtra_notas_ajenas():
    _h1, company_a = _scope()
    _h2, company_b = _scope()
    user = _user()
    RecordNote.objects.create(company=company_a, subject_type="X", subject_id="1",
                              body="nota de A", created_by=user)
    rf = APIRequestFactory()
    resp = _call(_OpenNotesView, rf.get("/api/chatter/notes/?subject_type=X&subject_id=1"),
                 company_b, user)
    assert resp.status_code == 200
    assert resp.data["results"] == []  # la empresa B no ve notas de A


@pytest.mark.django_db
def test_validaciones_de_forma():
    _h, company = _scope()
    user = _user()
    rf = APIRequestFactory()
    # GET sin subject → 400
    resp = _call(_OpenNotesView, rf.get("/api/chatter/notes/"), company, user)
    assert resp.status_code == 400
    # POST sin body → 422 (el handler del proyecto envuelve la validación del serializer)
    resp = _call(_OpenNotesView, rf.post("/api/chatter/notes/", {
        "subject_type": "X", "subject_id": "1", "body": "   ",
    }, format="json"), company, user)
    assert resp.status_code == 422
