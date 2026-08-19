<template>
  <q-page class="app-page caja-page">
    <PageHeader
      title="Caja de Venta"
      subtitle="Escaneá o tocá el producto, sale el precio del catálogo (mayoreo automático), cobrás de contado o al crédito. Cada venta es una factura real: baja inventario y entra a la sesión de caja."
      hide-refresh
    >
      <template #actions>
        <q-select
          v-model="bodegaId"
          :options="opcionesBodega"
          dense
          outlined
          emit-value
          map-options
          label="Bodega"
          class="caja-bodega"
        />
        <q-btn
          v-if="puede('sales.pos.report')"
          flat
          no-caps
          icon="summarize"
          label="Corte"
          @click="abrirCorte"
        />
        <q-btn
          v-if="puede('billing.credit_note.issue')"
          flat
          no-caps
          icon="assignment_return"
          label="Devolución"
          @click="abrirDevolucion"
        />
        <q-btn
          v-if="puede('billing.doc.read')"
          flat
          no-caps
          icon="history"
          label="Historial"
          to="/ventas/historial"
        />
        <q-btn flat no-caps icon="qr_code_2" label="Auto-factura (F6)" @click="abrirAutoFactura" />
        <q-btn
          v-if="enEspera.length"
          flat
          no-caps
          icon="pause_circle"
          :label="`En espera (${enEspera.length})`"
        >
          <q-menu>
            <q-list style="min-width: 240px">
              <q-item
                v-for="t in enEspera"
                :key="t.id"
                clickable
                v-close-popup
                @click="reanudarTicket(t)"
              >
                <q-item-section>
                  <q-item-label>{{ t.etiqueta }}</q-item-label>
                  <q-item-label caption>{{ t.lineas.length }} líneas · {{ formatMoney(t.total) }}</q-item-label>
                </q-item-section>
                <q-item-section side>
                  <q-btn flat dense round size="sm" icon="delete" aria-label="Eliminar ticket retenido" @click.stop="borrarTicket(t.id)" />
                </q-item-section>
              </q-item>
            </q-list>
          </q-menu>
        </q-btn>
      </template>
    </PageHeader>

    <!-- Barra de estado: sesión de caja visible + autorización de supervisor -->
    <div class="caja-estado">
      <q-icon
        :name="sesionCaja ? 'point_of_sale' : 'warning'"
        :color="sesionCaja ? 'positive' : 'negative'"
        size="20px"
      />
      <span v-if="sesionCaja" class="caja-estado__txt">
        Caja abierta · fondo {{ formatMoney(sesionCaja.opening_amount) }} · desde {{ horaSesion }}
      </span>
      <span v-else class="caja-estado__txt caja-estado__txt--alerta">
        No hay sesión de caja abierta.
      </span>
      <q-btn
        v-if="!sesionCaja && puede('payments.cash_session.open')"
        dense
        no-caps
        unelevated
        color="primary"
        icon="point_of_sale"
        label="Abrir caja (arqueo del fondo)"
        @click="abrirArqueoApertura"
      />
      <q-btn
        v-if="sesionCaja && puede('payments.cash_session.close')"
        dense
        no-caps
        outline
        color="primary"
        icon="calculate"
        label="Cerrar caja / Arqueo"
        @click="abrirArqueoCierre"
      />
      <q-space />
      <q-chip
        v-if="overrideGrant"
        dense
        square
        color="warning"
        text-color="white"
        icon="verified_user"
        removable
        @remove="quitarAutorizacion"
      >
        Precio/descuento autorizado por {{ overrideAutorizadoPor }}
      </q-chip>
      <q-btn
        v-else-if="!puedeOverride"
        flat
        dense
        no-caps
        icon="lock_open"
        label="Autorizar precio/descuento (supervisor)"
        @click="abrirAutorizacion"
      />
      <q-btn flat dense round icon="keyboard" aria-label="Atajos de teclado">
        <q-tooltip>Atajos de teclado</q-tooltip>
        <q-menu anchor="bottom right" self="top right">
          <q-list dense class="caja-atajos">
            <q-item-label header>Atajos</q-item-label>
            <q-item v-for="a in atajos" :key="a.tecla">
              <q-item-section side><kbd class="caja-kbd">{{ a.tecla }}</kbd></q-item-section>
              <q-item-section>{{ a.que }}</q-item-section>
            </q-item>
          </q-list>
        </q-menu>
      </q-btn>
    </div>

    <!-- Escáner: siempre con foco; el lector teclea el código y manda Enter -->
    <div class="caja-escaner">
      <q-input
        ref="inputEscaner"
        v-model="codigoEscaneado"
        outlined
        autofocus
        placeholder="Escaneá el código de barras aquí…"
        class="caja-escaner__input"
        @keyup.enter="escanear"
      >
        <template #prepend><q-icon name="qr_code_scanner" /></template>
        <template #append>
          <q-btn flat dense no-caps label="Agregar" :disable="!codigoEscaneado" @click="escanear" />
        </template>
      </q-input>
      <q-select
        v-model="busquedaSeleccion"
        :options="opcionesBusqueda"
        outlined
        dense
        use-input
        clearable
        label="…o buscá por nombre"
        class="caja-escaner__buscar"
        input-debounce="350"
        :loading="buscando"
        @filter="filtrarArticulos"
        @update:model-value="agregarDesdeBusqueda"
      >
        <template #option="scope">
          <q-item v-bind="scope.itemProps">
            <q-item-section>
              <q-item-label>{{ scope.opt.label }}</q-item-label>
              <q-item-label caption>{{ scope.opt.caption }}</q-item-label>
            </q-item-section>
          </q-item>
        </template>
        <template #no-option>
          <q-item><q-item-section class="text-muted">Sin coincidencias.</q-item-section></q-item>
        </template>
      </q-select>
    </div>

    <div class="caja-cuerpo">
      <div class="caja-izquierda">
        <!-- Grid táctil por categoría -->
        <div v-if="categorias.length" class="caja-grid">
          <div class="caja-grid__cats">
            <q-chip
              v-for="cat in categorias"
              :key="cat"
              clickable
              dense
              class="caja-cat"
              :class="{ 'caja-cat--activa': categoriaActiva === cat }"
              :style="{ '--acc': accCat(cat) }"
              @click="categoriaActiva = categoriaActiva === cat ? '' : cat"
            >
              {{ cat }}
            </q-chip>
          </div>
          <div class="caja-grid__items">
            <button
              v-for="it in articulosGrid"
              :key="it.id"
              class="caja-grid__card"
              :class="{ 'caja-grid__card--bajo': stockBajo(it) }"
              :style="{ '--acc': accCat(it.category), '--grad': gradCat(it.category) }"
              type="button"
              @click="agregarArticulo(it)"
            >
              <span class="caja-grid__tile">
                {{ inicial(it.name) }}
              </span>
              <span class="caja-grid__body">
                <span class="caja-grid__nombre">{{ it.name }}</span>
                <span class="caja-grid__precio">
                  {{ it.sale_price != null ? formatMoney(it.sale_price) : 'sin precio' }}
                </span>
                <span v-if="it.wholesale_price != null" class="caja-grid__mayoreo">
                  {{ formatMoney(it.wholesale_price) }} ×{{ formatQty(it.wholesale_min_qty ?? '0') }}+
                </span>
                <span v-if="stockBajo(it)" class="caja-grid__stock">
                  <q-icon name="warning" size="12px" />
                  {{ (stockDe(it) ?? 0) <= 0 ? 'agotado' : `quedan ${formatQty(String(stockDe(it) ?? 0))}` }}
                </span>
              </span>
            </button>
            <div v-if="!articulosGrid.length" class="text-muted caja-grid__vacio">
              Sin productos en esta categoría.
            </div>
          </div>
        </div>

        <!-- Carrito -->
        <q-markup-table flat class="app-table caja-carrito">
          <thead>
            <tr>
              <th class="text-left">Artículo</th>
              <th class="text-right" style="width: 150px">Cantidad</th>
              <th class="text-right" style="width: 130px">Precio</th>
              <th v-if="overrideDesbloqueado" class="text-right" style="width: 90px">Desc. %</th>
              <th class="text-right" style="width: 120px">Total</th>
              <th style="width: 40px"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!carrito.length">
              <td :colspan="overrideDesbloqueado ? 6 : 5" class="text-center text-muted caja-vacio">
                El carrito está vacío. Escaneá o tocá un producto para empezar.
              </td>
            </tr>
            <tr
              v-for="(ln, i) in carrito"
              :key="ln.item.id"
              :class="{ 'caja-linea--flash': itemResaltado === ln.item.id }"
            >
              <td>
                <div>{{ ln.item.name }}</div>
                <div class="text-muted caja-sku">{{ ln.item.sku }}</div>
                <div v-if="excedeStock(ln)" class="caja-stock-alerta">
                  <q-icon name="warning" size="13px" />
                  Excede existencia ({{ formatQty(String(stockDe(ln.item) ?? 0)) }} disp.)
                </div>
              </td>
              <td class="text-right">
                <div class="caja-cant">
                  <q-btn
                    flat
                    round
                    dense
                    icon="remove"
                    class="caja-cant__btn"
                    aria-label="Menos uno"
                    @click="ajustarCantidad(ln, -1)"
                  />
                  <q-input
                    v-model.number="ln.quantity"
                    dense
                    borderless
                    type="number"
                    min="0.0001"
                    input-class="text-center"
                    class="caja-num caja-cant__input"
                  />
                  <q-btn
                    flat
                    round
                    dense
                    icon="add"
                    class="caja-cant__btn"
                    aria-label="Más uno"
                    @click="ajustarCantidad(ln, 1)"
                  />
                </div>
              </td>
              <td class="text-right">
                <q-input
                  v-if="overrideDesbloqueado"
                  :model-value="precioUnitario(ln)"
                  dense
                  borderless
                  type="number"
                  min="0"
                  input-class="text-right"
                  class="caja-num"
                  @update:model-value="(v) => fijarPrecioManual(ln, v)"
                />
                <span v-else>{{ formatMoney(precioUnitario(ln)) }}</span>
                <q-badge
                  v-if="esMayoreo(ln)"
                  color="secondary"
                  label="mayoreo"
                  class="caja-badge-mayoreo"
                />
              </td>
              <td v-if="overrideDesbloqueado" class="text-right">
                <q-input
                  v-model.number="ln.discount_pct"
                  dense
                  borderless
                  type="number"
                  min="0"
                  max="100"
                  input-class="text-right"
                  class="caja-num"
                />
              </td>
              <td class="text-right">{{ formatMoney(totalLinea(ln)) }}</td>
              <td>
                <q-btn flat dense round size="sm" icon="close" aria-label="Eliminar producto del carrito" @click="carrito.splice(i, 1)" />
              </td>
            </tr>
          </tbody>
        </q-markup-table>
      </div>

      <!-- Panel de cobro -->
      <div class="caja-panel">
        <div class="caja-panel__cliente">
          <PartySelect
            ref="selectorCliente"
            v-model="clienteId"
            role="CUSTOMER"
            label="Cliente (opcional; obligatorio para crédito) — F4"
            @selected="onCliente"
          />
          <q-banner v-if="cuentaCargando" dense rounded class="caja-cuenta">
            <q-spinner size="18px" class="q-mr-sm" /> Consultando crédito…
          </q-banner>
          <q-banner v-else-if="cuenta" dense rounded class="caja-cuenta">
            Cuenta de crédito · disponible:
            <strong>{{ cuenta.available != null ? formatMoney(cuenta.available) : 'sin tope' }}</strong>
            · {{ cuenta.credit_days }} días
          </q-banner>
          <q-banner v-else-if="cuentaError" dense rounded class="caja-cuenta bg-red-1 text-negative">
            {{ cuentaError }}
          </q-banner>
          <q-banner v-else-if="clienteId" dense rounded class="caja-cuenta caja-cuenta--sin">
            Sin cuenta de crédito: solo contado.
          </q-banner>
        </div>

        <q-banner v-if="codigoAutoFactura" dense rounded class="caja-cuenta">
          <q-icon name="qr_code_2" class="q-mr-xs" />
          Cobrando auto-factura <strong>{{ codigoAutoFactura }}</strong>
          <template #action>
            <q-btn flat dense no-caps label="Quitar" @click="codigoAutoFactura = null" />
          </template>
        </q-banner>

        <q-separator class="q-my-sm" />

        <div class="caja-totales">
          <div class="caja-totales__fila">
            <span class="text-muted">Subtotal</span><span>{{ formatMoney(totales.subtotal) }}</span>
          </div>
          <div class="caja-totales__fila">
            <span class="text-muted">IVA</span><span>{{ formatMoney(totales.iva) }}</span>
          </div>
          <div class="caja-totales__fila caja-totales__total">
            <span>TOTAL</span><span>{{ formatMoney(totales.total) }}</span>
          </div>
        </div>

        <q-btn
          unelevated
          no-caps
          color="primary"
          size="lg"
          icon="point_of_sale"
          label="Cobrar (F2)"
          class="full-width q-mt-md"
          :disable="!carrito.length || !bodegaId"
          @click="abrirCobro"
        />
        <q-btn
          flat
          no-caps
          icon="pause"
          label="Dejar en espera"
          class="full-width q-mt-sm"
          :disable="!carrito.length"
          @click="dejarEnEspera"
        />
        <q-btn
          flat
          no-caps
          color="negative"
          icon="delete_sweep"
          label="Vaciar carrito"
          class="full-width"
          :disable="!carrito.length"
          @click="vaciarCarritoConfirm"
        />
      </div>
    </div>

    <!-- Diálogo de cobro -->
    <q-dialog v-model="dlgCobro" @hide="enfocarEscaner">
      <q-card class="app-dialog caja-cobro">
        <q-card-section class="caja-cobro__total">
          <div class="text-muted">Total a cobrar</div>
          <div class="caja-cobro__monto">{{ formatMoney(totales.total) }}</div>
        </q-card-section>

        <q-card-section class="caja-cobro__metodos">
          <q-btn
            v-for="m in metodosRapidos"
            :key="m.value"
            flat
            no-caps
            class="caja-metodo"
            :class="{ 'caja-metodo--sel': metodo === m.value }"
            :style="{ '--acc': accMetodo(m.value) }"
            :label="m.label"
            :disable="m.value === 'CREDIT' && !cuenta"
            @click="metodo = m.value"
          />
        </q-card-section>

        <q-card-section v-if="metodo === 'CASH'" class="app-form">
          <div class="caja-rapido">
            <q-btn
              outline
              no-caps
              dense
              color="primary"
              label="Exacto"
              @click="fijarEfectivo(totales.total)"
            />
            <q-btn
              v-for="m in montosRapidos"
              :key="m"
              outline
              no-caps
              dense
              :label="`C$ ${m}`"
              @click="fijarEfectivo(m)"
            />
          </div>
          <q-input
            v-model.number="efectivoRecibido"
            outlined
            dense
            type="number"
            label="Efectivo recibido"
            autofocus
            @keyup.enter="confirmarCobro"
          />
          <div class="caja-cobro__vuelto" :class="{ 'caja-cobro__vuelto--falta': vuelto < 0 }">
            {{ vuelto >= 0 ? 'Vuelto' : 'Falta' }}: <strong>{{ formatMoney(Math.abs(vuelto)) }}</strong>
          </div>
        </q-card-section>

        <q-card-section v-if="metodo === 'MIXED'" class="app-form">
          <div v-for="(p, i) in pagosMixtos" :key="i" class="caja-cobro__mixto-fila">
            <q-select
              v-model="p.method"
              :options="opcionesMetodoContado"
              dense
              outlined
              emit-value
              map-options
              class="caja-cobro__mixto-metodo"
            />
            <q-input v-model.number="p.amount" dense outlined type="number" min="0.01" label="Monto" />
            <q-btn flat dense round icon="close" aria-label="Eliminar forma de pago" :disable="pagosMixtos.length <= 1" @click="pagosMixtos.splice(i, 1)" />
          </div>
          <q-btn flat no-caps dense icon="add" label="Agregar pago" @click="pagosMixtos.push({ method: 'CASH', amount: 0 })" />
          <div class="caja-cobro__vuelto" :class="{ 'caja-cobro__vuelto--falta': faltanteMixto > 0 }">
            {{ faltanteMixto > 0 ? `Falta ${formatMoney(faltanteMixto)}` : faltanteMixto < 0 ? `Sobra ${formatMoney(-faltanteMixto)}` : 'Pagos completos' }}
          </div>
        </q-card-section>

        <q-card-section v-if="metodo === 'CREDIT' && cuenta" class="caja-cobro__credito">
          Se cargará a la cuenta de <strong>{{ cuenta.party_display_name }}</strong> ·
          disponible {{ cuenta.available != null ? formatMoney(cuenta.available) : 'sin tope' }} ·
          vence en {{ cuenta.credit_days }} días.
        </q-card-section>

        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="primary"
            :label="`Confirmar ${formatMoney(totales.total)}`"
            :loading="cobrando"
            :disable="confirmarDeshabilitado"
            @click="confirmarCobro"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Diálogo de venta realizada -->
    <q-dialog v-model="dlgListo" @hide="enfocarEscaner">
      <q-card class="app-dialog caja-listo">
        <q-card-section class="text-center">
          <q-icon name="check_circle" color="positive" size="56px" />
          <div class="text-h6 q-mt-sm">Venta realizada</div>
          <div class="text-muted">
            Factura #{{ resultado?.number ?? resultado?.doc_id }} · {{ formatMoney(resultado?.total ?? 0) }}
          </div>
          <div v-if="vueltoFinal > 0" class="caja-listo__vuelto">
            Vuelto: <strong>{{ formatMoney(vueltoFinal) }}</strong>
          </div>
          <div v-if="resultado?.sale_type === 'CREDIT'" class="text-muted q-mt-xs">
            Cargado a cuenta · disponible restante:
            {{ resultado?.available_after != null ? formatMoney(resultado.available_after) : 'sin tope' }}
          </div>
        </q-card-section>
        <q-card-actions align="center">
          <q-btn flat no-caps icon="receipt" label="Ticket" @click="imprimirTicket" />
          <q-btn
            v-if="puede('billing.doc.print') && resultado"
            flat
            no-caps
            icon="print"
            label="Imprimir fiscal"
            @click="imprimir"
          />
          <q-btn unelevated no-caps color="primary" label="Nueva venta" v-close-popup />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Diálogo: corte de ventas del día -->
    <q-dialog v-model="dlgCorte">
      <q-card class="app-dialog caja-corte">
        <q-card-section class="text-h6 row items-center justify-between">
          <span>Corte de ventas</span>
          <q-input v-model="corteFecha" dense outlined type="date" @update:model-value="cargarCorte" />
        </q-card-section>
        <q-card-section v-if="corte">
          <div class="caja-corte__grid">
            <div class="caja-corte__stat" style="--grad: var(--app-stat-blue)">
              <div class="caja-corte__rotulo">Ventas</div>
              <div class="caja-corte__cifra">{{ corte.sales.count }}</div>
            </div>
            <div class="caja-corte__stat" style="--grad: var(--app-stat-violet)">
              <div class="caja-corte__rotulo">Total vendido</div>
              <div class="caja-corte__cifra">{{ formatMoney(corte.sales.total) }}</div>
            </div>
            <div class="caja-corte__stat" style="--grad: var(--app-stat-teal)">
              <div class="caja-corte__rotulo">Utilidad bruta</div>
              <div class="caja-corte__cifra">{{ formatMoney(corte.gross_profit) }}</div>
            </div>
            <div class="caja-corte__stat" style="--grad: var(--app-stat-coral)">
              <div class="caja-corte__rotulo">Devoluciones</div>
              <div class="caja-corte__cifra">
                {{ corte.returns.count }} · {{ formatMoney(corte.returns.total) }}
              </div>
            </div>
          </div>

          <div class="text-subtitle2 q-mt-md">Cobros por método</div>
          <q-list dense separator>
            <q-item v-for="m in corte.payments_by_method" :key="m.method">
              <q-item-section>{{ POS_PAYMENT_METHOD_LABELS[m.method] ?? m.method }} ({{ m.count }})</q-item-section>
              <q-item-section side>{{ formatMoney(m.amount) }}</q-item-section>
            </q-item>
            <q-item v-if="Number(corte.sales.credit_total) > 0">
              <q-item-section>Al crédito (CxC)</q-item-section>
              <q-item-section side>{{ formatMoney(corte.sales.credit_total) }}</q-item-section>
            </q-item>
          </q-list>

          <div class="text-subtitle2 q-mt-md">Productos más vendidos</div>
          <q-list dense separator>
            <q-item v-for="p in corte.top_products" :key="p.sku">
              <q-item-section>
                <q-item-label>{{ p.name }}</q-item-label>
                <q-item-label caption>{{ p.sku }} · {{ formatQty(p.qty) }} uds</q-item-label>
              </q-item-section>
              <q-item-section side>{{ formatMoney(p.amount) }}</q-item-section>
            </q-item>
            <q-item v-if="!corte.top_products.length">
              <q-item-section class="text-muted">Sin ventas con artículo este día.</q-item-section>
            </q-item>
          </q-list>

          <div class="text-subtitle2 q-mt-md">Por cajero</div>
          <q-list dense separator>
            <q-item v-for="cj in corte.by_cashier" :key="cj.username">
              <q-item-section>{{ cj.username }} ({{ cj.count }})</q-item-section>
              <q-item-section side>{{ formatMoney(cj.total) }}</q-item-section>
            </q-item>
          </q-list>
        </q-card-section>
        <q-inner-loading :showing="cargandoCorte" />
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cerrar" v-close-popup />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Diálogo: devolución -->
    <q-dialog v-model="dlgDevolucion" @hide="enfocarEscaner">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">Devolución</q-card-section>
        <q-card-section class="app-form">
          <q-input
            v-model="devNumero"
            outlined
            dense
            label="Número de factura *"
            autofocus
            @keyup.enter="buscarFacturaDevolucion"
          >
            <template #append>
              <q-btn flat dense no-caps label="Buscar" :loading="devBuscando" @click="buscarFacturaDevolucion" />
            </template>
          </q-input>
          <q-banner v-if="devDoc" dense rounded class="caja-cuenta">
            Factura {{ devDoc.series }}-{{ devDoc.number }} ·
            {{ devDoc.customer_party_display_name || devDoc.customer_name || 'Consumidor final' }} ·
            {{ formatMoney(devDoc.total) }}
            <span v-if="Number(devDoc.credited_total) > 0" class="text-negative">
              · ya acreditado {{ formatMoney(devDoc.credited_total) }}
            </span>
          </q-banner>
          <q-input v-model="devMotivo" outlined dense label="Motivo *" />
          <q-toggle v-model="devRestock" label="Reingresar la mercadería al inventario" color="primary" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="warning"
            label="Emitir nota de crédito"
            :loading="devEmitiendo"
            :disable="!devDoc || devMotivo.trim().length < 3"
            @click="emitirDevolucion"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Diálogo: autorización de supervisor (override de precio/descuento) -->
    <q-dialog v-model="dlgAutorizar" @hide="enfocarEscaner">
      <q-card class="app-dialog caja-autorizar">
        <q-card-section class="text-h6 row items-center">
          <q-icon name="admin_panel_settings" class="q-mr-sm" />
          Autorización de supervisor
        </q-card-section>
        <q-card-section class="text-muted">
          El cajero no tiene permiso para cambiar precios o aplicar descuentos. Un supervisor
          con permiso se identifica para autorizar esta venta (queda auditado).
        </q-card-section>
        <q-card-section class="app-form">
          <q-input v-model="autSupervisor" outlined dense label="Usuario del supervisor *" autofocus />
          <q-input
            v-model="autPassword"
            outlined
            dense
            type="password"
            label="Contraseña *"
            @keyup.enter="confirmarAutorizacion"
          />
          <q-input v-model="autMotivo" outlined dense label="Motivo *" hint="Mínimo 3 caracteres" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="primary"
            icon="lock_open"
            label="Autorizar"
            :loading="autEnviando"
            :disable="!autSupervisor.trim() || !autPassword || autMotivo.trim().length < 3"
            @click="confirmarAutorizacion"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Diálogo: traer auto-factura del cliente -->
    <q-dialog v-model="dlgAutoFactura" @hide="enfocarEscaner">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">Auto-factura del cliente</q-card-section>
        <q-card-section class="app-form">
          <q-input
            v-model="afCodigo"
            outlined
            dense
            autofocus
            label="Código del ticket *"
            mask="XXXXXXXX"
            @keyup.enter="traerAutoFactura"
          >
            <template #prepend><q-icon name="qr_code_2" /></template>
            <template #append>
              <q-btn flat dense no-caps label="Traer" :loading="afCargando" @click="traerAutoFactura" />
            </template>
          </q-input>
          <div class="text-muted">
            El cliente armó su compra en la tableta; al traerla, el carrito se llena con los
            precios de catálogo de HOY y cobrás normal (contado o crédito).
          </div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Arqueo de caja: apertura (contar el fondo) / cierre (contar el cajón → diferencia) -->
    <q-dialog v-model="arqueoOpen">
      <q-card class="arqueo-dialog">
        <q-card-section class="text-h6">
          {{ arqueoModo === 'abrir' ? 'Abrir caja — arqueo del fondo' : 'Cerrar caja — arqueo' }}
        </q-card-section>
        <q-card-section>
          <ArqueoEfectivo
            v-model="arqueoDenoms"
            :esperado="arqueoEsperado"
            :ayuda="
              arqueoModo === 'abrir'
                ? 'Contá el efectivo con el que abrís la caja. El total queda como fondo de apertura.'
                : 'Contá el efectivo del cajón. El total se compara con lo esperado y se registra la diferencia.'
            "
          />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Cancelar" v-close-popup :disable="arqueoCargando" />
          <q-btn
            unelevated
            color="primary"
            :label="arqueoModo === 'abrir' ? 'Abrir caja' : 'Cerrar caja'"
            :loading="arqueoCargando"
            @click="confirmarArqueo"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import PartySelect from 'src/modules/parties/components/PartySelect.vue';
