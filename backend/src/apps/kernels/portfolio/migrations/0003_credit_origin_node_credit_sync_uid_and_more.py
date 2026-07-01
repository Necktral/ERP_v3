# Identidad de sync (Lote 5 — Cartera): sync_uid (ULID) + origin_node. El abstracto
# Obligation propaga a Receivable/Payable/Credit; además PaymentAllocation e InterestAccrual.
# Migración data-safe (AddField NULL → backfill ULIDs únicos + registro en el mapa
# → unique + NOT NULL). Mismo patrón que nomina/0015.
import apps.modulos.common.sync_identity as sync_identity
from django.db import migrations, models

_TARGETS = ["receivable", "payable", "credit", "paymentallocation", "interestaccrual"]


def fill_sync_uid(apps, schema_editor):
    SyncIdentity = apps.get_model("common", "SyncIdentity")
    node = sync_identity.current_node_code()
    for model_name in _TARGETS:
        Model = apps.get_model("portfolio", model_name)
        label = f"portfolio.{model_name}"
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
        ('portfolio', '0002_collectionreminder'),
        ('common', '0001_initial'),
    ]

    operations = [
        migrations.AddField(model_name='receivable', name='origin_node', field=_origin_node_field()),
        migrations.AddField(model_name='receivable', name='sync_uid', field=_sync_uid_temp()),
        migrations.AddField(model_name='payable', name='origin_node', field=_origin_node_field()),
        migrations.AddField(model_name='payable', name='sync_uid', field=_sync_uid_temp()),
        migrations.AddField(model_name='credit', name='origin_node', field=_origin_node_field()),
        migrations.AddField(model_name='credit', name='sync_uid', field=_sync_uid_temp()),
        migrations.AddField(model_name='paymentallocation', name='origin_node', field=_origin_node_field()),
        migrations.AddField(model_name='paymentallocation', name='sync_uid', field=_sync_uid_temp()),
        migrations.AddField(model_name='interestaccrual', name='origin_node', field=_origin_node_field()),
        migrations.AddField(model_name='interestaccrual', name='sync_uid', field=_sync_uid_temp()),
        migrations.RunPython(fill_sync_uid, noop_reverse),
        migrations.AlterField(model_name='receivable', name='sync_uid', field=_sync_uid_final()),
        migrations.AlterField(model_name='payable', name='sync_uid', field=_sync_uid_final()),
        migrations.AlterField(model_name='credit', name='sync_uid', field=_sync_uid_final()),
        migrations.AlterField(model_name='paymentallocation', name='sync_uid', field=_sync_uid_final()),
        migrations.AlterField(model_name='interestaccrual', name='sync_uid', field=_sync_uid_final()),
    ]
