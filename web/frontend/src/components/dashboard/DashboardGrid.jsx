import React, { useMemo, useCallback } from 'react';
import GridLayout, { WidthProvider } from 'react-grid-layout';
import 'react-grid-layout/css/styles.css';
import { useDashboardStore, GRID_COLS, ROW_HEIGHT_PX } from '../../store/useDashboardStore';

import { KpiWidget } from '../widgets/KpiWidget';
import { NovedadesWidget } from '../widgets/NovedadesWidget';
import { KpiDesgloseWidget } from '../widgets/KpiDesgloseWidget';
import { KpiConsumoRecursosWidget } from '../widgets/KpiConsumoRecursosWidget';
import { HuerfanasWidget } from '../widgets/HuerfanasWidget';
import { ChartOrigenWidget } from '../widgets/ChartOrigenWidget';
import { WidgetTopESXiHosts } from '../widgets/WidgetTopESXiHosts';
import { WidgetInfraestructura } from '../widgets/WidgetInfraestructura';
import { DiscoCriticoWidget } from '../widgets/DiscoCriticoWidget';
import { PoolsCapacidadWidget } from '../widgets/PoolsCapacidadWidget';
import { SaludAgentesWidget } from '../widgets/SaludAgentesWidget';
import { WritablesHuerfanosWidget } from '../widgets/WritablesHuerfanosWidget';
import { VdisRetenidasWidget } from '../widgets/VdisRetenidasWidget';
import { InfraInternaWidget } from '../widgets/InfraInternaWidget';

const WIDGET_COMPONENTS = {
  kpi_total_vdi:               KpiWidget,
  novedades_eventos:           NovedadesWidget,
  kpi_desglose_servidor_origen: KpiDesgloseWidget,
  top_esxi_hosts:              WidgetTopESXiHosts,
  infraestructura:             WidgetInfraestructura,
  consumo_recursos:            KpiConsumoRecursosWidget,
  vms_huerfanas:               HuerfanasWidget,
  dist_origen:                 ChartOrigenWidget,
  disco_criticos:              DiscoCriticoWidget,
  pools_capacidad:             PoolsCapacidadWidget,
  salud_agentes:               SaludAgentesWidget,
  writables_huerfanos:         WritablesHuerfanosWidget,
  vdis_retenidas:              VdisRetenidasWidget,
  infra_interna:               InfraInternaWidget,
};

// react-grid-layout en vez de @hello-pangea/dnd (2026-09-02): esa libreria esta pensada
// para listas simples (mismo ancho, una fila/columna), no para un grid con anchos
// variables -- el calculo de "donde cae" el item arrastrado se desincronizaba de la
// posicion visual real. react-grid-layout es grid-nativo: drag, resize con mouse desde
// la esquina, y compactType="vertical" reacomoda todo solo para no dejar huecos.
const ReactGridLayout = WidthProvider(GridLayout);

export function DashboardGrid() {
  const { widgets, applyLayout } = useDashboardStore();
  const visibleWidgets = useMemo(() => widgets.filter(w => w.visible), [widgets]);

  const layout = useMemo(() => visibleWidgets.map(w => ({
    i: w.id,
    x: w.x ?? 0,
    y: w.y ?? 0,
    w: Math.min(w.w ?? 1, GRID_COLS),
    h: w.h ?? 4,
    minW: 1,
    minH: 3,
  })), [visibleWidgets]);

  const handleLayoutChange = useCallback((newLayout) => {
    applyLayout(newLayout);
  }, [applyLayout]);

  return (
    <ReactGridLayout
      className="dashboard-grid-layout"
      layout={layout}
      cols={GRID_COLS}
      rowHeight={ROW_HEIGHT_PX}
      margin={[24, 24]}
      containerPadding={[0, 0]}
      onLayoutChange={handleLayoutChange}
      draggableHandle=".widget-drag-handle"
      compactType="vertical"
      preventCollision={false}
      isResizable
      isDraggable
      isBounded
      useCSSTransforms
    >
      {visibleWidgets.map((widget) => {
        const Component = WIDGET_COMPONENTS[widget.id];
        if (!Component) return null;
        return (
          <div key={widget.id} className="overflow-hidden">
            <Component id={widget.id} title={widget.title} />
          </div>
        );
      })}
    </ReactGridLayout>
  );
}
