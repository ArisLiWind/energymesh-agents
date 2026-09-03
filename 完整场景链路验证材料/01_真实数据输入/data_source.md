# 数据来源说明

本证据包使用 EnergyMesh 主仓中已经存在的数据与运行归档。

## EMSx site 8

- 原始元数据：`data/emsx/raw/metadata.csv`
- 处理后输入：`data/emsx/processed/emsx_site8_core_upload.csv`
- 本包副本：
  - `emsx_metadata.csv`
  - `emsx_site8_core_upload.csv`

字段包括：

- `timestamp`
- `site_id`
- `actual_consumption`
- `actual_pv`
- `load_00`
- `pv_00`
- `battery_capacity_kwh`
- `battery_power_kwh_per_interval`
- `charge_efficiency`
- `discharge_efficiency`
- `battery_soc`

## OpenCEM

- 原始公开数据副本：`data/opencem/2025-07-a.csv`
- 来源说明副本：`opencem_data_source.md`
- 原 README 中记录的 SHA-256：`9094f34779cc58046eab3a3ab0bb6a355db5ec0e0fccc254dfae762d0855f907`

EnergyMesh 使用 OpenCEM 作为公开微电网测量数据回放证据。电价与受保护负荷策略属于 EnergyMesh 回放配置，不伪装为 OpenCEM 原始测量项。

## 与本次链路的关系

`TASK-20260731-014.full_evidence_archive.json` 记录了一次完整运行归档。本包将其中的任务、事件、快照、AgentTeams handoff、Skill 调用、方案、审批、执行、回读和回滚拆分为可核验文件。

本次执行明确声明：

- `simulation_mode=true`
- `allow_production_write=false`
- `real_devices_contacted=0`

因此本材料证明的是“真实/公开数据回放 + EnergyMesh 完整闭环 + 数字孪生执行验证”，不是实体 PCS/BMS 的生产写入证明。