import { apiErrorMessage } from 'src/core/api';
import { formatMoney, formatQty } from 'src/core/format';
import { newUuid } from 'src/core/uuid';
import {
  issueCreditNote,
  listBillingDocs,
  printBillingDoc,
  type BillingDocRow,
} from 'src/modules/billing/api';
import {
  findItemByBarcode,
  getStock,
  listItems,
  listWarehouses,
  type InventoryItem,
  type Warehouse,
} from 'src/modules/inventory/api';
import {
  listCashSessions,
  openCashSession,
  submitDenominations,
  closeCashSession,
  getCashSession,
  type CashSessionRow,
  type Denomination,
} from 'src/modules/payments/api';
import { nuevoArqueo, totalArqueo } from 'src/modules/payments/denominations';
import ArqueoEfectivo from 'src/modules/payments/components/ArqueoEfectivo.vue';
import type { Party } from 'src/modules/parties/api';
import {
  getCreditAccount,
  getPosReport,
  getSelfServiceTicket,
  grantPosOverride,
  posSale,
  POS_PAYMENT_METHOD_LABELS,
  type CreditAccountSummary,
  type PosReport,
  type PosSalePayment,
  type PosSaleResult,
} from 'src/modules/ventas/api';
import { rehydrateHeldCustomer } from 'src/modules/ventas/held-ticket';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';

