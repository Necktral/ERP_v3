"""Entrena (offline) el Random Forest de probabilidad de mora de préstamos a productores.

OPCIONAL: requiere `scikit-learn`+`joblib` (ver `backend/requirements-optional.txt`). Si no están,
o no hay suficiente histórico, el sistema sigue funcionando con la heurística determinista de
`risk.py` — este comando solo MEJORA la PD cuando hay datos. Etiqueta: un préstamo es "mora" si
alguno de sus créditos quedó en estado OVERDUE/WRITTEN_OFF.

Determinista (random_state fijo). El modelo serializado se guarda en `risk_ml.model_path()` y solo
se usa al servir si el kill switch de IA está encendido.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone as dt_timezone

from django.core.management.base import BaseCommand

from apps.modulos.diagnostics.flags import ai_features_enabled
from apps.modulos.financiamiento import risk, risk_ml
from apps.modulos.financiamiento.models import FinancingLoan


class Command(BaseCommand):
    help = (
        "Entrena el Random Forest de mora de préstamos (offline, opcional). Degrada a la heurística "
        "si faltan datos o sklearn. La PD del modelo solo se usa con el kill switch de IA encendido."
    )

    def add_arguments(self, parser):
        parser.add_argument("--company", type=int, default=None, help="Limitar a una empresa (OrgUnit id).")
        parser.add_argument("--min-samples", type=int, default=30, help="Mínimo de préstamos para entrenar.")
        parser.add_argument("--force", action="store_true", help="Entrenar aunque la IA esté apagada.")
        parser.add_argument("--dry-run", action="store_true", help="Solo reportar el dataset, sin entrenar.")

    def handle(self, *args, **options):
        if not ai_features_enabled() and not options["force"]:
            self.stderr.write(
                "IA apagada (kill switch). El modelo no se usará al servir hasta encenderla. "
                "Usá --force para entrenar igual."
            )
            return

        try:
            import joblib
            from sklearn.ensemble import RandomForestClassifier
        except Exception:
            self.stderr.write(
                "scikit-learn/joblib no instalados. Instalá: pip install -r requirements-optional.txt "
                "(el sistema sigue usando la heurística determinista)."
            )
            return

        X, y = self._build_dataset(company_id=options["company"])
        n = len(y)
        n_mora = sum(y)
        self.stdout.write(f"Dataset: {n} préstamos, {n_mora} en mora, {n - n_mora} sanos.")

        if n < options["min_samples"]:
            self.stderr.write(
                f"Datos insuficientes ({n} < {options['min_samples']}). Se usa la heurística determinista."
            )
            return
        if n_mora == 0 or n_mora == n:
            self.stderr.write("Se necesita al menos un ejemplo de cada clase (mora y sano). Abortado.")
            return
        if options["dry_run"]:
            self.stdout.write(self.style.SUCCESS("Dry-run: dataset OK, no se entrenó."))
            return

        model = RandomForestClassifier(
            n_estimators=200, random_state=42, class_weight="balanced", n_jobs=1
        )
        model.fit(X, y)

        path = risk_ml.model_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        joblib.dump(model, path)
        meta = {
            "trained_at": datetime.now(dt_timezone.utc).isoformat(),
            "n_samples": n,
            "n_mora": n_mora,
            "features": list(risk_ml.FEATURE_ORDER),
            "version": 1,
        }
        with open(path + ".meta.json", "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2)
        self.stdout.write(self.style.SUCCESS(f"Modelo entrenado y guardado en {path} (n={n})."))

    def _build_dataset(self, *, company_id):
        """Construye (X, y) con las MISMAS features que el serving (`risk_ml.extract_features`)."""
        loans = FinancingLoan.objects.select_related(
            "producer", "credit_nio", "credit_usd", "application"
        )
        if company_id:
            loans = loans.filter(company_id=company_id)

        rows: list[list[float]] = []
        labels: list[int] = []
        fx_cache: dict[int, object] = {}
        for loan in loans:
            credits = [c for c in (loan.credit_nio, loan.credit_usd) if c is not None]
            if not credits:
                continue
            fx = fx_cache.get(loan.company_id)
            if fx is None:
                fx = risk._fx_rate(loan.company)
                fx_cache[loan.company_id] = fx
            ead = risk._consolidated_ead(loan, fx=fx)
            if ead <= 0:
                continue
            status, days_overdue = risk._worst_credit_view(loan)
            producer_dr, prestamos_previos = risk._producer_default_rate(loan)
            app = loan.application
            features = risk_ml.extract_features(
                loan=loan,
                ead=ead,
                days_overdue=days_overdue,
                producer_default_rate=producer_dr,
                prestamos_previos=prestamos_previos,
                garantia_cafe_qq=getattr(app, "guarantee_coffee_qq", 0) if app else 0,
                garantia_finca_mz=getattr(app, "guarantee_farm_area_mz", 0) if app else 0,
            )
            rows.append([float(features[k]) for k in risk_ml.FEATURE_ORDER])
            labels.append(1 if str(status) in risk._MORA_STATES else 0)
        return rows, labels
