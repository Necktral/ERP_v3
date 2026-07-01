# Identidad de sync (Lote 6 — Nómina/asistencia): sync_uid (ULID) + origin_node en
# PayrollEntry, AttendanceReport y los eventos de captura de campo (FieldRollCall,
# FieldCrewReport, FieldWorkerEvent). Migración data-safe (AddField NULL → backfill
# ULIDs únicos + registro en el mapa → unique + NOT NULL). Mismo patrón que nomina/0015.
import apps.modulos.common.sync_identity as sync_identity
from django.db import migrations, models

_TARGETS = ["payrollentry", "attendancereport", "fieldrollcall", "fieldcrewreport", "fieldworkerevent"]


def fill_sync_uid(apps, schema_editor):
    SyncIdentity = apps.get_model("common", "SyncIdentity")
    node = sync_identity.current_node_code()
    for model_name in _TARGETS:
        Model = apps.get_model("nomina", model_name)
        label = f"nomina.{model_name}"
        for pk in list(Model.objects.filter(sync_uid__isnull=True).values_list("pk", flat=True)):
            uid = sync_identity.new_ulid()
            Model.objects.filter(pk=pk).update(sync_uid=uid)
            SyncIdentity.objects.get_or_create(
                model_label=label,
                sync_uid=uid,
                defaults={"local_id": pk, "origin_node": node},
            )


def noop_reverse(apps, schema_editor):
    pass


def _origin_node_field():
    return models.CharField(
        default=sync_identity.current_node_code,
        editable=False,
        help_text="Código del nodo que creó la fila.",
        max_length=40,
    )


def _sync_uid_temp():
    return models.CharField(
        editable=False,
        help_text="Identidad global de la fila entre nodos (ULID).",
        max_length=26,
        null=True,
    )


def _sync_uid_final():
    return models.CharField(
        default=sync_identity.new_ulid,
        editable=False,
        help_text="Identidad global de la fila entre nodos (ULID).",
        max_length=26,
        unique=True,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('nomina', '0015_payrollpayment_origin_node_payrollpayment_sync_uid'),
        ('common', '0001_initial'),
    ]

    operations = [
        migrations.AddField(model_name='payrollentry', name='origin_node', field=_origin_node_field()),
        migrations.AddField(model_name='payrollentry', name='sync_uid', field=_sync_uid_temp()),
        migrations.AddField(model_name='attendancereport', name='origin_node', field=_origin_node_field()),
        migrations.AddField(model_name='attendancereport', name='sync_uid', field=_sync_uid_temp()),
        migrations.AddField(model_name='fieldrollcall', name='origin_node', field=_origin_node_field()),
        migrations.AddField(model_name='fieldrollcall', name='sync_uid', field=_sync_uid_temp()),
        migrations.AddField(model_name='fieldcrewreport', name='origin_node', field=_origin_node_field()),
        migrations.AddField(model_name='fieldcrewreport', name='sync_uid', field=_sync_uid_temp()),
        migrations.AddField(model_name='fieldworkerevent', name='origin_node', field=_origin_node_field()),
        migrations.AddField(model_name='fieldworkerevent', name='sync_uid', field=_sync_uid_temp()),
        migrations.RunPython(fill_sync_uid, noop_reverse),
        migrations.AlterField(model_name='payrollentry', name='sync_uid', field=_sync_uid_final()),
        migrations.AlterField(model_name='attendancereport', name='sync_uid', field=_sync_uid_final()),
        migrations.AlterField(model_name='fieldrollcall', name='sync_uid', field=_sync_uid_final()),
        migrations.AlterField(model_name='fieldcrewreport', name='sync_uid', field=_sync_uid_final()),
        migrations.AlterField(model_name='fieldworkerevent', name='sync_uid', field=_sync_uid_final()),
    ]