const $q = useQuasar();
const acl = useAclStore();
const ctx = useContextStore();

function puede(code: string): boolean {
  const companyId = ctx.activeCompanyId;
  return companyId ? acl.hasPermission(companyId, code) : false;
}
/** Permiso propio del cajero para cambiar precio / aplicar descuento. */
const puedeOverride = computed(() => puede('sales.pos.price_override'));

// --- Autorización de supervisor (override de precio/descuento) -------------------
const overrideGrant = ref<string | null>(null);
const overrideAutorizadoPor = ref('');
/** Override habilitado: por permiso propio o por autorización vigente de un supervisor. */
const overrideDesbloqueado = computed(() => puedeOverride.value || overrideGrant.value != null);

const dlgAutorizar = ref(false);
const autSupervisor = ref('');
const autPassword = ref('');
const autMotivo = ref('');
const autEnviando = ref(false);

function abrirAutorizacion() {
  autSupervisor.value = '';
  autPassword.value = '';
  autMotivo.value = '';
  dlgAutorizar.value = true;
}

async function confirmarAutorizacion() {
  if (!autSupervisor.value.trim() || !autPassword.value || autMotivo.value.trim().length < 3) return;
  autEnviando.value = true;
  try {
    const g = await grantPosOverride({
      supervisor_username: autSupervisor.value.trim(),
      supervisor_password: autPassword.value,
      reason: autMotivo.value.trim(),
    });
    overrideGrant.value = g.grant;
    overrideAutorizadoPor.value = g.authorized_by;
    autPassword.value = '';
    dlgAutorizar.value = false;
    $q.notify({ type: 'positive', message: `Descuento/precio autorizado por ${g.authorized_by}.` });
  } catch (e) {
    $q.notify({ type: 'negative', message: mensajeVenta(e) });
  } finally {
    autEnviando.value = false;
  }
}

