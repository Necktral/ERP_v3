// Catálogo de navegación de la consola (arquitectura de información).
//
// Organizado por ÁREA DE TRABAJO del holding Agrícola Santa Isabel (no por capa
// técnica): el menú refleja cómo opera el negocio. La VISIBILIDAD efectiva se
// calcula en runtime dentro de AppLayout: un ítem se muestra solo si la empresa
// tiene el módulo habilitado (effective_modules) Y el usuario tiene el permiso
// → "módulos sin dueño". Los ítems con `module: null` son del núcleo (solo
// exigen permiso). En el CEL solo se muestran los ítems `mobile: true` (operación
// de campo); el resto del sistema es de PC. Las secciones sin ítems visibles se
// ocultan solas.

export type NavSection =
  | 'Tablero'
  | 'Operación agrícola'
  | 'Comercio'
  | 'Caja'
  | 'Abastecimiento'
  | 'Personal y Nómina'
  | 'Holding'
  | 'Contador'
  | 'Sistema';

export interface NavItem {
  module: string | null; // null = transversal (no depende de módulos de la empresa)
  label: string;
  icon: string;
  to: string;
  perm: string;
  section: NavSection;
  mobile?: boolean; // visible en la experiencia LIMITADA del cel
}

// Orden = prioridad operativa. Contador y Sistema van al fondo (de-priorizados:
// la contabilidad la lleva el contador externo).
export const NAV_SECTIONS: NavSection[] = [
  'Tablero',
  'Operación agrícola',
  'Comercio',
  'Caja',
  'Abastecimiento',
  'Personal y Nómina',
  'Holding',
  'Contador',
  'Sistema',
];

