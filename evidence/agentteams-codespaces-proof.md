# AgentTeams Codespaces Proof

Date: 2026-09-01

## Runtime

- Codespace: `energymesh-agentteams-min-q7746qqwx77qcv45`
- Machine: `basicLinux32gb` (2 cores, 8 GB RAM, 32 GB storage)
- Official AgentTeams repository: `https://github.com/agentscope-ai/AgentTeams`
- Official AgentTeams commit in Codespace: `223ddc2`
- LLM provider: `openai-compat`
- Model: `deepseek-chat`
- Dashboard: disabled

## Running Containers

```text
agentteams-worker-energy-dispatcher Up higress-registry.cn-hangzhou.cr.aliyuncs.com/agentteams/agentteams-qwenpaw-worker:v1.2.3
agentteams-manager Up higress-registry.cn-hangzhou.cr.aliyuncs.com/agentteams/agentteams-manager-qwenpaw:v1.2.3
agentteams-controller Up higress-registry.cn-hangzhou.cr.aliyuncs.com/agentteams/agentteams-embedded:v1.2.3
```

## AgentTeams Resources

`docker exec agentteams-controller agt get teams`

```text
NAME             PHASE   LEADER             WORKERS  READY
energymesh-demo  Active  energy-dispatcher           0/0
```

`docker exec agentteams-controller agt get workers`

```text
NAME               PHASE    MODEL          TEAM             RUNTIME
energy-dispatcher  Running  deepseek-chat  energymesh-demo  qwenpaw
```

## Completed Real Task Handoff

- Project: `proj-8e9560f8-68e5-4466-8ff0-242136f1722d`
- Team: `energymesh-demo`
- Worker: `energy-dispatcher`
- Worker Matrix ID: `@energy-dispatcher:matrix-local.agentteams.io:18080`
- Team Room: `!Gw8awHaQ0bFSxke5b5:matrix-local.agentteams.io:18080`
- Task Room: `!mIiq0uJWi97IphbM4s:matrix-local.agentteams.io:18080`

Observed lifecycle in the real AgentTeams Matrix event stream:

```text
project created by energymesh-api
energy-dispatcher received Team Room event
qwenpaw agent built with model agentteams-gateway/deepseek-chat
teamharness__projectflow plan_dag
teamharness__roomflow create_task_room
teamharness__taskflow delegate_task
teamharness__taskflow ack_task
write_file result.md
teamharness__taskflow submit_task SUCCESS_WITH_NOTES
teamharness__taskflow check_task effective=true
teamharness__projectflow accept_task_result
teamharness__projectflow complete_project
teamharness__projectflow mark_requester_report_sent
```

## Result Note

The Worker produced and accepted a campus dispatch plan for:

- shifting 120 kWh flexible load from peak to PV window
- discharging 80 kWh battery energy at 18:00
- mapping KPIs to purchased electricity cost reduction, energy waste reduction, and manual dispatch labor reduction

The Worker explicitly reported that no `world_state.json` was attached to that manual project creation. EnergyMesh code now sends right-side CSV/campus state as `world_state` when `/api/runtime/chat` routes dispatch/control requests into the live AgentTeams Team Room.

## UI Access

Forward the Codespace Element Web port before opening the login page:

```bash
gh codespace ports forward 18088:18088 -c energymesh-agentteams-min-q7746qqwx77qcv45
```

Then open:

```text
http://127.0.0.1:18088/#/login
```

Use username `admin`. The password is stored in the Codespace AgentTeams env file and should not be committed.

## Login Verification

The AgentTeams Matrix admin login was verified after resetting the demo password.

```text
new_login_ok True
user_id @admin:matrix-local.agentteams.io:18080
```

The live local port-forward process was started for:

```text
remote 18088 <=> local 18088
remote 18080 <=> local 18080
```
