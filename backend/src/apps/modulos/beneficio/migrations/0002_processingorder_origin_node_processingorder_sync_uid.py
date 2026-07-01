# Identidad de sync (Lote 7 — Beneficio): sync_uid (ULID) + origin_node en ProcessingOrder.
# Migración data-safe (AddField NULL → backfill ULIDs únicos + registro en el mapa
# → unique + NOT NULL). Mismo patrón que nomina/0015.
import apps.modulos.common.sync_identity as sync_identity
from django.db import migrations, models


def fill_sync_uid(apps, schema_editor):
    ProcessingOrder = apps.get_model("beneficio", "processingorder")
    SyncIdentity = apps.get_model("common", "SyncIdentity")
    node = sync_identity.current_node_code()
    label = "beneficio.processingorder"
    for pk in list(ProcessingOrder.objects.filter(sync_uid__isnull=True).values_list("pk", flat=True)):
        uid = sync_identity.new_ulid()
        ProcessingOrder.objects.filter(pk=pk).update(sync_uid=uid)
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
        ('beneficio', '0001_initial'),
        ('common', '0001_initial'),
    ]

    operations = [
        migrations.AddField(model_name='processingorder', name='origin_node', field=_origin_node_field()),
        migrations.AddField(model_name='processingorder', name='sync_uid', field=_sync_uid_temp()),
        migrations.RunPython(fill_sync_uid, noop_reverse),
        migrations.AlterField(model_name='processingorder', name='sync_uid', field=_sync_uid_final()),
    ]