export const NAV: NavItem[] = [
  // ===== Tablero (inicio en vivo del holding) =====
  {
    module: null, // transversal: es el inicio, no depende de módulos de la empresa
    label: 'Tablero',
    icon: 'dashboard',
    to: '/tablero',
    perm: 'knowledge.docs.read',
    section: 'Tablero',
  },
  {
    module: 'analytics',
    label: 'Analítica',
    icon: 'insights',
    to: '/analitica',
    perm: 'report.dashboard.read',
    section: 'Tablero',
  },

  // ===== Operación agrícola =====
  {
    module: 'finca',
    label: 'Finca',
    icon: 'agriculture',
    to: '/finca',
    perm: 'finca.finca.read',
    section: 'Operación agrícola',
  },
  {
    module: 'finca',
    label: 'Reportes de finca',
    icon: 'assessment',
    to: '/finca/reportes',
    perm: 'finca.report.read',
    section: 'Operación agrícola',
  },
  {
    module: 'financiamiento',
    label: 'Acopio y Financiamiento',
    icon: 'savings',
    to: '/financiamiento',
    perm: 'financing.producer.read',
    section: 'Operación agrícola',
  },
  {
    module: 'financiamiento',
    label: 'Recibos de café',
    icon: 'scale',
    to: '/financiamiento/acopio',
    perm: 'financing.reception.read',
    section: 'Operación agrícola',
  },
  {
    module: 'financiamiento',
    label: 'Préstamos',
    icon: 'request_quote',
    to: '/financiamiento/prestamos',
    perm: 'financing.loan.read',
    section: 'Operación agrícola',
  },
  {
    module: 'financiamiento',
    label: 'Riesgo de cartera',
    icon: 'query_stats',
    to: '/financiamiento/riesgo',
    perm: 'financing.risk.read',
    section: 'Operación agrícola',
  },
  {
    module: 'financiamiento',
    label: 'Configuración de acopio',
    icon: 'tune',
    to: '/financiamiento/configuracion',
    perm: 'financing.settings.manage',
    section: 'Operación agrícola',
  },
  {
    module: 'beneficio',
    label: 'Beneficio de café',
    icon: 'coffee_maker',
    to: '/beneficio',
    perm: 'beneficio.order.read',
    section: 'Operación agrícola',
  },
  {
    module: 'fleet',
    label: 'Flota',
    icon: 'local_shipping',
    to: '/flota',
    perm: 'fleet.asset.read',
    section: 'Operación agrícola',
  },

  // ===== Comercio (comisariato + estación) =====
  {
    module: 'comisariato',
    label: 'Comisariato',
    icon: 'storefront',
    to: '/comisariato',
    perm: 'comisariato.read',
    section: 'Comercio',
  },
  {
    module: 'comisariato',
    label: 'Venta comisariato',
    icon: 'shopping_bag',
    to: '/comisariato/venta',
    perm: 'comisariato.sell',
    section: 'Comercio',
  },
  {
    module: 'fuel',
    label: 'Estación de Servicio',
    icon: 'local_gas_station',
    to: '/estacion',
    perm: 'fuel.shift.read',
    section: 'Comercio',
  },
  {
    module: 'retail_pos',
    label: 'POS Combustible',
    icon: 'shopping_cart_checkout',
    to: '/pos',
    perm: 'retail.pos.session.read',
    section: 'Comercio',
  },

  // ===== Caja (tesorería única: ventas + caja + pagos + bancos + cartera) =====
  {
    module: 'pos',
    label: 'Punto de venta',
    icon: 'point_of_sale',
    to: '/ventas',
    perm: 'sales.pos.sell',
    section: 'Caja',
  },
  {
    module: 'pos',
    label: 'Auto-factura',
    icon: 'qr_code_2',
    to: '/auto-factura',
    perm: 'sales.pos.self_service',
    section: 'Caja',
    mobile: true,
  },
  {
    module: 'billing',
    label: 'Facturación',
    icon: 'receipt',
    to: '/facturacion',
    perm: 'billing.doc.read',
    section: 'Caja',
  },
  {
    module: 'billing',
    label: 'Pedidos',
    icon: 'assignment',
    to: '/facturacion/pedidos',
    perm: 'billing.order.read',
    section: 'Caja',
  },
  {
    module: 'billing',
    label: 'Aprobaciones de crédito',
    icon: 'rule',
    to: '/facturacion/aprobaciones-credito',
    perm: 'billing.order.approve',
    section: 'Caja',
  },
  {
    module: 'payments',
    label: 'Sesiones de caja',
    icon: 'inventory_2',
    to: '/caja',
    perm: 'payments.cash_session.read',
    section: 'Caja',
  },
  {
    module: 'payments',
    label: 'Cobros y pagos',
    icon: 'paid',
    to: '/caja/pagos',
    perm: 'payments.intent.read',
    section: 'Caja',
  },
  {
    module: 'payments',
    label: 'Bancos',
    icon: 'account_balance',
    to: '/caja/bancos',
    perm: 'payments.bank.read',
    section: 'Caja',
  },
  {
    module: 'portfolio',
    label: 'Cartera',
    icon: 'account_balance_wallet',
    to: '/cartera',
    perm: 'portfolio.receivable.read',
    section: 'Caja',
  },
  {
    module: 'billing',
    label: 'Historial de ventas',
    icon: 'receipt_long',
    to: '/ventas/historial',
    perm: 'billing.doc.read',
    section: 'Caja',
  },

  // ===== Abastecimiento (inventario + compras + terceros) =====
  {
    module: 'inventory',
    label: 'Inventario',
    icon: 'inventory',
    to: '/inventario',
    perm: 'inventory.balance.read',
    section: 'Abastecimiento',
  },
  {
    module: 'inventory',
    label: 'Catálogo de inventario',
    icon: 'category',
    to: '/inventario/catalogo',
    perm: 'inventory.item.read',
    section: 'Abastecimiento',
  },
  {
    module: 'inventory',
    label: 'Conteo físico',
    icon: 'fact_check',
    to: '/inventario/conteo',
    perm: 'inventory.count.read',
    section: 'Abastecimiento',
  },
  {
    module: 'inventory',
    label: 'Listas de precios',
    icon: 'sell',
    to: '/inventario/listas-precios',
    perm: 'inventory.pricelist.read',
    section: 'Abastecimiento',
  },
  {
    module: 'procurement',
    label: 'Compras',
    icon: 'shopping_cart',
    to: '/compras',
    perm: 'procurement.doc.read',
    section: 'Abastecimiento',
  },
  {
    module: 'parties',
    label: 'Terceros',
    icon: 'contacts',
    to: '/terceros',
    perm: 'parties.party.read',
    section: 'Abastecimiento',
  },

  // ===== Personal y Nómina (consolidada del holding, cruza empresas por cédula) =====
  {
    module: 'payroll',
    label: 'Asistencia',
    icon: 'fact_check',
    to: '/asistencia',
    perm: 'nomina.field.read',
    section: 'Personal y Nómina',
    mobile: true,
  },
  {
    module: 'human_resources',
    label: 'Recursos Humanos',
    icon: 'groups',
    to: '/recursos-humanos',
    perm: 'hr.employee.read',
    section: 'Personal y Nómina',
  },
  {
    module: 'payroll',
    label: 'Nómina',
    icon: 'payments',
    to: '/nomina',
    perm: 'nomina.period.read',
    section: 'Personal y Nómina',
  },
  {
    module: 'payroll',
    label: 'Reloj biométrico',
    icon: 'fingerprint',
    to: '/nomina/biometrico',
    perm: 'nomina.attendance.read',
    section: 'Personal y Nómina',
  },
  {
    module: 'payroll',
    label: 'Cobrador-Pagador (CO-PA)',
    icon: 'point_of_sale',
    to: '/nomina/sala-de-pago',
    perm: 'nomina.payment.read',
    section: 'Personal y Nómina',
    mobile: true, // el pagador es una app de cel/tableta → debe verse en el shell móvil
  },

  // ===== Holding y trazabilidad (intercompañía + organización) =====
  {
    module: 'accounting',
    label: 'Intercompañía',
    icon: 'swap_horiz',
    to: '/contabilidad/intercompania',
    perm: 'accounting.intercompany.read',
    section: 'Holding',
  },
  {
    module: 'accounting',
    label: 'Cartera de grupo',
    icon: 'account_balance_wallet',
    to: '/contabilidad/cartera-grupo',
    perm: 'audit.read',
    section: 'Holding',
  },
  {
    module: 'organization',
    label: 'Organización',
    icon: 'corporate_fare',
    to: '/organizacion',
    perm: 'org.company.read',
    section: 'Holding',
  },
  {
    module: 'organization',
    label: 'Relaciones de empresas',
    icon: 'hub',
    to: '/organizacion?tab=relaciones',
    perm: 'org.company.read',
    section: 'Holding',
  },

  // ===== Contador (de-priorizado: la contabilidad la lleva el contador externo) =====
  {
    module: 'accounting',
    label: 'Contabilidad',
    icon: 'account_balance',
    to: '/contabilidad',
    perm: 'accounting.report.read',
    section: 'Contador',
  },
  {
    module: 'accounting',
    label: 'Consolidación del grupo',
    icon: 'account_tree',
    to: '/contabilidad/consolidacion',
    perm: 'accounting.consolidation.read',
    section: 'Contador',
  },
  {
    module: 'cec',
    label: 'Cierre contable (CEC)',
    icon: 'all_inclusive',
    to: '/cec',
    perm: 'cec.close_run.read',
    section: 'Contador',
  },

  // ===== Sistema =====
  {
    module: 'organization',
    label: 'Usuarios y acceso',
    icon: 'admin_panel_settings',
    to: '/usuarios',
    perm: 'rbac.assignments.read',
    section: 'Sistema',
  },
  {
    module: 'audit',
    label: 'Auditoría',
    icon: 'history_edu',
    to: '/auditoria',
    perm: 'audit.read',
    section: 'Sistema',
  },
  {
    module: 'controls',
    label: 'Controles',
    icon: 'gpp_maybe',
    to: '/controles',
    perm: 'controls.sod.read',
    section: 'Sistema',
  },
  {
    module: 'alertas',
    label: 'Alertas',
    icon: 'notifications_active',
    to: '/alertas',
    perm: 'alerts.read',
    section: 'Sistema',
  },
  {
    module: 'documents',
    label: 'Documentos',
    icon: 'document_scanner',
    to: '/documentos',
    perm: 'documents.scan.read',
    section: 'Sistema',
  },
  {
    module: 'knowledge',
    label: 'Conocimiento',
    icon: 'menu_book',
    to: '/conocimiento',
    perm: 'knowledge.docs.read',
    section: 'Sistema',
  },
  {
    module: null, // herramienta de desarrollo (dev/dueño): solo exige el permiso, no un módulo
    label: 'Feedback de código',
    icon: 'travel_explore',
    to: '/feedback-codigo',
    perm: 'knowledge.dev.read',
    section: 'Sistema',
  },
  {
    module: 'knowledge',
    label: 'Manual',
    icon: 'help_center',
    to: '/manual',
    perm: 'knowledge.docs.read',
    section: 'Sistema',
  },
  {
    module: 'diagnostics',
    label: 'Diagnóstico',
    icon: 'monitor_heart',
    to: '/diagnostico',
    perm: 'diagnostics.error.read',
    section: 'Sistema',
  },
  {
    module: 'synchronization',
    label: 'Dispositivos',
    icon: 'devices',
    to: '/dispositivos',
    perm: 'sync.device.enroll',
    section: 'Sistema',
  },
];
