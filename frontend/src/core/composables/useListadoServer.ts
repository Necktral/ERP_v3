/**
 * Patrón de listado con paginación SERVER-SIDE para q-table.
 * Hermano de useListado (que carga todo de una vez y solo sirve para catálogos
 * cortos): aquí cada página se pide al backend con limit/offset y `rowsNumber`
 * sale del `count` real del envelope {count, limit, offset, results}.
 *
 * Uso típico:
 *   const { rows, loading, pagination, onRequest, reload } =
 *     useListadoServer((p) => listarDocumentos(p));
 *   <q-table :rows="rows" :loading="loading" v-model:pagination="pagination"
 *            @request="onRequest" ... />
 */
import { onMounted, ref, type Ref } from 'vue';
import { Notify } from 'quasar';
import { apiErrorMessage, toPageParams, type PageReq, type Paginated, type QTablePagination } from 'src/core/api';

export interface ListadoServerOptions {
  /** Mensaje si el fetch falla y el backend no dio detalle. */
  errorMessage?: string;
  /** Cargar automáticamente al montar (default true). */
  auto?: boolean;
  /** Filas por página inicial (default 25). */
  rowsPerPage?: number;
}

export interface ListadoServer<T> {
  rows: Ref<T[]>;
  loading: Ref<boolean>;
  pagination: Ref<Required<Pick<QTablePagination, 'page' | 'rowsPerPage' | 'rowsNumber'>> & QTablePagination>;
  /** Handler para @request de q-table (paginación/orden server-side). */
  onRequest: (props: { pagination: QTablePagination }) => Promise<void>;
  /** Re-consulta desde la página 1 (cambio de filtros, alta/baja de filas). */
  reload: () => Promise<void>;
}

export function useListadoServer<T>(
  fetcher: (p: PageReq) => Promise<Paginated<T>>,
  opts: ListadoServerOptions = {},
): ListadoServer<T> {
  const rows = ref<T[]>([]) as Ref<T[]>;
  const loading = ref(false);
  const pagination = ref({
    page: 1,
    rowsPerPage: opts.rowsPerPage ?? 25,
    rowsNumber: 0,
    sortBy: null as string | null,
    descending: false,
  });

  async function fetchPage(p: QTablePagination) {
    loading.value = true;
    try {
      let data = await fetcher(toPageParams(p));
      let page = p.page;
      // Offset fuera de rango (filtró/borró y la página actual ya no existe):
      // volver a la página 1 en vez de pintar un vacío falso.
      if (data.results.length === 0 && data.count > 0 && page > 1) {
        page = 1;
        data = await fetcher(toPageParams({ ...p, page }));
      }
      rows.value = data.results;
      pagination.value = {
        page,
        rowsPerPage: p.rowsPerPage,
        rowsNumber: data.count,
        sortBy: p.sortBy ?? null,
        descending: p.descending ?? false,
      };
    } catch (e) {
      Notify.create({
        type: 'negative',
        message: apiErrorMessage(e, opts.errorMessage ?? 'No se pudo cargar la información.'),
      });
    } finally {
      loading.value = false;
    }
  }

  async function onRequest(props: { pagination: QTablePagination }) {
    await fetchPage(props.pagination);
  }

  /** Re-consulta desde la página 1 (cambio de filtros, alta/baja de filas). */
  async function reload() {
    await fetchPage({ ...pagination.value, page: 1 });
  }

  if (opts.auto !== false) {
    onMounted(reload);
  }

  return { rows, loading, pagination, onRequest, reload };
}
