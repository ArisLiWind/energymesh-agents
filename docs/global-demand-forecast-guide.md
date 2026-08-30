# 全球电力需求预测分析 — 数据模型使用指南

> 对应草案: `docs/global-demand-forecast-schema.json`  
> 类型定义: `docs/global-demand-forecast-types.ts`  
> 版本: 1.0.0-draft | 2026-07-28

---

## 1. 数据模型总览

本方案将数据分为 **四个层次**，各自解耦，便于前端按需消费：

| 层级 | 内容 | 用途 |
|------|------|------|
| `metadata` | 图表元信息 | 页面标题、来源标注、更新时间 |
| `axes` + `series` | 核心折线数据 | 驱动主线图表渲染 |
| `breakdownBySource` / `breakdownByRegion` | 分解维度 | 支撑堆叠图、饼图、区域对比 |
| `keyDrivers` + `interaction` + `visualConfig` | 标注与交互 | 竖向标记线、缩放逻辑、视觉主题 |

---

## 2. 核心设计 — 历史 vs 预测分离

```jsonc
"series": [
  { "id": "historical",    "lineStyle": "solid",  "lineColor": "#bbf451" },  // 实线 — 历史数据
  { "id": "forecast-baseline", "lineStyle": "dashed", "lineColor": "#67d9cf" }, // 虚线 — 基准预测
  { "id": "forecast-ai-surge", "lineStyle": "dashed", "lineColor": "#f2bd5b" }, // 虚线 — AI加速
  { "id": "forecast-green-transition", "lineStyle": "dashed", "lineColor": "#69e66e" } // 虚线 — 绿色转型
]
```

**历史系列规则**:
- `lineStyle: "solid"` — 前端渲染为实线
- `confidence: "confirmed" | "estimated"` — 区分确证值 vs 初步估算
- 2000–2025 共 26 个年度节点

**预测系列规则**:
- `lineStyle: "dashed"` — 前端渲染为虚线
- `dashPattern: [8, 4]` — 8px 线段 + 4px 间隔
- `confidence: "projected" | "speculative"` — 机-器可读置信标记
- 2026–2045 共 20 个年度预测点

**分界线**:
- `visualConfig.splitLine.enabled: true`  
- 图表以 2025 年为界,左侧标"历史数据 (实线)",右侧标"预测数据 (虚线)"

---

## 3. 多情景对比

三条预测曲线支持多情景对比,场景定义:

| 情景 ID | 标签 | 颜色 | 逻辑 |
|---------|------|------|------|
| `forecast-baseline` | 基准预测 (STEPS) | `#67d9cf` 青 | 基于 IEA 既定政策情景,年增速从 3.4% 缓降至 1.3% |
| `forecast-ai-surge` | AI加速情景 | `#f2bd5b` 金 | 考虑数据中心+AI算力爆发,增速高于基准 1–2pp |
| `forecast-green-transition` | 绿色转型情景 | `#69e66e` 绿 | 深度电气化+可再生能源占比突破60% |

前端渲染建议: 基准预测默认可见,另外两条可通过图例 toggle 开关。

---

## 4. 节点点击缩放逻辑

### 交互流程

```
用户点击折线节点
  → 触发 "node:click" 事件
  → 携带 payload: { seriesId, year, valueTWh, confidence, nearbyRange }
  → 前端计算 nearbyRange = [year - 5, year + 5]
  → 调用 zoomToRange() 动画缩放到该范围
  → 同时高亮被点击的节点 + 突出显示该年份的 breakdown 数据
```

### 缩放参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `defaultRange` | 10 年 | 每次放大的默认窗口 |
| `minRange` | 3 年 | 最小缩放窗口 |
| `maxRange` | 45 年 | 最大缩放窗口(全量数据) |
| `snapToYear` | true | 放大边界强制吸附到整年 |
| `animationDurationMs` | 400ms | 缩放动画时长 |

### 鼠标悬停

tooltip 显示: `2027年: 29500 TWh (年增长率: 3.3%)`
并展示 `confidence` 小标签和 `source` 来源。

---

## 5. 按来源分解 (breakdownBySource)

支持以下渲染模式:

- **堆叠面积图**: 展示煤电、天然气、核电、水电、风电、光伏占比随时间的变化趋势
- **100% 堆叠柱状图**: 展示各来源在特定年份(每5年)的比例
- **桑基图**: 展示 2025→2045 能源结构变迁

类别配色方案:
```
煤电 #4a4a4a | 天然气 #8f9a94 | 核电 #ef776f | 水电 #69a2e6
风电 #67d9cf | 光伏 #f2bd5b | 其他可再生 #69e66e | 其他 #b0b8b3
```

---

## 6. 按区域分解 (breakdownByRegion)

支持:

- **分组柱状图**: 7 个区域的年度对比
- **蝴蝶图 (双向条形图)**: 发达国家 vs 新兴经济体对比
- **小多组图 (small multiples)**: 每区域独立小折线图

---

## 7. 关键驱动力标记

`keyDrivers.drivers` 中的事件将在图表中以竖直虚线+顶部标签形式展示。

包括:
- 2000 互联网泡沫
- 2008 全球金融危机
- 2020 新冠疫情
- 2022 ChatGPT 发布 (AI算力起点)
- 2025 AI算力大规模部署
- 2030 全球碳中和目标里程碑
- 2033 数据中心电力占比超10%
- 2045 全球电网互联互通

---

## 8. 数据来源说明

历史数据参考来源:
- **IEA Electricity 2025** — 全球及主要经济体电力消费统计
- **Ember Global Electricity Review** — 可再生能源发电占比数据
- **IEA World Energy Outlook 2025** — STEPS 情景预测

预测模型逻辑:
- 基准线基于 IEA STEPS 情景的年复合增速外推
- AI加速线在基准线基础上叠加数据中心用电弹性系数 (1.3–1.8x)
- 绿色转型线基于电气化率加速假设 (年增量 +0.5pp)

---

## 9. 前端集成建议

推荐图表库: **ECharts** (对中文生态友好,内置缩放/标注/多系列支持)

数据绑定伪代码:

```typescript
// 从 JSON 构造 ECharts option
const option = {
  xAxis: { data: schema.axes.x },
  yAxis: { ...schema.axes.y },
  series: schema.series.map(s => ({
    name: s.label,
    type: 'line',
    data: s.data.map(d => [d.year, d.valueTWh]),
    lineStyle: {
      type: s.lineStyle,           // 'solid' | 'dashed'
      color: s.lineColor,
      width: s.lineWidth
    },
    symbolSize: s.pointRadius,
    // 关键: 虚线 pattern
    ...(s.dashPattern ? { lineStyle: { type: s.dashPattern } } : {})
  }))
};
```

ECharts `dataZoom` 组件可直接映射 `interaction.zoom` 配置。  
节点点击事件通过 `chart.on('click', params => { ... })` 捕获,根据 `params.dataIndex` 查找 `series.data[dataIndex]` 获取完整数据点。

---

## 10. 后续扩展方向

- [ ] API 端点: `GET /api/global-demand-forecast` 返回此 JSON
- [ ] 实时数据刷新: WebSocket 推送每年 IEA 更新后的修订值
- [ ] 对比模式: 用户可在图表中选择任意两年进行差值对比
- [ ] 导出: 支持导出为 PNG / SVG / CSV
- [ ] 移动端适配: 使用 `visualConfig.responsiveness` 断点