function quitarAutorizacion() {
  overrideGrant.value = null;
  overrideAutorizadoPor.value = '';
}

// Redondeo a 2 decimales espejo del kernel (cada paso se cuantiza).
function r2(x: number): number {
  return Math.round((x + Number.EPSILON) * 100) / 100;
}

// --- Bodega ---------------------------------------------------------------
const bodegas = ref<Warehouse[]>([]);
const bodegaId = ref<number | null>(null);
const opcionesBodega = computed(() =>
  bodegas.value.map((w) => ({ label: w.name, value: w.id })),
);

// --- Sesión de caja (visible para el cajero) ------------------------------------
const sesionCaja = ref<CashSessionRow | null>(null);

async function cargarSesionCaja() {
  try {
    const sesiones = await listCashSessions();
    sesionCaja.value = sesiones.find((s) => s.status === 'OPEN') ?? null;
  } catch {
    sesionCaja.value = null;
  }
}

const horaSesion = computed(() => {
  if (!sesionCaja.value) return '';
  return new Date(sesionCaja.value.opened_at).toLocaleTimeString('es-NI', {
    hour: '2-digit',
    minute: '2-digit',
  });
});

// --- Arqueo de caja (apertura/cierre por denominación) desde la sala de ventas ---------------------
const arqueoOpen = ref(false);
const arqueoModo = ref<'abrir' | 'cerrar'>('abrir');
const arqueoDenoms = ref<Denomination[]>(nuevoArqueo());
const arqueoEsperado = ref<number | null>(null);
const arqueoCargando = ref(false);
const arqueoTotal = computed(() => totalArqueo(arqueoDenoms.value));

function abrirArqueoApertura() {
  arqueoModo.value = 'abrir';
  arqueoDenoms.value = nuevoArqueo();
  arqueoEsperado.value = null;
  arqueoOpen.value = true;
}

async function abrirArqueoCierre() {
  if (!sesionCaja.value) return;
  arqueoModo.value = 'cerrar';
  arqueoDenoms.value = nuevoArqueo();
  arqueoEsperado.value = null;
  arqueoOpen.value = true;
  // Traer lo ESPERADO para mostrar la diferencia en vivo mientras se cuenta.
  try {
    const s = await getCashSession(sesionCaja.value.id);
    arqueoEsperado.value = Number(s.expected_amount);
  } catch {
    /* sin esperado: el cierre igual lo calcula en el backend */
  }
}

async function confirmarArqueo() {
  arqueoCargando.value = true;
  try {
    if (arqueoModo.value === 'abrir') {
      await openCashSession({
        opening_amount: arqueoTotal.value.toFixed(2),
        denominations: arqueoDenoms.value.filter((d) => d.quantity > 0),
      });
      $q.notify({ type: 'positive', icon: 'point_of_sale', message: `Caja abierta · fondo ${formatMoney(arqueoTotal.value)}.` });
    } else {
      const id = sesionCaja.value?.id;
      if (!id) return;
      await submitDenominations(id, arqueoDenoms.value);
      const r = await closeCashSession(id, { counted_amount: arqueoTotal.value.toFixed(2) });
      const dif = Number(r.difference_amount);
      $q.notify({
        type: dif === 0 ? 'positive' : 'warning',
        icon: 'calculate',
        message:
          `Caja cerrada · contado ${formatMoney(r.counted_amount)} · esperado ${formatMoney(r.expected_amount)}` +
          (dif === 0 ? ' · sin diferencia.' : ` · diferencia ${formatMoney(dif)} (${dif > 0 ? 'sobrante' : 'faltante'}).`),
        timeout: 6000,
      });
    }
    arqueoOpen.value = false;
    await cargarSesionCaja();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo completar el arqueo de caja.') });
  } finally {
    arqueoCargando.value = false;
  }
}

// --- Existencias por artículo (para avisar stock bajo) --------------------------
const stockPorItem = ref<Map<number, number>>(new Map());

async function cargarStock() {
  if (!bodegaId.value) {
    stockPorItem.value = new Map();
    return;
  }
  try {
    const filas = await getStock({ warehouse_id: bodegaId.value });
    const mapa = new Map<number, number>();
    for (const f of filas) mapa.set(f.item, Number(f.qty_available));
    stockPorItem.value = mapa;
  } catch {
    stockPorItem.value = new Map();
  }
}

/** Existencia disponible del artículo en la bodega activa (null si no se conoce). */
function stockDe(item: InventoryItem): number | null {
  const v = stockPorItem.value.get(item.id);
  return v === undefined ? null : v;
}

/** true si la existencia está en/por debajo del punto de reorden (o agotada). */
function stockBajo(item: InventoryItem): boolean {
  const disp = stockDe(item);
  if (disp === null) return false;
  const reorden = Number(item.reorder_point || 0);
  return disp <= 0 || (reorden > 0 && disp <= reorden);
}

/** true si la cantidad en el carrito supera la existencia disponible conocida. */
function excedeStock(ln: { item: InventoryItem; quantity: number }): boolean {
  const disp = stockDe(ln.item);
  return disp !== null && ln.quantity > disp;
}

// --- Color por categoría (estable, NO arcoíris) -----------------------------------
// Cada categoría toma SIEMPRE la misma familia de acento del tema.
const ACENTOS = ['blue', 'teal', 'violet', 'amber', 'coral'] as const;

function acentoDe(categoria: string): string {
  const cat = (categoria || '').trim();
  if (!cat) return 'blue';
  let h = 0;
  for (let i = 0; i < cat.length; i++) h = (h * 31 + cat.charCodeAt(i)) >>> 0;
  return ACENTOS[h % ACENTOS.length] ?? 'blue';
}
/** Gradiente (fondo del tile). */
function gradCat(categoria: string): string {
  return `var(--app-stat-${acentoDe(categoria)})`;
}
/** Sólido (barra/borde/tinte). */
function accCat(categoria: string): string {
  return `var(--app-accent-${acentoDe(categoria)})`;
}

/** Inicial del producto para el tile coloreado. */
function inicial(nombre: string): string {
  return (nombre || '?').trim().charAt(0).toUpperCase() || '?';
}

// Acento por método de pago (color con significado, estable).
const ACC_METODO: Record<string, string> = {
  CASH: 'var(--app-accent-teal)',
  TRANSFER: 'var(--app-accent-blue)',
  CARD: 'var(--app-accent-violet)',
  CHECK: 'var(--app-accent-blue)',
  CREDIT: 'var(--app-accent-amber)',
  MIXED: 'var(--app-accent-coral)',
};
function accMetodo(value: string): string {
  return ACC_METODO[value] ?? 'var(--app-accent-blue)';
}

// --- Carrito ----------------------------------------------------------------
interface LineaCarrito {
  item: InventoryItem;
  quantity: number;
  /** true cuando el cajero (con permiso) fijó el precio a mano. */
  manual: boolean;
  /** Solo válido cuando manual=true. */
  unit_price: number;
  discount_pct: number; // en %, la API lo recibe como fracción
}

