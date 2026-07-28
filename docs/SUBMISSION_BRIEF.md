# 初赛作品简介草案

项目名称：EnergyMesh Agents：园区、工业中心和算力中心的多智能体电力网络自主调度系统

EnergyMesh Agents 面向园区、工业中心和算力中心，解决传统 EMS 难以在负荷、电价、天气、设备状态和生产计划同时变化时自主重定义调度任务的问题。系统连接 EMS、SCADA、光伏、储能和用电设备的数据抽象层，通过感知、调度、审核、执行与验证 Agent，持续生成并调整电力运行策略，在满足安全与生产约束的前提下降低峰值功率与用电成本。

系统使用开源 `agentscope-ai/AgentTeams` 的 Manager-Workers 协作框架设计 Team Leader、感知 Agent、调度 Agent、审核 Agent、执行 Agent，完成从外部数据快照、运行上下文核验、原 EMS 策略回放、新策略生成、安全与收益双重审核、人工审批、结构化模拟执行到结果持续确认的闭环。当前版本提供 `agentteams/agentteams-resources.yaml`、Worker 包资产、Skill 包和 `/api/agentteams/manifest`，本地 FastAPI 服务作为能源业务工具/API 层保证无云账号也可复现 Demo。

项目创新点在于不让大模型直接控制电力设备，而是采用「AgentTeams 编排 + 外部数据模拟 + 优化求解 + 确定性审计 + 人工审批 + 证据封存」的混合架构，把能源调度需求转化为可解释、可验证、可回滚的调度方案。核心 Skill 包括 `microgrid_context_ingest`、`dispatch_plan_generate`、`dispatch_audit_verify`、`execution_mapping`、`approval_rollback`，可复用于不同园区、不同储能配置和不同业务目标。

Demo 聚焦「光伏出力下降、变压器热态降额、峰值电价临近、生产计划不可中断」场景，展示系统如何读取模拟 EMS/BMS/PCS/气象/MES 外部数据，生成多套策略，拦截不安全方案，请求人工审批，模拟执行并输出 Trace、Metrics 和 SHA-256 证据包。MCP、RAG、可观测和阿里云官方用云 Skills 的集成方案已作为等价工具契约和迁移计划沉淀在 `docs/` 中，便于后续接入 Nacos、Higress、PolarDB for PostgreSQL、RocketMQ 和 AgentLoop/LoongSuite。
