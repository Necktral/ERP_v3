import hashlib

from django.db import migrations, models
from django.db.migrations.exceptions import IrreversibleError


def retire_plaintext_tokens(apps, schema_editor):
    BiometricDevice = apps.get_model("nomina", "BiometricDevice")
    # Cubre dispositivos creados por una versión anterior durante la ventana
    # 0020: ningún plaintext se retira antes de materializar su hash.
    for device in BiometricDevice.objects.filter(api_token_hash__isnull=True).only("pk", "api_token").iterator():
        raw_token = str(device.api_token or "")
        if not raw_token:
            raise RuntimeError(f"BiometricDevice {device.pk} no tiene credencial migrable.")
        BiometricDevice.objects.filter(pk=device.pk).update(
            api_token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        )
    BiometricDevice.objects.exclude(api_token="").update(api_token="")


def block_unsafe_legacy_rollback(apps, schema_editor):
    raise IrreversibleError(
        "0021 eliminó los tokens biométricos en texto claro. No revierta a código legacy: "
        "restaure un backup anterior a 0021 o mantenga el código hash-aware y rote las credenciales."
    )


class Migration(migrations.Migration):
    dependencies = [("nomina", "0020_hash_biometric_device_tokens")]

    operations = [
        migrations.RunPython(retire_plaintext_tokens, block_unsafe_legacy_rollback),
        migrations.AlterField(
            model_name="biometricdevice",
            name="api_token_hash",
            field=models.CharField(editable=False, max_length=64, unique=True),
        ),
        migrations.AlterField(
            model_name="biometricdevice",
            name="api_token",
            field=models.CharField(blank=True, default="", editable=False, max_length=64),
        ),
        migrations.AddConstraint(
            model_name="biometricdevice",
            constraint=models.CheckConstraint(
                condition=models.Q(api_token=""), name="ck_biometric_token_plaintext_empty"
            ),
        ),
    ]