const carrito = ref<LineaCarrito[]>([]);
let idemKey = newUuid();

/** Precio de catálogo según cantidad: mayoreo automático (espejo del servidor). */
function precioCatalogo(item: InventoryItem, qty: number): number | null {
  if (
    item.wholesale_price != null &&
    item.wholesale_min_qty != null &&
    qty >= Number(item.wholesale_min_qty)
  ) {
    return Number(item.wholesale_price);
  }
  return item.sale_price != null ? Number(item.sale_price) : null;
}

function precioUnitario(ln: LineaCarrito): number {
  if (ln.manual) return ln.unit_price;
  return precioCatalogo(ln.item, ln.quantity) ?? 0;
}

function esMayoreo(ln: LineaCarrito): boolean {
  return (
    !ln.manual &&
    ln.item.wholesale_price != null &&
    ln.item.wholesale_min_qty != null &&
    ln.quantity >= Number(ln.item.wholesale_min_qty)
  );
}

function fijarPrecioManual(ln: LineaCarrito, v: string | number | null) {
  ln.manual = true;
  ln.unit_price = Number(v ?? 0);
}

function totalLinea(ln: LineaCarrito): number {
  const bruto = r2(ln.quantity * precioUnitario(ln));
  const desc = r2(bruto * (ln.discount_pct / 100));
  const sub = r2(bruto - desc);
  const iva = r2(sub * Number(ln.item.default_tax_rate || 0));
  return r2(sub + iva);
}

const totales = computed(() => {
  let subtotal = 0;
  let iva = 0;
  for (const ln of carrito.value) {
    const bruto = r2(ln.quantity * precioUnitario(ln));
    const desc = r2(bruto * (ln.discount_pct / 100));
    const sub = r2(bruto - desc);
    subtotal = r2(subtotal + sub);
    iva = r2(iva + r2(sub * Number(ln.item.default_tax_rate || 0)));
  }
  return { subtotal, iva, total: r2(subtotal + iva) };
});

// Feedback visual: resalta (flash) la línea recién agregada/incrementada y la trae a la vista, para que
// el cajero VEA que el producto entró sin mirar el detalle.
const itemResaltado = ref<number | null>(null);
function resaltarLinea(itemId: number) {
  itemResaltado.value = itemId;
  void nextTick(() => {
    document.querySelector('.caja-carrito .caja-linea--flash')?.scrollIntoView({ block: 'nearest' });
  });
  window.setTimeout(() => {
    if (itemResaltado.value === itemId) itemResaltado.value = null;
  }, 700);
}

function agregarArticulo(item: InventoryItem) {
  const existente = carrito.value.find((l) => l.item.id === item.id);
  if (existente) {
    existente.quantity += 1;
    resaltarLinea(item.id);
    return;
  }
  if (item.sale_price == null && !overrideDesbloqueado.value) {
    $q.notify({
      type: 'warning',
      message: `«${item.name}» no tiene precio de venta. Definilo en el Catálogo de inventario.`,
    });
    return;
  }
  carrito.value.push({
    item,
    quantity: 1,
    manual: item.sale_price == null,
    unit_price: item.sale_price != null ? Number(item.sale_price) : 0,
    discount_pct: 0,
  });
  resaltarLinea(item.id);
}

// Steppers ± de cantidad (táctil/mouse). Min 1 por unidad; para peso, el cajero teclea la cantidad.
function ajustarCantidad(ln: LineaCarrito, delta: number) {
  ln.quantity = Math.max(1, r2((Number(ln.quantity) || 0) + delta));
  resaltarLinea(ln.item.id);
}

function vaciarCarrito() {
  carrito.value = [];
  clienteId.value = null;
  clienteNombre.value = '';
  cuenta.value = null;
  cuentaError.value = '';
  cuentaCargando.value = false;
  codigoAutoFactura.value = null;
  quitarAutorizacion();
  idemKey = newUuid();
  enfocarEscaner();
}

// BUG-11: vaciar el carrito es destructivo (descarta líneas + cliente + autorización).
// Las acciones iniciadas por el usuario (botón y F9) piden confirmación; el carrito
// vacío no pregunta y el camino programático (poner en espera) usa `vaciarCarrito` directo.
function vaciarCarritoConfirm() {
  if (!carrito.value.length) {
    vaciarCarrito();
    return;
  }
  $q.dialog({
    title: 'Vaciar carrito',
    message: '¿Descartar las líneas, el cliente y la autorización del carrito actual?',
    cancel: { label: 'Cancelar', flat: true },
    ok: { label: 'Vaciar', color: 'negative' },
    persistent: true,
  }).onOk(() => vaciarCarrito());
}

// --- Auto-factura (pre-ticket del kiosko) -----------------------------------------
const dlgAutoFactura = ref(false);
const afCodigo = ref('');
const afCargando = ref(false);
const codigoAutoFactura = ref<string | null>(null);

function abrirAutoFactura() {
  afCodigo.value = '';
  dlgAutoFactura.value = true;
}

async function traerAutoFactura() {
  const codigo = afCodigo.value.trim().toUpperCase();
  if (!codigo) return;
  afCargando.value = true;
  try {
    const t = await getSelfServiceTicket(codigo);

    // El ticket guarda artículo+cantidad; el item completo sale del catálogo cargado.
    let porId = new Map(articulos.value.map((it) => [it.id, it]));
    if (t.lines.some((l) => !l.unavailable && !porId.has(l.inventory_item_id))) {
      const refrescados = await listItems({ is_active: true });
      articulos.value = refrescados.filter(
        (it) => it.sale_price != null || it.wholesale_price != null,
      );
      porId = new Map(refrescados.map((it) => [it.id, it]));
    }

    const lineas: LineaCarrito[] = [];
    const omitidas: string[] = [];
    for (const l of t.lines) {
      const item = porId.get(l.inventory_item_id);
      if (l.unavailable || !item) {
        omitidas.push(l.name || l.sku || `#${l.inventory_item_id}`);
        continue;
      }
      lineas.push({
        item,
        quantity: Number(l.quantity),
        manual: false,
        unit_price: item.sale_price != null ? Number(item.sale_price) : 0,
        discount_pct: 0,
      });
    }
    if (!lineas.length) {
      $q.notify({ type: 'negative', message: 'El ticket no tiene artículos disponibles.' });
      return;
    }

    carrito.value = lineas;
    codigoAutoFactura.value = t.code;
    dlgAutoFactura.value = false;
    if (omitidas.length) {
      $q.notify({
        type: 'warning',
        message: `Se omitieron artículos sin precio o inactivos: ${omitidas.join(', ')}.`,
      });
    }
    $q.notify({
      type: 'info',
      message: `Auto-factura ${t.code} cargada: ${lineas.length} líneas, estimado ${formatMoney(t.estimated_total)}.`,
    });
  } catch (e) {
    $q.notify({ type: 'negative', message: mensajeVenta(e) });
  } finally {
    afCargando.value = false;
  }
}

// --- Escáner -----------------------------------------------------------------
const codigoEscaneado = ref('');
const inputEscaner = ref<{ focus: () => void } | null>(null);

function enfocarEscaner() {
  setTimeout(() => inputEscaner.value?.focus(), 50);
}

async function escanear() {
  const codigo = codigoEscaneado.value.trim();
  codigoEscaneado.value = '';
  if (!codigo) return;
  try {
    const item = await findItemByBarcode(codigo);
    if (!item) {
      $q.notify({ type: 'negative', message: `Código ${codigo}: producto no encontrado.` });
      return;
    }
    agregarArticulo(item);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo buscar el producto.') });
  } finally {
    enfocarEscaner();
  }
}

// --- Grid táctil por categoría ----------------------------------------------------
const articulos = ref<InventoryItem[]>([]);
const categoriaActiva = ref('');

const categorias = computed(() => {
  const set = new Set<string>();
  for (const it of articulos.value) if (it.category) set.add(it.category);
  return [...set].sort();
});

const articulosGrid = computed(() => {
  const base = categoriaActiva.value
    ? articulos.value.filter((it) => it.category === categoriaActiva.value)
    : articulos.value;
  return base.slice(0, 60);
});

// --- Búsqueda por nombre -------------------------------------------------------
interface OpcionArticulo {
  label: string;
  value: number;
  caption: string;
}
const opcionesBusqueda = ref<OpcionArticulo[]>([]);
const busquedaSeleccion = ref<number | null>(null);
const buscando = ref(false);
const articulosPorId = new Map<number, InventoryItem>();

function filtrarArticulos(input: string, update: (fn: () => void) => void, abort: () => void) {
  if (!input.trim()) {
    abort();
    return;
  }
  buscando.value = true;
  listItems({ search: input.trim() })
    .then((rows) => {
      update(() => {
        articulosPorId.clear();
        for (const it of rows) articulosPorId.set(it.id, it);
        opcionesBusqueda.value = rows.map((it) => ({
          label: it.name,
          value: it.id,
          caption: `${it.sku}${it.sale_price != null ? ' · ' + formatMoney(it.sale_price) : ' · SIN PRECIO'}`,
        }));
      });
    })
    .catch(() => abort())
    .finally(() => {
      buscando.value = false;
    });
}

