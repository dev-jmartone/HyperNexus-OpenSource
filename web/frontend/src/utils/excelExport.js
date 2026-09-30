// Export a Excel real (.xlsx, multi-hoja) para la Granja: una hoja por recurso
// (Aplicación o Pool RDS) con el detalle de usuarios/grupos autorizados, más una hoja
// "Resumen" con estadísticas agregadas. exceljs se importa dinámicamente (~1MB) para no
// engordar el bundle principal -- solo se carga cuando alguien clickea "Exportar".
import { estadoDirectorioLabel, estadoDirectorioCategoria } from './directorioEstado';

const HEADER_FILL = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF1E293B' } }; // slate-800
const HEADER_FONT = { bold: true, color: { argb: 'FFE2E8F0' } }; // slate-200
const TITLE_FONT = { bold: true, size: 13, color: { argb: 'FFF1F5F9' } };
const SECTION_FONT = { bold: true, size: 11, color: { argb: 'FF818CF8' } }; // indigo-400

function sanitizeSheetName(name) {
  let s = (name || 'Hoja').toString().replace(/[:\\/?*[\]]/g, ' ').trim();
  if (!s) s = 'Hoja';
  return s.length > 31 ? s.slice(0, 31) : s;
}

function uniqueSheetName(base, used) {
  let name = sanitizeSheetName(base);
  let n = 2;
  while (used.has(name.toLowerCase())) {
    const suffix = ` (${n})`;
    name = sanitizeSheetName(base).slice(0, 31 - suffix.length) + suffix;
    n += 1;
  }
  used.add(name.toLowerCase());
  return name;
}

function normalizado(usuario) {
  return (usuario || '').trim().toLowerCase();
}

/**
 * recursos: [{ nombre, tipoRecurso: 'Aplicación'|'Pool RDS', farm, entries: [
 *   { usuario_o_grupo, es_grupo, tipo_entitlement: 'Local'|'Global', directorio }
 * ] }]
 */
