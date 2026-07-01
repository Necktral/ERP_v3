# Identidad de sync (Lote 1 — POS): sync_uid (ULID) + origin_node en PosSession,
# PosTicket y PosTicketLine. Migración data-safe para filas existentes: sync_uid se
# agrega NULL, se rellena por fila con un ULID único (+ registro en el mapa de
# identidad) y recién entonces se vuelve único + NOT NULL. Mismo patrón que nomina/0015.
import apps.modulos.common.sync_identity as sync_identity
from django.db import migrations, models

_TARGETS = ["possession", "posticket", "posticketline"]


def fill_sync_uid(apps, schema_editor):
    SyncIdentity = apps.get_model("common", "SyncIdentity")
    node = sync_identity.current_node_code()
    for model_name in _TARGETS:
        Model = apps.get_model("retail_pos", model_name)
        label = f"retail_pos.{model_name}"
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
        ('retail_pos', '0005_posticket_customer_party'),
        ('common', '0001_initial'),
    ]

    operations = [
        # 1) origin_node (default callable: ok, no es único) + sync_uid temporal NULL
        migrations.AddField(model_name='possession', name='origin_node', field=_origin_node_field()),
        migrations.AddField(model_name='possession', name='sync_uid', field=_sync_uid_temp()),
        migrations.AddField(model_name='posticket', name='origin_node', field=_origin_node_field()),
        migrations.AddField(model_name='posticket', name='sync_uid', field=_sync_uid_temp()),
        migrations.AddField(model_name='posticketline', name='origin_node', field=_origin_node_field()),
        migrations.AddField(model_name='posticketline', name='sync_uid', field=_sync_uid_temp()),
        # 2) rellenar ULIDs únicos por fila + registrar en el mapa de identidad
        migrations.RunPython(fill_sync_uid, noop_reverse),
        # 3) único + NOT NULL + default para filas nuevas
        migrations.AlterField(model_name='possession', name='sync_uid', field=_sync_uid_final()),
        migrations.AlterField(model_name='posticket', name='sync_uid', field=_sync_uid_final()),
        migrations.AlterField(model_name='posticketline', name='sync_uid', field=_sync_uid_final()),
    ]
