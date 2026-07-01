/** Códigos de negocio de pagos/bancos → mensaje en español para el usuario. */
export const MENSAJES_BANCOS: Record<string, string> = {
  PAYMENTS_BANK_ACCOUNT_INVALID: 'Faltan datos de la cuenta bancaria (nombre, banco y número).',
  PAYMENTS_BANK_ACCOUNT_DUPLICATE: 'Esa cuenta bancaria ya está registrada en la empresa.',
  PAYMENTS_BANK_ACCOUNT_NOT_FOUND: 'La cuenta bancaria no existe o está inactiva.',
  PAYMENTS_STATEMENT_NOT_FOUND: 'El extracto no existe en esta empresa.',
  PAYMENTS_STATEMENT_PERIOD_INVALID: 'El período del extracto no es válido (fin antes del inicio).',
  PAYMENTS_STATEMENT_LINES_REQUIRED: 'El extracto necesita al menos una línea.',
  PAYMENTS_STATEMENT_LINE_AMOUNT_INVALID: 'Hay una línea con monto cero: corregila o quitala.',
  PAYMENTS_STATEMENT_LINE_NOT_FOUND: 'La línea del extracto no existe.',
  PAYMENTS_STATEMENT_LINE_ALREADY_MATCHED: 'Esa línea ya está conciliada: deshacé el match primero.',
  PAYMENTS_STATEMENT_NOT_OPEN: 'El extracto ya fue conciliado y es inmutable.',
  PAYMENTS_INTENT_NOT_FOUND: 'El pago elegido no existe o no está capturado.',
  PAYMENTS_INTENT_ALREADY_MATCHED: 'Ese pago ya respalda otra línea de extracto.',
  PAYMENTS_MATCH_AMOUNT_MISMATCH: 'El monto del pago no coincide con el de la línea.',
  PAYMENTS_EXCLUDE_REASON_REQUIRED: 'Hay que escribir la razón para excluir la línea.',
  PAYMENTS_STATEMENT_LINES_PENDING:
    'Quedan líneas sin resolver: conciliá o excluí todas antes de cerrar el extracto.',
  PAYMENTS_STATEMENT_UNBALANCED:
    'El extracto no cuadra: saldo inicial + movimientos no da el saldo final. Revisá las líneas o los saldos.',
};
