# Identidad de sync (Lote 4 — Facturación): sync_uid (ULID) + origin_node en
# SalesOrder, SalesOrderLine, BillingDocument, BillingLine y BillingPayment.
# Migración data-safe (AddField NULL → backfill ULIDs únicos + registro en el mapa
# → unique + NOT NULL). Mismo patrón que nomina/0015.
import apps.modulos.common.sync_identity as sync_identity
from django.db import migrations, models

_TARGETS = ["salesorder", "salesorderline", "billingdocument", "billingline", "billingpayment"]


def fill_sync_uid(apps, schema_editor):
    SyncIdentity = apps.get_model("common", "SyncIdentity")
    node = sync_identity.current_node_code()
    for model_name in _TARGETS:
        Model = apps.get_model("facturacion", model_name)
        label = f"facturacion.{model_name}"
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
        ('facturacion', '0009_billingdocument_credited_total_and_more'),
        ('common', '0001_initial'),
    ]

    operations = [
        migrations.AddField(model_name='salesorder', name='origin_node', field=_origin_node_field()),
        migrations.AddField(model_name='salesorder', name='sync_uid', field=_sync_uid_temp()),
        migrations.AddField(model_name='salesorderline', name='origin_node', field=_origin_node_field()),
        migrations.AddField(model_name='salesorderline', name='sync_uid', field=_sync_uid_temp()),
        migrations.AddField(model_name='billingdocument', name='origin_node', field=_origin_node_field()),
        migrations.AddField(model_name='billingdocument', name='sync_uid', field=_sync_uid_temp()),
        migrations.AddField(model_name='billingline', name='origin_node', field=_origin_node_field()),
        migrations.AddField(model_name='billingline', name='sync_uid', field=_sync_uid_temp()),
        migrations.AddField(model_name='billingpayment', name='origin_node', field=_origin_node_field()),
        migrations.AddField(model_name='billingpayment', name='sync_uid', field=_sync_uid_temp()),
        migrations.RunPython(fill_sync_uid, noop_reverse),
        migrations.AlterField(model_name='salesorder', name='sync_uid', field=_sync_uid_final()),
        migrations.AlterField(model_name='salesorderline', name='sync_uid', field=_sync_uid_final()),
        migrations.AlterField(model_name='billingdocument', name='sync_uid', field=_sync_uid_final()),
        migrations.AlterField(model_name='billingline', name='sync_uid', field=_sync_uid_final()),
        migrations.AlterField(model_name='billingpayment', name='sync_uid', field=_sync_uid_final()),
    ]