export async function exportRecursosExcel({ filenameBase, titulo, subtitulo, recursos }) {
  const { default: ExcelJS } = await import('exceljs');
  const wb = new ExcelJS.Workbook();
  wb.creator = 'inventario-vdi';
  wb.created = new Date();

  // ---------- Estadísticas ----------
  const usuariosUnicos = new Set();
  const gruposUnicos = new Set();
  const categoriaPorUsuario = new Map(); // usuario normalizado -> categoría (para el desglose de AD)
  let totalFilas = 0;

  const porRecurso = recursos.map((r) => {
    const usuariosDelRecurso = new Set();
    let locales = 0;
    let globales = 0;
    r.entries.forEach((e) => {
      totalFilas += 1;
      if (e.tipo_entitlement === 'Global') globales += 1; else locales += 1;
      const key = normalizado(e.usuario_o_grupo);
      usuariosDelRecurso.add(key);
      if (e.es_grupo) {
        gruposUnicos.add(key);
      } else {
        usuariosUnicos.add(key);
        if (!categoriaPorUsuario.has(key)) categoriaPorUsuario.set(key, estadoDirectorioCategoria(e));
      }
    });
    return {
      nombre: r.nombre, tipoRecurso: r.tipoRecurso, farm: r.farm,
      locales, globales, total: r.entries.length, usuariosUnicos: usuariosDelRecurso.size,
    };
  }).sort((a, b) => b.total - a.total);

  const categorias = { 'Activo en AD': 0, 'Inactivo en AD': 0, 'No encontrado en Directorio': 0 };
  categoriaPorUsuario.forEach((cat) => { if (categorias[cat] !== undefined) categorias[cat] += 1; });

  const topRecurso = porRecurso[0];

  // ---------- Hoja Resumen ----------
  const resumen = wb.addWorksheet('Resumen', { views: [{ state: 'frozen', ySplit: 0 }] });
  resumen.columns = [{ width: 34 }, { width: 20 }, { width: 20 }, { width: 20 }, { width: 20 }];

  const addTitle = (text) => { const row = resumen.addRow([text]); row.getCell(1).font = TITLE_FONT; };
  const addSection = (text) => { resumen.addRow([]); const row = resumen.addRow([text]); row.getCell(1).font = SECTION_FONT; };
  const addHeaderRow = (cells) => {
    const row = resumen.addRow(cells);
    row.eachCell((cell) => { cell.font = HEADER_FONT; cell.fill = HEADER_FILL; });
    return row;
  };
  const addKv = (label, value) => { const row = resumen.addRow([label, value]); row.getCell(1).font = { color: { argb: 'FF94A3B8' } }; row.getCell(2).font = { bold: true }; };

  addTitle(titulo || 'Granja RDS & Aplicaciones — Resumen de autorizaciones');
  if (subtitulo) { const r = resumen.addRow([subtitulo]); r.getCell(1).font = { color: { argb: 'FF64748B' }, italic: true }; }
  resumen.addRow([`Generado el ${new Date().toLocaleString('es-UY')}`]).getCell(1).font = { color: { argb: 'FF64748B' }, size: 9, italic: true };

  addSection('Totales');
  addKv('Recursos exportados (apps + pools)', recursos.length);
  addKv('Aplicaciones', recursos.filter((r) => r.tipoRecurso === 'Aplicación').length);
  addKv('Pools RDS', recursos.filter((r) => r.tipoRecurso === 'Pool RDS').length);
  addKv('Filas de autorización (con posibles repetidos entre recursos)', totalFilas);
  addKv('Usuarios reales únicos (sin duplicados)', usuariosUnicos.size);
  addKv('Grupos AD únicos', gruposUnicos.size);
  if (topRecurso) addKv('Recurso con más autorizados', `${topRecurso.nombre} (${topRecurso.total})`);

  addSection('Estado en Directorio (sobre usuarios únicos, no grupos)');
  addKv('Activos en AD', categorias['Activo en AD']);
  addKv('Inactivos en AD', categorias['Inactivo en AD']);
  addKv('No encontrados en Directorio', categorias['No encontrado en Directorio']);

  addSection('Autorizaciones por recurso');
  addHeaderRow(['Recurso', 'Tipo', 'Farm', 'Locales', 'Globales', 'Total', 'Usuarios únicos']);
  porRecurso.forEach((r) => resumen.addRow([r.nombre, r.tipoRecurso, r.farm, r.locales, r.globales, r.total, r.usuariosUnicos]));

  // ---------- Una hoja por recurso ----------
  const used = new Set(['resumen']);
  recursos.forEach((r) => {
    const ws = wb.addWorksheet(uniqueSheetName(r.nombre, used), { views: [{ state: 'frozen', ySplit: 1 }] });
    ws.columns = [
      { header: 'Usuario / Grupo', key: 'usuario', width: 34 },
      { header: 'Tipo', key: 'tipo', width: 12 },
      { header: 'Es Grupo AD', key: 'esGrupo', width: 14 },
      { header: 'Estado Directorio', key: 'estado', width: 30 },
    ];
    const header = ws.getRow(1);
    header.eachCell((cell) => { cell.font = HEADER_FONT; cell.fill = HEADER_FILL; });
    r.entries
      .slice()
      .sort((a, b) => a.tipo_entitlement.localeCompare(b.tipo_entitlement) || (a.usuario_o_grupo || '').localeCompare(b.usuario_o_grupo || ''))
      .forEach((e) => ws.addRow({
        usuario: e.usuario_o_grupo,
        tipo: e.tipo_entitlement,
        esGrupo: e.es_grupo ? 'Sí' : 'No',
        estado: estadoDirectorioLabel(e),
      }));
  });

  const buf = await wb.xlsx.writeBuffer();
  const blob = new Blob([buf], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filenameBase.endsWith('.xlsx') ? filenameBase : `${filenameBase}.xlsx`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
