import Swal from 'sweetalert2';

// Instancia de SweetAlert2 tematizada con la misma paleta oscura que el resto del
// SPA (slate-900/800, indigo-600 de acción primaria, rose-600 de acción destructiva --
// ver web/frontend/src/components/ui/Button.jsx). Un solo lugar para no repetir estas
// clases en cada página que dispare un confirm/alert.
const themed = Swal.mixin({
  background: '#0f172a', // slate-900
  color: '#e2e8f0', // slate-200
  confirmButtonColor: '#4f46e5', // indigo-600
  cancelButtonColor: '#64748b', // slate-500
  customClass: {
    popup: 'rounded-2xl border border-slate-800',
    title: 'text-slate-100',
    htmlContainer: 'text-slate-400',
  },
  buttonsStyling: true,
});

/** Confirmación estándar antes de una acción destructiva (eliminar, desvincular, etc). */
export function confirmarEliminar({ titulo = '¿Estás seguro?', texto = 'Esta acción no se puede deshacer.', confirmText = 'Sí, eliminar' } = {}) {
  return themed.fire({
    title: titulo,
    text: texto,
    icon: 'warning',
    showCancelButton: true,
    confirmButtonText: confirmText,
    confirmButtonColor: '#e11d48', // rose-600 -- acción destructiva, no el indigo de "primary"
    cancelButtonText: 'Cancelar',
    reverseButtons: true,
  }).then((r) => r.isConfirmed);
}

/** Confirmación genérica (no destructiva) con botones Sí/No. */
export function confirmar({ titulo, texto, icon = 'question', confirmText = 'Sí', cancelText = 'Cancelar' } = {}) {
  return themed.fire({
    title: titulo,
    text: texto,
    icon,
    showCancelButton: true,
    confirmButtonText: confirmText,
    cancelButtonText: cancelText,
    reverseButtons: true,
  }).then((r) => r.isConfirmed);
}

export function exito(titulo, texto = '') {
  return themed.fire({ title: titulo, text: texto, icon: 'success', confirmButtonText: 'OK' });
}

export function error(titulo, texto = '') {
  return themed.fire({ title: titulo, text: texto, icon: 'error', confirmButtonText: 'OK' });
}

/** Toast chico arriba a la derecha, se cierra solo -- para feedback que no necesita bloquear al usuario. */
const toastMixin = themed.mixin({
  toast: true,
  position: 'top-end',
  showConfirmButton: false,
  timer: 3000,
  timerProgressBar: true,
});

export function toastExito(titulo) {
  return toastMixin.fire({ icon: 'success', title: titulo });
}

export function toastError(titulo) {
  return toastMixin.fire({ icon: 'error', title: titulo });
}

export default themed;
