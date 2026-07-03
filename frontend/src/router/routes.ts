import { Platform } from 'quasar';
import type { RouteRecordRaw } from 'vue-router';
import { isNativeApp } from 'src/core/platform';

// Frontend en reconstrucción alrededor del modelo multi-empresa.
// Auth (público) + app gated (AppLayout) con Recursos Humanos como primer módulo.
const routes: RouteRecordRaw[] = [
  {
    path: '/bootstrap',
    component: () => import('layouts/AuthLayout.vue'),
    children: [
      {
        path: '',
        component: () => import('src/modules/auth/pages/BootstrapWizardPage.vue'),
        meta: { requiresAuth: false },
      },
    ],
  },
  {
    path: '/password-change',
    component: () => import('layouts/AuthLayout.vue'),
    children: [
      {
        path: '',
        component: () => import('src/modules/auth/pages/ForcePasswordChangePage.vue'),
        meta: { requiresAuth: true },
      },
    ],
  },
  {
    path: '/enrolar',
    component: () => import('layouts/AuthLayout.vue'),
    children: [
      {
        path: '',
        component: () => import('src/modules/devices/pages/EnrolarDispositivoPage.vue'),
        meta: { requiresAuth: false },
      },
    ],
  },
  {
    path: '/select-context',
    component: () => import('layouts/AuthLayout.vue'),
    children: [
      {
        path: '',
        component: () => import('src/modules/auth/pages/SelectContextPage.vue'),
        meta: { requiresAuth: true },
      },
    ],
  },
  {
    path: '/403',
    component: () => import('layouts/AuthLayout.vue'),
    children: [
      {
        path: '',
        component: () => import('pages/ForbiddenPage.vue'),
        meta: { requiresAuth: true },
      },
    ],
  },
  {
    path: '/login',
    component: () => import('layouts/AuthLayout.vue'),
    children: [
      {
        path: '',
        component: () => import('src/modules/auth/pages/LoginPage.vue'),
        meta: { requiresAuth: false },
      },
      {
        path: '2fa',
        component: () => import('src/modules/auth/pages/TwoFactorPage.vue'),
        meta: { requiresAuth: false },
      },
    ],
  },
  {
    // Kiosko de auto-factura: pantalla completa, sin menú. El dispositivo se loguea UNA vez
    // con la cuenta de kiosko (perms sales.pos.self_service + inventory.item.read, fija a 1 sucursal).
    path: '/kiosko',
    component: () => import('layouts/KioskLayout.vue'),
    children: [
      {
        path: '',
        name: 'kiosko-autofactura',
        component: () => import('src/modules/ventas/pages/AutoFacturaPage.vue'),
        meta: {
          requiresAuth: true,
          requiresContext: true,
          requiredPermissions: ['sales.pos.self_service'],
          kiosko: true,
        },
      },
    ],
  },
  {
    path: '/',
    component: () => import('layouts/AppLayout.vue'),
    meta: { requiresAuth: true, requiresContext: true },
    children: [
      // La APK nativa es MONOPROPÓSITO: solo CO-PA (Sala de Pago). Arranca directo ahí y
      // no expone el resto del ERP (autofactura, asistencia, etc. — el drawer va oculto).
      // En el cel-web la experiencia es LIMITADA: entra a Asistencia. En PC, el Tablero.
      {
        path: '',
        redirect: () =>
          isNativeApp() ? '/nomina/sala-de-pago' : Platform.is.mobile ? '/asistencia' : '/tablero',
      },
      {
        path: 'tablero',
        name: 'tablero',
        component: () => import('src/modules/dashboard/pages/TableroPage.vue'),
        // Sin permiso específico: es el inicio. La página degrada con gracia si
        // el resumen no trae secciones (o falta knowledge.docs.read).
        meta: { requiresAuth: true, requiresContext: true },
      },
      {
        path: 'asistencia',
        name: 'asistencia',
        component: () => import('src/modules/asistencia/pages/AsistenciaPage.vue'),
        // read = entrar a ver (supervisor); marcar exige nomina.field.capture (la página lo controla)
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['nomina.field.read'] },
      },
      {
        path: 'recursos-humanos',
        name: 'rrhh-home',
        component: () => import('src/modules/hr/pages/HrHomePage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['hr.employee.read'] },
      },
      {
        path: 'recursos-humanos/puestos',
        name: 'rrhh-puestos',
        component: () => import('src/modules/hr/pages/PuestosPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['hr.position.read'] },
      },
      {
        path: 'recursos-humanos/trabajadores',
        name: 'rrhh-trabajadores',
        component: () => import('src/modules/hr/pages/TrabajadoresPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['hr.employee.read'] },
      },
      {
        path: 'recursos-humanos/trabajadores/nuevo',
        name: 'rrhh-trabajadores-nuevo',
        component: () => import('src/modules/hr/pages/NuevoTrabajadorPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['hr.employee.create'] },
      },
      {
        path: 'recursos-humanos/trabajadores/:id(\\d+)',
        name: 'rrhh-trabajador-perfil',
        component: () => import('src/modules/hr/pages/TrabajadorPerfilPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['hr.employee.read'] },
      },
      {
        path: 'recursos-humanos/contratos',
        name: 'rrhh-contratos',
        component: () => import('src/modules/hr/pages/ContratosPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['hr.contract.read'] },
      },
      {
        path: 'recursos-humanos/vacaciones',
        name: 'rrhh-vacaciones',
        component: () => import('src/modules/hr/pages/VacacionesPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['hr.vacation.read'] },
      },
      {
        path: 'nomina',
        name: 'nomina',
        component: () => import('src/modules/nomina/pages/NominaPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['nomina.period.read'] },
      },
      {
        path: 'nomina/biometrico',
        name: 'nomina-biometrico',
        component: () => import('src/modules/biometrico/pages/BiometricoPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['nomina.attendance.read'] },
      },
      {
        path: 'nomina/periodos/:id(\\d+)',
        name: 'nomina-periodo',
        component: () => import('src/modules/nomina/pages/PeriodoDetallePage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['nomina.period.read'] },
      },
      {
        path: 'nomina/periodos/:id(\\d+)/complemento',
        name: 'nomina-periodo-complemento',
        component: () => import('src/modules/nomina/pages/ComplementoPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['nomina.complement.read'] },
      },
      {
        path: 'nomina/periodos/:id(\\d+)/inss',
        name: 'nomina-periodo-inss',
        component: () => import('src/modules/nomina/pages/RegimenInssPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['nomina.inss.read'] },
      },
      {
        path: 'nomina/sala-de-pago',
        name: 'sala-de-pago',
        component: () => import('src/modules/pagador/pages/SalaDePagoPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['nomina.payment.read'] },
      },
      {
        path: 'dispositivos',
        name: 'dispositivos',
        component: () => import('src/modules/devices/pages/DispositivosPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['sync.device.enroll'] },
      },
      {
        path: 'inventario',
        name: 'inventario',
        component: () => import('src/modules/inventory/pages/ExistenciasPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['inventory.balance.read'] },
      },
      {
        path: 'inventario/kardex',
        name: 'inventario-kardex',
        component: () => import('src/modules/inventory/pages/KardexPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['inventory.movement.read'] },
      },
      {
        path: 'inventario/catalogo',
        name: 'inventario-catalogo',
        component: () => import('src/modules/inventory/pages/CatalogoInventarioPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['inventory.item.read'] },
      },
      {
        path: 'inventario/conteo',
        name: 'inventario-conteo',
        component: () => import('src/modules/inventory/pages/ConteoFisicoPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['inventory.count.read'] },
      },
      {
        path: 'inventario/listas-precios',
        name: 'inventario-listas-precios',
        component: () => import('src/modules/inventory/pages/ListasPreciosPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['inventory.pricelist.read'] },
      },
      {
        path: 'inventario/producto/:itemId',
        name: 'inventario-producto',
        component: () => import('src/modules/inventory/pages/ProductoDetallePage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['inventory.item.read'] },
      },
      {
        path: 'compras',
        name: 'compras',
        component: () => import('src/modules/procurement/pages/ComprasPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['procurement.doc.read'] },
      },
      {
        path: 'compras/oc/:id(\\d+)',
        name: 'compra-oc-detalle',
        component: () => import('src/modules/procurement/pages/OrdenCompraDetallePage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['procurement.order.read'] },
      },
      {
        path: 'compras/:id(\\d+)',
        name: 'compra-detalle',
        component: () => import('src/modules/procurement/pages/CompraDetallePage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['procurement.doc.read'] },
      },
      {
        path: 'ventas',
        name: 'ventas',
        component: () => import('src/modules/ventas/pages/CajaVentaPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['sales.pos.sell'] },
      },
      {
        path: 'ventas/historial',
        name: 'ventas-historial',
        component: () => import('src/modules/ventas/pages/HistorialVentasPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['billing.doc.read'] },
      },
      {
        path: 'auto-factura',
        name: 'auto-factura',
        component: () => import('src/modules/ventas/pages/AutoFacturaPage.vue'),
        meta: {
          requiresAuth: true,
          requiresContext: true,
          requiredPermissions: ['sales.pos.self_service'],
        },
      },
      {
        path: 'facturacion',
        name: 'facturacion',
        component: () => import('src/modules/billing/pages/FacturacionPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['billing.doc.read'] },
      },
      {
        path: 'facturacion/config-fiscal',
        name: 'facturacion-config-fiscal',
        component: () => import('src/modules/billing/pages/ConfigFiscalPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['billing.fiscal.config.read'] },
      },
      {
        path: 'facturacion/pedidos',
        name: 'facturacion-pedidos',
        component: () => import('src/modules/billing/pages/PedidosPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['billing.order.read'] },
      },
      {
        path: 'facturacion/aprobaciones-credito',
        name: 'facturacion-aprobaciones-credito',
        component: () => import('src/modules/billing/pages/AprobacionesCreditoPage.vue'),
        meta: {
          requiresAuth: true,
          requiresContext: true,
          requiredPermissions: ['billing.order.read', 'billing.order.approve'],
        },
      },
      {
        path: 'facturacion/:id(\\d+)',
        name: 'factura-detalle',
        component: () => import('src/modules/billing/pages/FacturaDetallePage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['billing.doc.read'] },
      },
      {
        path: 'caja',
        name: 'caja',
        component: () => import('src/modules/payments/pages/CajaPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['payments.cash_session.read'] },
      },
      {
        path: 'caja/sesiones',
        name: 'caja-sesiones',
        component: () => import('src/modules/payments/pages/SesionesCajaPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['payments.cash_session.read'] },
      },
      {
        path: 'caja/pagos',
        name: 'caja-pagos',
        component: () => import('src/modules/payments/pages/IntentosPagoPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['payments.intent.read'] },
      },
      {
        path: 'caja/bancos',
        name: 'caja-bancos',
        component: () => import('src/modules/payments/pages/BancosPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['payments.bank.read'] },
      },
      {
        path: 'cartera',
        name: 'cartera',
        component: () => import('src/modules/portfolio/pages/CarteraPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['portfolio.receivable.read'] },
      },
      {
        path: 'cartera/creditos',
        name: 'cartera-creditos',
        component: () => import('src/modules/portfolio/pages/CreditosPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['portfolio.credit.read'] },
      },
      {
        path: 'comisariato',
        name: 'comisariato',
        component: () => import('src/modules/comisariato/pages/ComisariatoPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['comisariato.read'] },
      },
      {
        path: 'comisariato/venta',
        name: 'comisariato-venta',
        component: () => import('src/modules/comisariato/pages/VentaComisariatoPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['comisariato.sell'] },
      },
      {
        path: 'estacion',
        name: 'estacion',
        component: () => import('src/modules/fuel/pages/EstacionPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['fuel.shift.read'] },
      },
      {
        path: 'estacion/turnos',
        name: 'estacion-turnos',
        component: () => import('src/modules/fuel/pages/TurnosPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['fuel.shift.read'] },
      },
      {
        path: 'estacion/reportes',
        name: 'estacion-reportes',
        component: () => import('src/modules/fuel/pages/ReportesEstacionPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['fuel.reports.view'] },
      },
      {
        path: 'estacion/tanques',
        name: 'estacion-tanques',
        component: () => import('src/modules/fuel/pages/TanquesPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['fuel.tank.read'] },
      },
      {
        path: 'pos',
        name: 'pos',
        component: () => import('src/modules/pos/pages/PosPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['retail.pos.session.read'] },
      },
      {
        path: 'pos/tickets',
        name: 'pos-tickets',
        component: () => import('src/modules/pos/pages/TicketsPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['retail.pos.ticket.read'] },
      },
      {
        path: 'finca',
        name: 'finca',
        component: () => import('src/modules/finca/pages/FincaPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['finca.finca.read'] },
      },
      {
        path: 'finca/ordenes',
        name: 'finca-ordenes',
        component: () => import('src/modules/finca/pages/OrdenesTrabajoPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['finca.work.read'] },
      },
      {
        path: 'finca/costos',
        name: 'finca-costos',
        component: () => import('src/modules/finca/pages/CostosFincaPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['finca.field.read'] },
      },
      {
        path: 'finca/presupuesto',
        name: 'finca-presupuesto',
        component: () => import('src/modules/finca/pages/PresupuestoFincaPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['finca.budget.read'] },
      },
      {
        path: 'finca/reportes',
        name: 'finca-reportes',
        component: () => import('src/modules/finca/pages/ReportesFincaPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['finca.report.read'] },
      },
      {
        path: 'financiamiento',
        name: 'financiamiento',
        component: () => import('src/modules/financiamiento/pages/FinanciamientoHomePage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['financing.producer.read'] },
      },
      {
        path: 'financiamiento/productores',
        name: 'financiamiento-productores',
        component: () => import('src/modules/financiamiento/pages/ProductoresPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['financing.producer.read'] },
      },
      {
        path: 'financiamiento/acopio',
        name: 'financiamiento-acopio',
        component: () => import('src/modules/financiamiento/pages/AcopioPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['financing.reception.read'] },
      },
      {
        path: 'financiamiento/prestamos',
        name: 'financiamiento-prestamos',
        component: () => import('src/modules/financiamiento/pages/PrestamosPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['financing.loan.read'] },
      },
      {
        path: 'financiamiento/liquidaciones',
        name: 'financiamiento-liquidaciones',
        component: () => import('src/modules/financiamiento/pages/LiquidacionesPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['financing.liquidation.read'] },
      },
      {
        path: 'financiamiento/riesgo',
        name: 'financiamiento-riesgo',
        component: () => import('src/modules/financiamiento/pages/RiesgoCarteraPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['financing.risk.read'] },
      },
      {
        path: 'financiamiento/configuracion',
        name: 'financiamiento-configuracion',
        component: () => import('src/modules/financiamiento/pages/ConfiguracionAcopioPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['financing.settings.manage'] },
      },
      {
        path: 'beneficio',
        name: 'beneficio',
        component: () => import('src/modules/beneficio/pages/BeneficioPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['beneficio.order.read'] },
      },
      {
        path: 'flota',
        name: 'flota',
        component: () => import('src/modules/fleet/pages/FlotaPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['fleet.asset.read'] },
      },
      {
        path: 'flota/conductores',
        name: 'flota-conductores',
        component: () => import('src/modules/fleet/pages/ConductoresPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['fleet.driver.read'] },
      },
      {
        path: 'flota/costos',
        name: 'flota-costos',
        component: () => import('src/modules/fleet/pages/CostosFlotaPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['fleet.cost.read'] },
      },
      {
        path: 'flota/mantenimiento',
        name: 'flota-mantenimiento',
        component: () => import('src/modules/fleet/pages/MantenimientoPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['fleet.maintenance.read'] },
      },
      {
        path: 'contabilidad',
        name: 'contabilidad',
        component: () => import('src/modules/accounting/pages/ContabilidadHomePage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['accounting.report.read'] },
      },
      {
        path: 'contabilidad/diario',
        name: 'contabilidad-diario',
        component: () => import('src/modules/accounting/pages/DiarioPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['accounting.journal_draft.read'] },
      },
      {
        path: 'contabilidad/plan-cuentas',
        name: 'contabilidad-plan',
        component: () => import('src/modules/accounting/pages/PlanCuentasPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['accounting.coa.read'] },
      },
      {
        path: 'contabilidad/periodos',
        name: 'contabilidad-periodos',
        component: () => import('src/modules/accounting/pages/PeriodosPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['accounting.period.read'] },
      },
      {
        path: 'contabilidad/reportes',
        name: 'contabilidad-reportes',
        component: () => import('src/modules/accounting/pages/ReportesContablesPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['accounting.report.read'] },
      },
      {
        path: 'contabilidad/reconciliacion-operativa',
        name: 'contabilidad-reconciliacion-operativa',
        component: () => import('src/modules/accounting/pages/ReconciliacionOperativaPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['accounting.report.read'] },
      },
      {
        path: 'contabilidad/monedas',
        name: 'contabilidad-monedas',
        component: () => import('src/modules/accounting/pages/MonedasPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['accounting.fx_rate.read'] },
      },
      {
        path: 'contabilidad/intercompania',
        name: 'contabilidad-intercompania',
        component: () => import('src/modules/accounting/pages/IntercompaniaPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['accounting.intercompany.read'] },
      },
      {
        path: 'contabilidad/cartera-grupo',
        name: 'contabilidad-cartera-grupo',
        component: () => import('src/modules/intercompany/pages/CarteraGrupoPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['audit.read'] },
      },
      {
        path: 'contabilidad/centros-costo',
        name: 'contabilidad-centros-costo',
        component: () => import('src/modules/accounting/pages/CentrosCostoPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['accounting.cost_center.read'] },
      },
      {
        path: 'contabilidad/presupuestos',
        name: 'contabilidad-presupuestos',
        component: () => import('src/modules/accounting/pages/PresupuestosPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['accounting.budget.read'] },
      },
      {
        path: 'contabilidad/cierre-anual',
        name: 'contabilidad-cierre-anual',
        component: () => import('src/modules/accounting/pages/CierreAnualPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['accounting.year_end.close'] },
      },
      {
        path: 'contabilidad/consolidacion',
        name: 'contabilidad-consolidacion',
        component: () => import('src/modules/accounting/pages/ConsolidacionPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['accounting.consolidation.read'] },
      },
      {
        path: 'cec',
        name: 'cec',
        component: () => import('src/modules/cec/pages/CecPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['cec.close_run.read'] },
      },
      {
        path: 'auditoria',
        name: 'auditoria',
        component: () => import('src/modules/audit/pages/BitacoraPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['audit.read'] },
      },
      {
        path: 'controles',
        name: 'controles',
        component: () => import('src/modules/controls/pages/ControlesPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['controls.sod.read'] },
      },
      {
        path: 'alertas',
        name: 'alertas',
        component: () => import('src/modules/alertas/pages/AlertasPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['alerts.read'] },
      },
      {
        path: 'analitica',
        name: 'analitica',
        component: () => import('src/modules/dashboard/pages/AnaliticaPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['report.dashboard.read'] },
      },
      {
        path: 'documentos',
        name: 'documentos',
        component: () => import('src/modules/documents/pages/EscaneosPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['documents.scan.read'] },
      },
      {
        path: 'conocimiento',
        name: 'conocimiento',
        component: () => import('src/modules/knowledge/pages/ConocimientoPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['knowledge.docs.read'] },
      },
      {
        path: 'feedback-codigo',
        name: 'feedback-codigo',
        component: () => import('src/modules/knowledge/pages/DevFeedbackPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['knowledge.dev.read'] },
      },
      {
        path: 'manual',
        name: 'manual',
        component: () => import('src/modules/knowledge/pages/ManualPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['knowledge.docs.read'] },
      },
      {
        path: 'diagnostico',
        name: 'diagnostico',
        component: () => import('src/modules/diagnostics/pages/DiagnosticoPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['diagnostics.error.read'] },
      },
      {
        path: 'terceros',
        name: 'terceros',
        component: () => import('src/modules/parties/pages/TercerosPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['parties.party.read'] },
      },
      {
        path: 'organizacion',
        name: 'organizacion',
        component: () => import('src/modules/org/pages/OrganizacionPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['org.company.read'] },
      },
      {
        path: 'usuarios',
        name: 'usuarios',
        component: () => import('src/modules/rbac/pages/UsuariosPage.vue'),
        meta: { requiresAuth: true, requiresContext: true, requiredPermissions: ['rbac.assignments.read'] },
      },
    ],
  },
  {
    path: '/:catchAll(.*)*',
    component: () => import('pages/ErrorNotFound.vue'),
  },
];

export default routes;
