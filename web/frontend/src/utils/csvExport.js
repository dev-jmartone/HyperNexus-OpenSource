// Export a CSV real (descarga de archivo vía Blob), sin librerías. BOM UTF-8 + separador
// ";" -- Excel con configuración regional es-* usa "," como separador decimal, así que
// interpreta "," como separador de lista solo en locale en-*; con ";" abre bien en ambos.

function csvEscape(val) {
  const s = val === null || val === undefined ? '' : String(val);
  return /[";\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function exportToCsv(filename, headers, rows) {
  const lines = [headers.map(csvEscape).join(';')];
  rows.forEach((row) => lines.push(row.map(csvEscape).join(';')));
  const csv = '﻿' + lines.join('\r\n');

  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename.endsWith('.csv') ? filename : `${filename}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function slugify(s) {
  return (s || '')
    .toString()
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '');
}
