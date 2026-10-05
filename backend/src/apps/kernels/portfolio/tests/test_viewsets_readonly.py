"""
BUG-I1 (bug-hunt de integridad): los ViewSets de obligaciones de portfolio
(CxC, CxP, Créditos, Aplicaciones) deben ser SOLO LECTURA. El create/update por
defecto de un ModelViewSet aceptaba FKs (party, restructured_from, payment_intent,
obligación) de CUALQUIER empresa, permitiendo mezclar cuentas entre compañías.
Las obligaciones se crean exclusivamente por servicios scopeados por empresa.
"""
from __future__ import annotations

from rest_framework.viewsets import ReadOnlyModelViewSet

from apps.kernels.portfolio.views import (
    CreditViewSet,
    PaymentAllocationViewSet,
    PayableViewSet,
    ReceivableViewSet,
)

_ESCRITURA = ("create", "update", "partial_update", "destroy")


def test_viewsets_de_obligaciones_son_solo_lectura():
    for vs in (ReceivableViewSet, PayableViewSet, CreditViewSet, PaymentAllocationViewSet):
        assert issubclass(vs, ReadOnlyModelViewSet), f"{vs.__name__} debe ser ReadOnly"
        for verbo in _ESCRITURA:
            assert not hasattr(vs, verbo), f"{vs.__name__} no debe exponer {verbo} (fuga cross-company BUG-I1/011)"


def test_acciones_de_servicio_siguen_disponibles():
    # Las operaciones legítimas (por servicio scopeado) se conservan como @action.
    assert hasattr(ReceivableViewSet, "adjust")
    assert hasattr(ReceivableViewSet, "writeoff")
    assert hasattr(CreditViewSet, "disburse")
