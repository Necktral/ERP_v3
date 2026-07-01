/**
 * Generador de código de barras Code 128B en SVG puro (sin dependencias).
 *
 * Suficiente para etiquetas de góndola/artículo escaneables con cualquier lector
 * (los mismos que usa la Caja de Venta). Subconjunto B: ASCII imprimible 32–126.
 */

// Tabla estándar Code 128: anchos de módulos (barra,espacio,...) por valor 0–106.
const PATTERNS = [
  '212222', '222122', '222221', '121223', '121322', '131222', '122213', '122312',
  '132212', '221213', '221312', '231212', '112232', '122132', '122231', '113222',
  '123122', '123221', '223211', '221132', '221231', '213212', '223112', '312131',
  '311222', '321122', '321221', '312212', '322112', '322211', '212123', '212321',
  '232121', '111323', '131123', '131321', '112313', '132113', '132311', '211313',
  '231113', '231311', '112133', '112331', '132131', '113123', '113321', '133121',
  '313121', '211331', '231131', '213113', '213311', '213131', '311123', '311321',
  '331121', '312113', '312311', '332111', '314111', '221411', '431111', '111224',
  '111422', '121124', '121421', '141122', '141221', '112214', '112412', '122114',
  '122411', '142112', '142211', '241211', '221114', '413111', '241112', '134111',
  '111242', '121142', '121241', '114212', '124112', '124211', '411212', '421112',
  '421211', '212141', '214121', '412121', '111143', '111341', '131141', '114113',
  '114311', '411113', '411311', '113141', '114131', '311141', '411131', '211412',
  '211214', '211232', '2331112',
];

const START_B = 104;
const STOP = 106;

/**
 * SVG de un Code 128B para `text` (ASCII imprimible). Devuelve '' si no es
 * codificable. `height` en px del dibujo; el ancho sale del contenido.
 */
export function code128Svg(text: string, opts: { height?: number; moduleWidth?: number } = {}): string {
  const clean = (text ?? '').trim();
  if (!clean || [...clean].some((ch) => ch.charCodeAt(0) < 32 || ch.charCodeAt(0) > 126)) {
    return '';
  }
  const height = opts.height ?? 48;
  const mw = opts.moduleWidth ?? 2;

  const values = [START_B, ...[...clean].map((ch) => ch.charCodeAt(0) - 32)];
  let checksum = values[0] as number;
  for (let i = 1; i < values.length; i++) checksum += (values[i] as number) * i;
  values.push(checksum % 103, STOP);

  // Quiet zone de 10 módulos a cada lado (requisito del estándar para escanear).
  let x = 10 * mw;
  const rects: string[] = [];
  for (const v of values) {
    const pattern = PATTERNS[v];
    if (!pattern) return '';
    let bar = true;
    for (const d of pattern) {
      const w = Number(d) * mw;
      if (bar) rects.push(`<rect x="${x}" y="0" width="${w}" height="${height}" fill="#000"/>`);
      x += w;
      bar = !bar;
    }
  }
  const total = x + 10 * mw;
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${total}" height="${height}" ` +
    `viewBox="0 0 ${total} ${height}" shape-rendering="crispEdges">` +
    `<rect width="${total}" height="${height}" fill="#fff"/>${rects.join('')}</svg>`
  );
}