function agregarDesdeBusqueda(itemId: number | null) {
  if (itemId == null) return;
  const item = articulosPorId.get(itemId);
  if (item) agregarArticulo(item);
  busquedaSeleccion.value = null;
  enfocarEscaner();
}

// --- Cliente / crédito ----------------------------------------------------------
const clienteId = ref<number | null>(null);
const clienteNombre = ref('');
const cuenta = ref<CreditAccountSummary | null>(null);
const cuentaError = ref('');
const cuentaCargando = ref(false);
const selectorCliente = ref<{ $el?: HTMLElement } | null>(null);

async function onCliente(party: Party | null) {
  clienteNombre.value = party?.display_name ?? '';
  cuenta.value = null;
  cuentaError.value = '';
  if (!party) return;
  cuentaCargando.value = true;
  try {
    cuenta.value = await getCreditAccount(party.id);
  } catch (error) {
    cuentaError.value = apiErrorMessage(error, 'No se pudo consultar el crédito del cliente.');
    $q.notify({ type: 'negative', message: cuentaError.value });
  } finally {
    cuentaCargando.value = false;
  }
}

// --- Cobro ----------------------------------------------------------------------
const dlgCobro = ref(false);
const metodo = ref('CASH');
const efectivoRecibido = ref(0);
const pagosMixtos = ref<{ method: string; amount: number }[]>([]);
const cobrando = ref(false);

const metodosRapidos = [
  { value: 'CASH', label: 'Efectivo' },
  { value: 'TRANSFER', label: 'Transferencia' },
  { value: 'CARD', label: 'Tarjeta' },
  { value: 'CREDIT', label: 'Crédito' },
  { value: 'MIXED', label: 'Mixto' },
];
const opcionesMetodoContado = [
  { value: 'CASH', label: 'Efectivo' },
  { value: 'TRANSFER', label: 'Transferencia' },
  { value: 'CARD', label: 'Tarjeta' },
  { value: 'CHECK', label: 'Cheque' },
];

const vuelto = computed(() => r2(efectivoRecibido.value - totales.value.total));

// Montos de efectivo rápido (un toque): billetes ≥ total para no teclear. "Exacto" va aparte.
const montosRapidos = computed(() => {
  const total = totales.value.total;
  return [100, 200, 500, 1000].filter((b) => b > total);
});
function fijarEfectivo(monto: number) {
  efectivoRecibido.value = monto;
}
const faltanteMixto = computed(() => {
  const pagado = pagosMixtos.value.reduce((s, p) => r2(s + (p.amount || 0)), 0);
  return r2(totales.value.total - pagado);
});

const confirmarDeshabilitado = computed(() => {
  if (metodo.value === 'CASH') return vuelto.value < 0;
  if (metodo.value === 'MIXED') return faltanteMixto.value !== 0;
  if (metodo.value === 'CREDIT') return !cuenta.value || !clienteId.value;
  return false;
});

function abrirCobro() {
  metodo.value = 'CASH';
  efectivoRecibido.value = totales.value.total;
  pagosMixtos.value = [{ method: 'CASH', amount: totales.value.total }];
  dlgCobro.value = true;
}

const dlgListo = ref(false);
const resultado = ref<PosSaleResult | null>(null);
const vueltoFinal = ref(0);

/** Snapshot de la última venta para el ticket 80mm. */
interface UltimaVenta {
  numero: string;
  fecha: string;
  cliente: string;
  metodo: string;
  lineas: { nombre: string; qty: number; precio: number; total: number }[];
  subtotal: number;
  iva: number;
  total: number;
  vuelto: number;
}
const ultimaVenta = ref<UltimaVenta | null>(null);

async function confirmarCobro() {
  if (confirmarDeshabilitado.value || !bodegaId.value) return;

  let payments: PosSalePayment[];
  if (metodo.value === 'CREDIT') {
    payments = [{ method: 'CREDIT' }];
  } else if (metodo.value === 'MIXED') {
    payments = pagosMixtos.value.map((p) => ({ method: p.method, amount: p.amount.toFixed(2) }));
  } else {
    payments = [{ method: metodo.value, amount: totales.value.total.toFixed(2) }];
  }

  cobrando.value = true;
  try {
    const res = await posSale({
      warehouse_id: bodegaId.value,
      customer_party_id: clienteId.value,
      customer_name: clienteNombre.value,
      idempotency_key: idemKey,
      ...(codigoAutoFactura.value ? { self_service_code: codigoAutoFactura.value } : {}),
      ...(overrideGrant.value ? { override_grant: overrideGrant.value } : {}),
      lines: carrito.value.map((ln) => {
        const linea: Record<string, unknown> = {
          inventory_item_id: ln.item.id,
          quantity: String(ln.quantity),
        };
        // El precio solo viaja si el cajero lo fijó a mano (override con permiso);
        // el catálogo (incluido el mayoreo) lo resuelve el servidor.
        if (ln.manual) linea.unit_price = ln.unit_price.toFixed(4);
        if (ln.discount_pct > 0) linea.discount_pct = (ln.discount_pct / 100).toFixed(4);
        return linea as never;
      }),
      payments,
    });
    resultado.value = res;
    vueltoFinal.value = metodo.value === 'CASH' ? vuelto.value : 0;
    ultimaVenta.value = {
      numero: String(res.number ?? res.doc_id),
      fecha: new Date().toLocaleString('es-NI'),
      cliente: clienteNombre.value || 'Consumidor final',
      metodo: metodosRapidos.find((m) => m.value === metodo.value)?.label ?? metodo.value,
      lineas: carrito.value.map((ln) => ({
        nombre: ln.item.name,
        qty: ln.quantity,
        precio: precioUnitario(ln),
        total: totalLinea(ln),
      })),
      subtotal: totales.value.subtotal,
      iva: totales.value.iva,
      total: totales.value.total,
      vuelto: metodo.value === 'CASH' ? vuelto.value : 0,
    };
    dlgCobro.value = false;
    dlgListo.value = true;
    carrito.value = [];
    clienteId.value = null;
    cuenta.value = null;
    codigoAutoFactura.value = null;
    quitarAutorizacion();
    idemKey = newUuid();
    void cargarSesionCaja();
    void cargarStock();
  } catch (e) {
    $q.notify({ type: 'negative', message: mensajeVenta(e) });
  } finally {
    cobrando.value = false;
  }
}

const MENSAJES_VENTA: Record<string, string> = {
  SALES_NO_OPEN_CASH_SESSION: 'No hay sesión de caja abierta. Abrí caja primero (Caja y Pagos).',
  SALES_ITEM_WITHOUT_PRICE: 'Un artículo no tiene precio de venta en el catálogo.',
  SALES_PRICE_OVERRIDE_FORBIDDEN: 'No tenés permiso para cambiar precios o aplicar descuentos.',
  SALES_PAYMENTS_MISMATCH: 'Los pagos no cuadran con el total.',
  SALES_NO_CREDIT_ACCOUNT: 'El cliente no tiene cuenta de crédito: solo contado.',
  SALES_CREDIT_REQUIRES_CUSTOMER: 'Para vender al crédito hay que elegir el cliente.',
  COMISARIATO_CREDIT_LIMIT_EXCEEDED: 'La venta excede el crédito disponible del cliente.',
  SALES_SELF_SERVICE_NOT_FOUND: 'No existe una auto-factura con ese código.',
  SALES_SELF_SERVICE_NOT_OPEN: 'Esa auto-factura ya fue cobrada o cancelada.',
  SALES_SELF_SERVICE_EXPIRED: 'Esa auto-factura ya venció; el cliente debe armarla de nuevo.',
  SALES_OVERRIDE_BAD_CREDENTIALS: 'Usuario o contraseña del supervisor incorrectos.',
  SALES_OVERRIDE_NOT_AUTHORIZED: 'Ese usuario no tiene permiso para autorizar precios/descuentos.',
  SALES_OVERRIDE_SELF: 'La autorización la debe dar otro usuario (no el mismo cajero).',
  SALES_OVERRIDE_REASON_REQUIRED: 'Indicá el motivo de la autorización.',
  SALES_OVERRIDE_INVALID: 'La autorización no es válida; pedila de nuevo.',
  SALES_OVERRIDE_EXPIRED: 'La autorización venció; pedila de nuevo.',
};

function mensajeVenta(e: unknown): string {
  const crudo = apiErrorMessage(e, 'No se pudo completar la venta.');
  return MENSAJES_VENTA[crudo] ?? crudo;
}

async function imprimir() {
  if (!resultado.value) return;
  try {
    await printBillingDoc(resultado.value.doc_id);
    $q.notify({ type: 'positive', message: 'Impresión encolada.' });
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo imprimir.') });
  }
}

