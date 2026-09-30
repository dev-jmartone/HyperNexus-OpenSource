import { describe, it, expect } from 'vitest';
import { getTeamsChatUrl, getVmCenterUrl } from '../navigation';

describe('getTeamsChatUrl', () => {
  it('null/undefined -> null', () => {
    expect(getTeamsChatUrl(null)).toBeNull();
    expect(getTeamsChatUrl(undefined)).toBeNull();
  });

  it('email válido como string -> URL de Teams', () => {
    expect(getTeamsChatUrl('user@example.com')).toBe(
      'https://teams.microsoft.com/l/chat/0/0?users=user%40example.com'
    );
  });

  it('username tipo samAccountName sin espacios -> arma email con dominio default', () => {
    expect(getTeamsChatUrl('jdoe')).toBe(
      'https://teams.microsoft.com/l/chat/0/0?users=jdoe%40example.com'
    );
  });

  it('username con formato DOMINIO\\usuario -> toma solo la parte de usuario', () => {
    expect(getTeamsChatUrl('CORP\\jdoe')).toBe(
      'https://teams.microsoft.com/l/chat/0/0?users=jdoe%40example.com'
    );
  });

  it('nombre completo con espacios y sin email -> null (no es destino válido)', () => {
    expect(getTeamsChatUrl('John Doe')).toBeNull();
  });

  it('"Sin asignar" / "Sin usuario" / "—" -> null', () => {
    expect(getTeamsChatUrl('Sin asignar')).toBeNull();
    expect(getTeamsChatUrl('Sin usuario')).toBeNull();
    expect(getTeamsChatUrl('—')).toBeNull();
  });

  it('objeto con email preferido sobre username', () => {
    const url = getTeamsChatUrl({ email: 'x@example.com', username: 'yusername' });
    expect(url).toContain('x%40example.com');
  });

  it('objeto sin email, con usuario_asignado válido', () => {
    const url = getTeamsChatUrl({ usuario_asignado: 'jdoe' });
    expect(url).toContain('jdoe%40example.com');
  });

  it('email con espacios es inválido -> null', () => {
    expect(getTeamsChatUrl('nombre raro@dominio.com')).toBeNull();
  });
});

describe('getVmCenterUrl', () => {
  it('sin vm -> "#"', () => {
    expect(getVmCenterUrl(null)).toBe('#');
  });

  it('con external_id arma URL de detalle VM', () => {
    const url = getVmCenterUrl({ nombre: 'VDI-GRAL-032', external_id: 'vm-55065', vcenter_host: 'vcenter-dt.corp.local' });
    expect(url).toBe(
      'https://vcenter-dt.corp.local/ui/app/vm;nav=h/urn:vmomi:VirtualMachine:vm-55065/summary?navigator=tree'
    );
  });

  it('sin external_id arma URL de búsqueda simple', () => {
    const url = getVmCenterUrl({ nombre: 'VDI-GRAL-032', vcenter_host: 'vcenter-dt.corp.local' });
    expect(url).toBe('https://vcenter-dt.corp.local/ui/app/search?query=VDI-GRAL-032&searchType=simple');
  });

  it('sin vcenter_host, infiere host por origen mz', () => {
    const url = getVmCenterUrl({ nombre: 'X', origen: 'mz' });
    expect(url).toContain('vcenter-mz.corp.local');
  });

  it('sin vcenter_host y sin origen conocido, usa default DT', () => {
    const url = getVmCenterUrl({ nombre: 'X' });
    expect(url).toContain('vcenter-dt.corp.local');
  });

  it('string simple (solo nombre) arma búsqueda con host default', () => {
    const url = getVmCenterUrl('PC_ADMIN');
    expect(url).toBe('https://vcenter-dt.corp.local/ui/app/search?query=PC_ADMIN&searchType=simple');
  });
});
