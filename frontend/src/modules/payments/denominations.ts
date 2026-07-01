import type { Denomination } from 'src/modules/payments/api';

/**
 * Denominaciones de córdoba EN USO para el arqueo de caja — FUENTE ÚNICA (la usan CajaPage y la sala
 * de ventas). Exactamente: billetes C$ 1000/500/200/100/50/20/10 + monedas C$ 5/1/0.50. (Sin 0.25.)
 */
const DENOMINACIONES: ReadonlyArray<{ type: 'BILL' | 'COIN'; value: string }> = [
  { type: 'BILL', value: '1000' },
  { type: 'BILL', value: '500' },
  { type: 'BILL', value: '200' },
  { type: 'BILL', value: '100' },
  { type: 'BILL', value: '50' },
  { type: 'BILL', value: '20' },
  { type: 'BILL', value: '10' },
  { type: 'COIN', value: '5' },
  { type: 'COIN', value: '1' },
  { type: 'COIN', value: '0.50' },
];

/** Nuevo arqueo en blanco (todas las cantidades en 0). */
export function nuevoArqueo(): Denomination[] {
  return DENOMINACIONES.map((d) => ({
    denomination_type: d.type,
    denomination_value: d.value,
    quantity: 0,
  }));
}

/** Total contado = Σ (valor × cantidad). */
export function totalArqueo(denoms: Denomination[]): number {
  return denoms.reduce((acc, d) => acc + Number(d.denomination_value) * (d.quantity || 0), 0);
}
