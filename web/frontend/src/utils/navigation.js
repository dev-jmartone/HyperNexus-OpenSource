/**
 * Utilidades para generación de URLs directas a Teams Chat y vCenter/Horizon Web UI.
 */

/**
 * Genera el enlace directo para iniciar un chat en Microsoft Teams con un usuario.
 * @param {string} usernameOrEmail - Nombre de usuario, UPN o Email.
 * @returns {string} URL del Deep Link de Microsoft Teams.
 */
/**
 * Genera el enlace directo para iniciar un chat en Microsoft Teams con un usuario.
 * Acepta tanto un string (email/username) como un objeto usuario { username, email, usuario_asignado }.
 *
 * REGLA ESTRICTA DE VALIDACIÓN PARA TEAMS:
 * Un destino de Teams es VÁLIDO únicamente si:
 * 1. Posee una dirección de correo válida con '@' y sin espacios (ej: 'user@example.com').
 * 2. O es un sAMAccountName / username puro SIN ESPACIOS (ej: 'jdoe' -> 'jdoe@example.com').
 * 
 * Si el usuario es un Nombre Completo con espacios (ej: 'Arian Maldonado' o 'Adrian Martinez') 
 * y NO posee una dirección de correo válida, NO ES UN DESTINATARIO VÁLIDO PARA TEAMS y retorna null.
 *
 * @param {Object|string} userOrString - Objeto usuario o string.
 * @returns {string|null} URL del Deep Link de Teams o null si no es válido.
 */
export function getTeamsChatUrl(userOrString) {
  if (!userOrString) return null;

  let email = null;
  let username = null;

  if (typeof userOrString === 'object' && userOrString !== null) {
    email = userOrString.email || null;
    username = userOrString.username || userOrString.usuario_asignado || null;
  } else if (typeof userOrString === 'string') {
    if (userOrString.includes('@')) {
      email = userOrString;
    } else {
      username = userOrString;
    }
  }

  // 1. Validar Email si está presente
  if (email && typeof email === 'string') {
    let cleanEmail = email.trim();
    if (cleanEmail.includes('@') && !cleanEmail.includes(' ')) {
      return `https://teams.microsoft.com/l/chat/0/0?users=${encodeURIComponent(cleanEmail)}`;
    }
  }

  // 2. Validar Username si está presente
  if (username && typeof username === 'string') {
    let raw = username.trim();
    if (!raw || raw.toLowerCase() === 'sin asignar' || raw.toLowerCase() === 'sin usuario' || raw === '—') {
      return null;
    }

    if (raw.includes('\\')) {
      raw = raw.split('\\')[1].trim();
    }

    // Si el username mismo ya es un correo electrónico sin espacios
    if (raw.includes('@')) {
      if (!raw.includes(' ')) {
        return `https://teams.microsoft.com/l/chat/0/0?users=${encodeURIComponent(raw)}`;
      }
      return null;
    }

    // Si NO tiene espacios y contiene un formato de samAccountName válido (tipo 'jdoe')
    if (!raw.includes(' ') && /^[a-zA-Z0-9_\.\-]+$/.test(raw)) {
      const defaultDomain = (typeof window !== 'undefined' && window.__TEAMS_DOMAIN__) || 'example.com';
      return `https://teams.microsoft.com/l/chat/0/0?users=${encodeURIComponent(raw + '@' + defaultDomain)}`;
    }
  }

  return null;
}

/**
 * Genera la URL para acceder a la VM en su respectivo vCenter / Horizon.
 * 
 * Si posee MoRef:UUID:
 * https://vcenter-01.corp.local/ui/app/vm;nav=h/urn:vmomi:VirtualMachine:vm-55065:d14fa998-7e75-465c-895e-4e82b1acac19/summary?navigator=tree
 *
 * Si es búsqueda:
 * https://vcenter-02.corp.local/ui/app/search?query=PC_CON04&searchType=simple
 *
 * @param {Object|string} vm - Objeto máquina o nombre de VM.
 * @returns {string} URL completa de vCenter.
 */
export function getVmCenterUrl(vm) {
  if (!vm) return '#';

  const vmName = typeof vm === 'string' ? vm : (vm.nombre || vm.name || '');
  const orig = typeof vm === 'object' && vm ? String(vm.origen || '').toLowerCase() : '';
  let host = typeof vm === 'object' && vm ? (vm.vcenter_host || '') : '';

  const vdiDomain = (typeof window !== 'undefined' && window.__VDI_DOMAIN__) || 'corp.local';
  if (!host) {
    if (orig === 'mz') host = `vcenter-mz.${vdiDomain}`;
    else if (orig === 'su') host = `vcenter-su.${vdiDomain}`;
    else if (orig === 'core') host = `vcenter-core.${vdiDomain}`;
    else host = `vcenter-dt.${vdiDomain}`;
  } else {
    // Si viene solo el subdominio o formato vcenter-mz
    if (!host.includes('.')) {
      if (host.includes('mz')) host = `vcenter-mz.${vdiDomain}`;
      else if (host.includes('su')) host = `vcenter-su.${vdiDomain}`;
      else if (host.includes('core')) host = `vcenter-core.${vdiDomain}`;
      else host = `${host}.${vdiDomain}`;
    }
  }

  // Asegurar protocolo https://
  if (!host.startsWith('http://') && !host.startsWith('https://')) {
    host = `https://${host}`;
  }

  // Si disponemos del identificador MoRef/UUID (external_id)
  const extId = typeof vm === 'object' && vm ? (vm.external_id || vm.vm_id) : null;
  if (extId) {
    return `${host}/ui/app/vm;nav=h/urn:vmomi:VirtualMachine:${extId}/summary?navigator=tree`;
  }

  // Formato de búsqueda simple en vCenter Web UI
  return `${host}/ui/app/search?query=${encodeURIComponent(vmName)}&searchType=simple`;
}