// --- Ticket 80mm -------------------------------------------------------------------
function imprimirTicket() {
  const v = ultimaVenta.value;
  if (!v) return;
  const filas = v.lineas
    .map(
      (l) =>
        `<tr><td>${l.nombre}</td><td class="n">${l.qty}</td><td class="n">${l.precio.toFixed(2)}</td><td class="n">${l.total.toFixed(2)}</td></tr>`,
    )
    .join('');
  const html = `<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Ticket ${v.numero}</title>
<style>
  body { font-family: 'Courier New', monospace; width: 72mm; margin: 0 auto; font-size: 12px; color: #000; }
  h1 { font-size: 14px; text-align: center; margin: 4px 0; }
  .c { text-align: center; margin: 2px 0; }
  table { width: 100%; border-collapse: collapse; margin-top: 6px; }
  th, td { text-align: left; padding: 1px 2px; }
  .n { text-align: right; }
  .tot { border-top: 1px dashed #000; font-weight: bold; }
  @media print { @page { margin: 0; size: 80mm auto; } }
</style></head><body>
  <h1>Factura ${v.numero}</h1>
  <div class="c">${v.fecha}</div>
  <div class="c">Cliente: ${v.cliente}</div>
  <table>
    <thead><tr><th>Producto</th><th class="n">Cant</th><th class="n">Precio</th><th class="n">Total</th></tr></thead>
    <tbody>${filas}</tbody>
    <tfoot>
      <tr><td colspan="3" class="n">Subtotal</td><td class="n">${v.subtotal.toFixed(2)}</td></tr>
      <tr><td colspan="3" class="n">IVA</td><td class="n">${v.iva.toFixed(2)}</td></tr>
      <tr class="tot"><td colspan="3" class="n">TOTAL C$</td><td class="n">${v.total.toFixed(2)}</td></tr>
      <tr><td colspan="3" class="n">Pago</td><td class="n">${v.metodo}</td></tr>
      ${v.vuelto > 0 ? `<tr><td colspan="3" class="n">Vuelto</td><td class="n">${v.vuelto.toFixed(2)}</td></tr>` : ''}
    </tfoot>
  </table>
  <div class="c" style="margin-top:8px">¡Gracias por su compra!</div>
</body></html>`;
  const win = window.open('', '_blank', 'width=420,height=600');
  if (!win) {
    $q.notify({ type: 'warning', message: 'El navegador bloqueó la ventana del ticket.' });
    return;
  }
  win.document.write(html);
  win.document.close();
  win.focus();
  setTimeout(() => win.print(), 250);
}

// --- Corte de ventas -----------------------------------------------------------------
const dlgCorte = ref(false);
const corte = ref<PosReport | null>(null);
const corteFecha = ref('');
const cargandoCorte = ref(false);

function abrirCorte() {
  corteFecha.value = new Date().toISOString().slice(0, 10);
  dlgCorte.value = true;
  void cargarCorte();
}

async function cargarCorte() {
  cargandoCorte.value = true;
  try {
    corte.value = await getPosReport(corteFecha.value || undefined);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cargar el corte.') });
  } finally {
    cargandoCorte.value = false;
  }
}

// --- Devolución -----------------------------------------------------------------------
const dlgDevolucion = ref(false);
const devNumero = ref('');
const devDoc = ref<BillingDocRow | null>(null);
const devMotivo = ref('');
const devRestock = ref(true);
const devBuscando = ref(false);
const devEmitiendo = ref(false);

function abrirDevolucion() {
  devNumero.value = '';
  devDoc.value = null;
  devMotivo.value = '';
  devRestock.value = true;
  dlgDevolucion.value = true;
}

async function buscarFacturaDevolucion() {
  devDoc.value = null;
  const numero = devNumero.value.trim();
  if (!numero) return;
  devBuscando.value = true;
  try {
    const docs = await listBillingDocs({ q: numero, doc_type: 'INVOICE', status: 'ISSUED' });
    devDoc.value = docs.find((d) => String(d.number) === numero) ?? docs[0] ?? null;
    if (!devDoc.value) {
      $q.notify({ type: 'negative', message: `No se encontró la factura ${numero}.` });
    }
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo buscar.') });
  } finally {
    devBuscando.value = false;
  }
}

async function emitirDevolucion() {
  if (!devDoc.value) return;
  devEmitiendo.value = true;
  try {
    const r = await issueCreditNote(devDoc.value.id, {
      reason: devMotivo.value.trim(),
      restock: devRestock.value,
    });
    dlgDevolucion.value = false;
    $q.notify({
      type: 'positive',
      message: `Nota de crédito #${r.number} por ${formatMoney(r.total)}${devRestock.value ? '; mercadería reingresada' : ''}.`,
    });
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo emitir la devolución.') });
  } finally {
    devEmitiendo.value = false;
  }
}

// --- Tickets en espera (localStorage) -------------------------------------------
interface TicketEspera {
  id: string;
  etiqueta: string;
  total: number;
  clienteId: number | null;
  clienteNombre?: string;
  lineas: { item: InventoryItem; quantity: number; manual: boolean; unit_price: number; discount_pct: number }[];
}

const claveEspera = computed(() => `caja-espera:${ctx.activeCompanyId ?? 0}`);
const enEspera = ref<TicketEspera[]>([]);

function cargarEspera() {
  try {
    enEspera.value = JSON.parse(localStorage.getItem(claveEspera.value) ?? '[]') as TicketEspera[];
  } catch {
    enEspera.value = [];
  }
}

function persistirEspera() {
  localStorage.setItem(claveEspera.value, JSON.stringify(enEspera.value));
}

function dejarEnEspera() {
  enEspera.value.push({
    id: newUuid(),
    etiqueta: clienteNombre.value || `Ticket ${new Date().toLocaleTimeString('es-NI')}`,
    total: totales.value.total,
    clienteId: clienteId.value,
    clienteNombre: clienteNombre.value,
    lineas: carrito.value.map((l) => ({
      item: l.item,
      quantity: l.quantity,
      manual: l.manual,
      unit_price: l.unit_price,
      discount_pct: l.discount_pct,
    })),
  });
  persistirEspera();
  vaciarCarrito();
  $q.notify({ type: 'info', message: 'Ticket en espera; lo retomás desde el botón de arriba.' });
}

async function reanudarTicket(t: TicketEspera) {
  carrito.value = t.lineas.map((l) => ({ ...l }));
  clienteId.value = t.clienteId;
  clienteNombre.value = t.clienteNombre ?? '';
  cuenta.value = null;
  cuentaError.value = '';
  if (t.clienteId != null) {
    cuentaCargando.value = true;
    try {
      const restored = await rehydrateHeldCustomer(t, getCreditAccount);
      cuenta.value = restored.account;
    } catch (error) {
      cuentaError.value = apiErrorMessage(error, 'No se pudo consultar el crédito del cliente.');
      $q.notify({ type: 'negative', message: cuentaError.value });
    } finally {
      cuentaCargando.value = false;
    }
  }
  borrarTicket(t.id);
  enfocarEscaner();
}

function borrarTicket(id: string) {
  enEspera.value = enEspera.value.filter((t) => t.id !== id);
  persistirEspera();
}

// --- Atajos de teclado ------------------------------------------------------------
// Leyenda de atajos (se muestra en el menú ⌨ de la barra de caja).
const atajos = [
  { tecla: 'F2', que: 'Cobrar' },
  { tecla: 'F3', que: 'Volver al escáner' },
  { tecla: 'F4', que: 'Cliente' },
  { tecla: 'F6', que: 'Traer auto-factura' },
  { tecla: 'F7', que: 'Devolución' },
  { tecla: 'F8', que: 'Corte del día' },
  { tecla: 'F9', que: 'Vaciar carrito' },
  { tecla: '− / +', que: 'Cantidad por línea (botones)' },
  { tecla: 'Enter', que: 'Confirmar (escáner / cobro)' },
];

// ¿Hay algún diálogo abierto? Con uno abierto NO interceptamos atajos globales (que el diálogo
// maneje su Enter/Esc y los suyos).
const algunDialogoAbierto = computed(
  () =>
    dlgCobro.value ||
    dlgListo.value ||
    dlgCorte.value ||
    dlgDevolucion.value ||
    dlgAutorizar.value ||
    dlgAutoFactura.value ||
    arqueoOpen.value,
);

// Atajos de teclado del cajero (solo F-keys → no chocan con el escáner, que está siempre enfocado;
// la cantidad se ajusta con los steppers táctiles de cada línea).
function onTecla(ev: KeyboardEvent) {
  if (algunDialogoAbierto.value) return;
  switch (ev.key) {
    case 'F2':
      if (carrito.value.length && bodegaId.value) {
        ev.preventDefault();
        abrirCobro();
      }
      break;
    case 'F3': // volver a escanear
      ev.preventDefault();
      enfocarEscaner();
      break;
    case 'F4': // cliente
      ev.preventDefault();
      selectorCliente.value?.$el?.querySelector('input')?.focus();
      break;
    case 'F6': // auto-factura
      ev.preventDefault();
      abrirAutoFactura();
      break;
    case 'F7': // devolución
      ev.preventDefault();
      abrirDevolucion();
      break;
    case 'F8': // corte del día
      ev.preventDefault();
      abrirCorte();
      break;
    case 'F9': // vaciar carrito
      if (carrito.value.length) {
        ev.preventDefault();
        vaciarCarritoConfirm();
      }
      break;
  }
}

