/**
 * EnergyMesh 全球电力需求预测分析 — TypeScript 类型定义草案
 * 对应文件: docs/global-demand-forecast-schema.json
 * 用于指导前端 (ECharts / D3 / Observable Plot) 的数据绑定
 */

// ---- 数据点 ----

/** 单一数据点的置信度 */
export type ConfidenceLevel = "confirmed" | "estimated" | "projected" | "speculative";

/** 折线图上的单个数据点 */
export interface ForecastDataPoint {
  year: number;
  valueTWh: number;
  confidence: ConfidenceLevel;
  /** 年增长率 (0.034 表示 3.4%)，在 tooltip 中展示 */
  growthRate?: number;
  /** 数据来源标签 */
  source?: string;
  /** 关键事件的文本标注 */
  annotation?: string;
}

// ---- 系列 ----

export type LineStyle = "solid" | "dashed" | "dotted";

export interface SeriesDefinition {
  id: string;
  label: string;
  description: string;
  lineStyle: LineStyle;
  lineWidth: number;
  lineColor: string;
  /** 虚线间隔模式 [线段长度, 间隔长度] 仅在 lineStyle === "dashed" 时生效 */
  dashPattern?: [number, number];
  pointRadius: number;
  pointColor: string;
  pointHoverRadius: number;
  /** 是否在折线下方渲染半透明填充区域 */
  areaFill: boolean;
  areaFillColor?: string;
  data: ForecastDataPoint[];
}

// ---- 轴 ----

export interface AxisDefinition {
  field: string;
  label: string;
  type: "linear" | "time";
  domain: [number, number];
  tickInterval: number;
  gridLineStyle: LineStyle;
  gridLineColor: string;
  formatPrefix?: string;
}

// ---- 按来源/区域分解 ----

export interface BreakdownCategory {
  id: string;
  label: string;
  color: string;
}

export interface SourceBreakdownPoint {
  year: number;
  totalTWh: number;
  breakdown: Record<string, number>;
}

export interface RegionBreakdownPoint {
  year: number;
  totalTWh: number;
  breakdown: Record<string, number>;
}

// ---- 关键事件/驱动力 ----

export interface KeyDriver {
  year: number;
  label: string;
  /** event | policy | technology | milestone */
  type: "event" | "policy" | "technology" | "milestone";
  impact: "positive" | "negative" | "neutral";
}

// ---- 交互配置 ----

export interface ZoomConfig {
  enabled: boolean;
  /** node-click: 点击节点触发; brush: 框选放大 */
  mode: "node-click" | "brush";
  description: string;
  /** 默认放大窗口的年数范围 */
  defaultRange: number;
  minRange: number;
  maxRange: number;
  /** 放大后是否吸附到整年 */
  snapToYear: boolean;
  animationDurationMs: number;
}

export interface TooltipConfig {
  enabled: boolean;
  template: string;
  showConfidence: boolean;
  showSource: boolean;
}

export interface NodeClickPayload {
  seriesId: string;
  year: number;
  valueTWh: number;
  confidence: ConfidenceLevel;
  /** 建议的放大展示范围 [startYear, endYear] */
  nearbyRange: [number, number];
}

// ---- 响应式配置 ----

export interface ResponsiveBreakpoint {
  minWidth: number;
  fontSize: number;
  pointRadius: number;
}

// ---- 视觉 / 前端集成 ----

export interface VisualConfig {
  chartType: "multiSeriesLine";
  foregroundColor: string;
  backgroundColor: string;
  panelBackground: string;
  fontFamily: string;
  splitLine: {
    enabled: boolean;
    historicalAfter: number;
    splitLabelLeft: string;
    splitLabelRight: string;
  };
  responsiveness: {
    breakpoints: {
      desktop: ResponsiveBreakpoint;
      tablet: ResponsiveBreakpoint;
      mobile: ResponsiveBreakpoint;
    };
  };
}

export interface FrontendIntegration {
  dataBinding: {
    seriesField: string;
    xField: string;
    yField: string;
    lineStyleField: string;
    lineColorField: string;
    dashPatternField: string;
  };
  nodeClickHandler: {
    eventName: string;
    payload: NodeClickPayload;
    action: string;
  };
  renderLibrary: "agnostic";
  suggestedLibraries: string[];
}

// ---- 顶层模型 ----

export interface GlobalDemandForecast {
  metadata: {
    chartId: string;
    title: string;
    subtitle: string;
    unit: string;
    dataSource: string;
    lastUpdated: string;
    timezone: string;
    locale: string;
  };
  axes: {
    x: AxisDefinition;
    y: AxisDefinition;
  };
  series: SeriesDefinition[];
  breakdownBySource: {
    description: string;
    categories: BreakdownCategory[];
    data: SourceBreakdownPoint[];
  };
  breakdownByRegion: {
    description: string;
    regions: BreakdownCategory[];
    data: RegionBreakdownPoint[];
  };
  keyDrivers: {
    description: string;
    drivers: KeyDriver[];
  };
  interaction: {
    zoom: ZoomConfig;
    tooltip: TooltipConfig;
    legend: {
      position: string;
      interactive: boolean;
      toggleSeries: boolean;
    };
    annotations: {
      showKeyDrivers: boolean;
      driverMarkerStyle: string;
      driverLabelPosition: string;
    };
  };
  visualConfig: VisualConfig;
  frontendIntegration: FrontendIntegration;
}