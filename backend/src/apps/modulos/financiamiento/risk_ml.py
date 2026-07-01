"""Capa OPCIONAL de Random Forest para la probabilidad de mora (PD).

Contrato "degrada honesto" (igual que cec/ai_explainer): `predict_pd` devuelve `None` —y el motor
determinista usa la heurística— si CUALQUIERA de estas falla:
  - el kill switch de IA está apagado (`ai_features_enabled()` False),
  - `scikit-learn`/`joblib` no están instalados (deps OPCIONALES),
  - no hay un modelo entrenado en disco.

El modelo se entrena offline con el management command `train_credit_risk` y se persiste como
`.joblib`. `extract_features` define el orden de columnas y lo comparten serving y entrenamiento.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from django.conf import settings

from apps.modulos.diagnostics.flags import ai_features_enabled

# Orden ESTABLE de features (serving y entrenamiento deben coincidir).
FEATURE_ORDER: tuple[str, ...] = (
    "monto",
    "plazo_meses",
    "tasa_interes",
    "tasa_penalidad",
    "garantia_cafe_qq",
    "garantia_finca_mz",
    "prestamos_previos",
    "tasa_mora_historica",
    "dias_atraso",
)


def model_path() -> str:
    """Ruta del modelo entrenado. Configurable por `CREDIT_RISK_MODEL_PATH`."""
    configured = str(getattr(settings, "CREDIT_RISK_MODEL_PATH", "") or "").strip()
    if configured:
        return configured
    base = str(getattr(settings, "BASE_DIR", "") or os.getcwd())
    return os.path.join(base, "var", "models", "credit_risk_rf.joblib")


@lru_cache(maxsize=1)
def _load_model(path: str, mtime: float):  # mtime en la clave → recarga al reentrenar
    import joblib

    return joblib.load(path)


def _get_model():
    try:
        import joblib  # noqa: F401
    except Exception:
        return None
    path = model_path()
    if not os.path.exists(path):
        return None
    try:
        return _load_model(path, os.path.getmtime(path))
    except Exception:
        return None


def extract_features(
    *,
    loan,
    ead,
    days_overdue: int,
    producer_default_rate: float,
    prestamos_previos: int,
    garantia_cafe_qq,
    garantia_finca_mz,
) -> dict[str, float]:
    """Vector de features de un préstamo (mismo para predecir y para entrenar)."""
    return {
        "monto": float(ead),
        "plazo_meses": float(loan.term_months or 0),
        "tasa_interes": float(loan.interest_rate or 0),
        "tasa_penalidad": float(loan.penalty_rate or 0),
        "garantia_cafe_qq": float(garantia_cafe_qq or 0),
        "garantia_finca_mz": float(garantia_finca_mz or 0),
        "prestamos_previos": float(prestamos_previos),
        "tasa_mora_historica": float(producer_default_rate),
        "dias_atraso": float(days_overdue),
    }


def predict_pd(features: dict[str, Any]) -> float | None:
    """PD del Random Forest, o `None` si la IA está apagada / no hay modelo / no hay sklearn."""
    if not ai_features_enabled():
        return None
    try:
        import sklearn  # noqa: F401
    except Exception:
        return None
    model = _get_model()
    if model is None:
        return None
    try:
        row = [[float(features.get(k, 0.0)) for k in FEATURE_ORDER]]
        proba = model.predict_proba(row)[0]
        classes = list(getattr(model, "classes_", [0, 1]))
        idx = classes.index(1) if 1 in classes else len(proba) - 1
        pd = float(proba[idx])
        return min(1.0, max(0.0, pd))
    except Exception:
        return None