watch(bodegaId, () => {
  void cargarStock();
});

onMounted(async () => {
  window.addEventListener('keydown', onTecla);
  cargarEspera();
  void cargarSesionCaja();
  try {
    const [whs, items] = await Promise.all([listWarehouses(), listItems()]);
    bodegas.value = whs;
    bodegaId.value = whs.find((w) => w.is_default)?.id ?? whs[0]?.id ?? null;
    articulos.value = items.filter((it) => it.sale_price != null || it.wholesale_price != null);
    void cargarStock();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cargar el catálogo.') });
  }
});

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onTecla);
});
</script>

<style scoped>
.caja-bodega {
  width: 200px;
}

.caja-escaner {
  display: flex;
  gap: var(--app-space-3);
  margin-bottom: var(--app-space-3);
  flex-wrap: wrap;
}

.caja-escaner__input {
  flex: 2;
  min-width: 280px;
  font-size: 1.1rem;
}

.caja-escaner__buscar {
  flex: 1;
  min-width: 220px;
}

.caja-cuerpo {
  display: flex;
  gap: var(--app-space-4);
  align-items: flex-start;
  flex-wrap: wrap;
}

.caja-izquierda {
  flex: 2;
  min-width: 340px;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
}

.caja-grid__cats {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-1);
  margin-bottom: var(--app-space-2);
}

/* Chip de categoría: SIEMPRE tintado con su acento; se rellena al activarse */
.caja-cat {
  background: color-mix(in srgb, var(--acc) 15%, transparent);
  border: 1px solid color-mix(in srgb, var(--acc) 42%, transparent);
  color: var(--acc);
  font-weight: 700;
}

.caja-cat--activa {
  background: var(--acc);
  border-color: transparent;
  color: #fff;
  box-shadow: var(--app-shadow-soft);
}

.caja-grid__items {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: var(--app-space-2);
  max-height: 300px;
  overflow-y: auto;
  padding: 2px;
}

.caja-grid__card {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  padding: var(--app-space-2);
  border: 1px solid var(--app-border);
  border-left: 5px solid var(--acc);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-strong);
  box-shadow: var(--app-shadow-soft);
  color: var(--app-text);
  cursor: pointer;
  text-align: left;
  font: inherit;
  transition: transform 0.08s ease, box-shadow 0.08s ease, background 0.08s ease;
}

.caja-grid__card:hover {
  background: color-mix(in srgb, var(--acc) 8%, var(--app-surface-strong));
  box-shadow: var(--app-shadow-card);
  transform: translateY(-1px);
}

.caja-grid__card:active {
  transform: translateY(0);
}

/* Tile con la inicial, con el gradiente de la categoría (da color sin arcoíris) */
.caja-grid__tile {
  flex: 0 0 auto;
  width: 42px;
  height: 42px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--app-radius-md);
  background: var(--grad);
  color: #fff;
  font-weight: 700;
  font-size: 1.1rem;
  box-shadow: var(--app-shadow-soft);
}

.caja-grid__body {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.caja-grid__nombre {
  font-size: 0.82rem;
  line-height: 1.15;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
}

.caja-grid__precio {
  font-weight: 800;
  color: var(--app-primary);
}

.caja-grid__mayoreo {
  font-size: 0.7rem;
  color: var(--app-text-muted);
}

.caja-grid__vacio {
  grid-column: 1 / -1;
  padding: var(--app-space-3);
}

.caja-vacio {
  padding: var(--app-space-6) 0;
}

.caja-sku {
  font-size: 0.75rem;
}

.caja-num {
  max-width: 110px;
  margin-left: auto;
}

/* Cantidad con steppers ± (táctil/mouse) */
.caja-cant {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 2px;
}
.caja-cant__btn {
  color: var(--app-primary);
}
.caja-cant__input {
  max-width: 64px;
  margin-left: 0;
}

/* Flash al agregar/incrementar una línea (confirmación visual) */
@keyframes caja-flash {
  0% { background: var(--app-primary); }
  100% { background: transparent; }
}
.caja-linea--flash > td {
  animation: caja-flash 0.7s ease-out;
}

/* Botones de efectivo rápido en el diálogo de cobro */
.caja-rapido {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-2);
  margin-bottom: var(--app-space-3);
}

/* Leyenda de atajos */
.caja-atajos {
  min-width: 220px;
}
.caja-kbd {
  display: inline-block;
  min-width: 34px;
  text-align: center;
  padding: 1px 6px;
  border: 1px solid var(--app-border-strong);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-strong);
  font-size: 0.72rem;
  font-family: monospace;
  color: var(--app-text);
}

.caja-badge-mayoreo {
  margin-left: 4px;
}

.caja-panel {
  flex: 1;
  min-width: 280px;
  position: sticky;
  top: 70px;
  background: var(--app-surface-strong);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  box-shadow: var(--app-shadow-card);
  padding: var(--app-space-4);
}

.caja-cuenta {
  margin-top: var(--app-space-2);
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  font-size: 0.85rem;
}

.caja-cuenta--sin {
  color: var(--app-text-muted);
}

.caja-totales__fila {
  display: flex;
  justify-content: space-between;
  padding: 2px 0;
}

.caja-totales__total {
  font-size: 1.6rem;
  font-weight: 800;
  color: var(--app-primary);
  border-top: 1px solid var(--app-border);
  margin-top: var(--app-space-2);
  padding-top: var(--app-space-2);
}

.caja-cobro {
  width: 460px;
}

.caja-cobro__total {
  text-align: center;
}

.caja-cobro__monto {
  font-size: 2.4rem;
  font-weight: 800;
  color: var(--app-primary);
}

.caja-cobro__metodos {
  display: flex;
  gap: var(--app-space-2);
  flex-wrap: wrap;
  justify-content: center;
}

/* Métodos de pago: cada uno con su acento (color con significado) */
.caja-metodo {
  border: 1px solid color-mix(in srgb, var(--acc) 45%, transparent);
  background: color-mix(in srgb, var(--acc) 12%, transparent);
  color: var(--acc);
  font-weight: 700;
}

.caja-metodo--sel {
  background: var(--acc);
  border-color: transparent;
  color: #fff;
  box-shadow: var(--app-shadow-soft);
}

.caja-cobro__vuelto {
  font-size: 1.2rem;
  font-weight: 600;
  text-align: right;
}

.caja-cobro__vuelto--falta {
  color: var(--q-negative);
}

.caja-cobro__mixto-fila {
  display: flex;
  gap: var(--app-space-2);
  align-items: center;
}

.caja-cobro__mixto-metodo {
  min-width: 150px;
}

.caja-cobro__credito {
  text-align: center;
  color: var(--app-text-muted);
}

.caja-listo {
  width: 380px;
}

.caja-listo__vuelto {
  font-size: 1.3rem;
  margin-top: var(--app-space-2);
}

.caja-corte {
  width: 560px;
  max-width: 95vw;
}

.caja-corte__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: var(--app-space-3);
}

.caja-corte__stat {
  border-radius: var(--app-radius-md);
  background: var(--grad, var(--app-surface));
  color: #fff;
  padding: var(--app-space-3);
  box-shadow: var(--app-shadow-soft);
}

.caja-corte__rotulo {
  font-size: 0.8rem;
  color: rgba(255, 255, 255, 0.85);
}

.caja-corte__cifra {
  font-size: 1.15rem;
  font-weight: 700;
}

/* --- Barra de estado (sesión de caja + autorización) --- */
.caja-estado {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  flex-wrap: wrap;
  padding: var(--app-space-2) var(--app-space-3);
  margin-bottom: var(--app-space-3);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-strong);
  box-shadow: var(--app-shadow-soft);
}

.caja-estado__txt {
  font-size: 0.9rem;
}

.caja-estado__txt--alerta {
  color: var(--q-negative);
  font-weight: 600;
}

.caja-estado__link {
  color: var(--app-primary);
  font-weight: 600;
  margin-left: var(--app-space-1);
}

/* --- Aviso de stock bajo --- */
.caja-grid__card--bajo {
  border-color: var(--q-warning);
}

.caja-grid__stock {
  font-size: 0.68rem;
  color: var(--q-warning);
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 2px;
}

.caja-stock-alerta {
  font-size: 0.72rem;
  color: var(--q-warning);
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 2px;
}

.caja-autorizar {
  width: 420px;
  max-width: 95vw;
}

/* --- Responsive: tableta y pantallas medianas --- */
@media (max-width: 1024px) {
  .caja-panel {
    position: static;
    flex: 1 1 100%;
  }

  .caja-grid__items {
    max-height: 360px;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  }

  /* Objetivos táctiles más grandes para dedo en tableta */
  .caja-grid__card {
    min-height: 68px;
    padding: var(--app-space-3);
  }

  .caja-grid__tile {
    width: 48px;
    height: 48px;
    font-size: 1.25rem;
  }
}

@media (max-width: 600px) {
  .caja-escaner__input,
  .caja-escaner__buscar {
    min-width: 100%;
  }

  .caja-grid__items {
    grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  }
}
</style>
