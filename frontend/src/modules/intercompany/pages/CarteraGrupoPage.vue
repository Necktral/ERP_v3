<template>
  <q-page class="app-page">
    <PageHeader
      title="Cartera de grupo"
      subtitle="Posición de cuentas por cobrar/pagar del holding por empresa, separando lo intercompañía."
      :loading="cargando"
      @refresh="cargar"
    >
      <template #actions>
        <BackButton to="/organizacion" />
      </template>
    </PageHeader>

    <q-banner v-if="!companyIds.length" class="cg-aviso" rounded>
      <template #avatar><q-icon name="info" color="primary" /></template>
      No hay empresas en el grupo para consolidar.
    </q-banner>
    <DataReport v-else :data="data" />
  </q-page>
</template>

<script setup lang="ts">
import BackButton from 'src/components/BackButton.vue';
import DataReport from 'src/components/DataReport.vue';
import { computed, onMounted, ref } from 'vue';
import { useQuasar } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import { apiErrorMessage } from 'src/core/api';
import { getGroupCartera } from 'src/modules/intercompany/api';
import { useAclStore } from 'src/stores/acl.store';

const $q = useQuasar();
const acl = useAclStore();

const cargando = ref(false);
const data = ref<Record<string, unknown> | null>(null);

const companyIds = computed(() => acl.companies.map((c) => Number(c.company_id)).filter((n) => !Number.isNaN(n)));

function nombreEmpresa(id: unknown): string {
  const c = acl.companies.find((x) => String(x.company_id) === String(id));
  return c?.company_name ?? `#${String(id)}`;
}

async function cargar() {
  if (!companyIds.value.length) {
    data.value = null;
    return;
  }
  cargando.value = true;
  try {
    const raw = await getGroupCartera(companyIds.value);
    // Reemplazar company_id por el nombre de empresa para legibilidad.
    const byCompany = Array.isArray(raw.by_company) ? (raw.by_company as Record<string, unknown>[]) : [];
    data.value = {
      ...raw,
      by_company: byCompany.map((r) => {
        const { company_id, ...rest } = r;
        return { empresa: nombreEmpresa(company_id), ...rest };
      }),
    };
  } catch (e) {
    data.value = null;
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cargar la cartera de grupo.') });
  } finally {
    cargando.value = false;
  }
}

onMounted(cargar);
</script>

<style scoped>
.cg-aviso {
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  color: var(--app-text-muted);
}
</style>
