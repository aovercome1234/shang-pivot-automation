# 尚品汇可观测平台（部署在服务器上）

指标 / 日志 / 追踪 / 告警四件套，**平台本体跑在被测服务器（111.170.33.2）上**，
以原生二进制 + systemd 方式装在 `/opt/monitoring/`（服务器连不上 Docker Hub，容器镜像拉不下来）。
本机只做两件事：**开 SSH 隧道看 UI**、**接告警弹桌面通知**。

```
┌─ 服务器 111.170.33.2（systemd，只监听回环）────────────────────────────────┐
│                                                                          │
│  shang-pivot 应用（8086 应用 / 8087 actuator）  projectku 应用（8080）      │
│      │  │                                       │                        │
│      │  └── /actuator/prometheus ──┐            │                        │
│      └──── OTLP 4318 ──► tempo ◄───┼────────────┘                        │
│                                    │                                     │
│  prometheus(9090) ◄────────────────┘   规则 rules/{projectku,shang-pivot}-alerts.yml
│      │  ▲                                │                               │
│      │  └── node_exporter(9100)          ▼                               │
│      │                              alertmanager(9093) ──► alert-notifier(8899)
│      ▼                                                       └─► /opt/monitoring/docs/.../alerts.log
│  grafana(3000) 仪表板：尚品汇性能测试总览 / 元气购性能测试总览                │
│                                                                          │
│  filebeat ──► elasticsearch(9200) ──► kibana(5601)                       │
│    ├ /opt/shang-pivot/current/logs/*.log  → 索引 shang-pivot-logs-*       │
│    └ journald/nginx（元气购）             → 索引 projectku-logs-*         │
└──────────────────────────────────────────────────────────────────────────┘
        ▲ SSH 本地转发（本机 scripts/open-dashboards.sh）
        │
   ┌────┴─ 开发机 ────────────────────────────────────────────┐
   │ 浏览器看 Grafana/Kibana；scripts/alert-watch.sh 弹桌面通知 │
   └──────────────────────────────────────────────────────────┘
```

## 一页纸

```bash
cd observability

# 访问（UI 只监听服务器回环，必须走隧道）
bash ./scripts/open-dashboards.sh --daemon     # 后台建隧道，打印本机地址
bash ./scripts/open-dashboards.sh              # 前台保持（Ctrl-C 断开）

# 运维（全部通过 SSH 操作服务器上的平台）
bash ./scripts/platform.sh status              # 平台服务 + 采集目标
bash ./scripts/platform.sh verify              # 关键指标是否有数据
bash ./scripts/platform.sh alerts              # 规则 / 活跃告警 / 投递记录
bash ./scripts/platform.sh traces              # Tempo 里的 span（含 SQL 跨度）
bash ./scripts/platform.sh logs                # 日志索引 / 管道 / 来源分布

# 压测（在服务器上跑，压 127.0.0.1:8090 内网入口，客户端指标写入服务器 Prometheus）
bash ./scripts/platform.sh k6 preflight.js \
  -e BASE_URL=http://127.0.0.1:8090/api -e ADMIN_BASE_URL=http://127.0.0.1:8091/admin \
  -e PHONE=13800000001 -e ACCOUNT=admin -e PASSWORD=Admin@123
bash ./scripts/platform.sh k6 browse-load.js -e BASE_URL=http://127.0.0.1:8090/api \
  -e PHONE=13800000001 -e STAGES=30s:10,2m:50,3m:100

# 告警桌面通知（每次开机起一次；不起就只有服务器上的文件记录）
bash ./scripts/alert-watch.sh --daemon

# 部署/更新（幂等，可反复执行）
bash ./scripts/deploy-platform-to-server.sh           # 尚品汇的采集任务/规则/仪表板/日志输入
bash ./scripts/deploy-platform-to-server.sh --revert  # 撤掉尚品汇接入项（保留元气购那套）
bash ./scripts/deploy-app.sh                          # 应用侧（actuator 指标 + OTel Agent）发布
```

## 本机入口（经隧道）

| 服务 | 本机地址 | 凭据 |
| --- | --- | --- |
| Grafana | http://localhost:13000 | admin / admin |
| Kibana | http://localhost:15601 | 无（数据视图「尚品汇日志」） |
| Prometheus | http://localhost:19090 | 无 |
| Alertmanager | http://localhost:19093 | 无 |
| Elasticsearch | http://localhost:19200 | 无 |
| Tempo API | http://localhost:13200 | 无 |

仪表板：http://localhost:13000/d/shang-pivot-perf-overview （文件夹「尚品汇可观测」，25 个面板）

### 公网入口（不开隧道也能看，一层认证）

平台经服务器上 projectku 的 nginx 暴露在 60080 的 `/monitor/` 下，**只输一次口令**：

| 入口 | 地址 | 认证 |
| --- | --- | --- |
| Grafana（两个项目仪表板） | http://111.170.33.2:60080/monitor/grafana/ | 只需 nginx basic：`monitor` / `Monitor@2026`（Grafana 侧已配 `[auth.proxy]`，用 nginx 传的 `X-WEBAUTH-USER` 自动登录，不再二次登录） |
| Kibana（日志） | http://111.170.33.2:60080/monitor/kibana/ | 同上（Kibana 本身无认证） |
| Prometheus | http://111.170.33.2:60080/monitor/prometheus/ | 同上 |
| Alertmanager | http://111.170.33.2:60080/monitor/alertmanager/ | 同上 |

- 尚品汇仪表板：http://111.170.33.2:60080/monitor/grafana/d/shang-pivot-perf-overview
- 元气购仪表板：http://111.170.33.2:60080/monitor/grafana/d/projectku-perf-overview
- trace 没有独立公网入口：走 Grafana → Explore → Tempo（TraceQL `{resource.service.name="shang-pivot"}`）

> 单层认证怎么实现的 / 怎么回退：Grafana 侧是 drop-in `grafana.service.d/auth-proxy.conf`，
> nginx 侧是 `snippets/projectku-monitoring.conf` 里一行 `proxy_set_header X-WEBAUTH-USER $remote_user;`
> （备份 `projectku-monitoring.conf.bak-singleauth`）。本机直连 127.0.0.1:3000（隧道）时没有该头，
> 仍走 Grafana 自己的登录页 admin/admin——管理操作请走隧道或直接用 admin 登录。

> 另一路（元气购）留下的 `web-serverbridge-1` 容器也把服务器的 3000/9090/9093/3200/5601
> 转发到了本机同号端口，两套转发互不冲突，任选其一。

## 服务器侧有哪些尚品汇的东西

| 位置 | 内容 | 由谁维护 |
| --- | --- | --- |
| `/opt/monitoring/prometheus/prometheus.yml` | 采集任务 `shang-pivot`（127.0.0.1:8087）、`shang-pivot-host`（127.0.0.1:9100） | `scripts/deploy-platform-to-server.sh`（标记块 `# >>> shang-pivot`） |
| `/opt/monitoring/prometheus/rules/shang-pivot-alerts.yml` | 13 条告警规则（名字统一带「尚品汇-」前缀，避免与元气购同名规则混进同一组通知） | 同上 |
| `/opt/monitoring/grafana/provisioning/dashboards-shang/` | 仪表板 JSON + provider（文件夹「尚品汇可观测」） | 同上 |
| ES 解析管道 `shang-pivot-logs` | 日志解析（app 与 access 两种格式） | 同上 |
| `/opt/monitoring/filebeat/filebeat.yml` | 两个输入：`/opt/shang-pivot/current/logs/shang-pivot{,-access}.log` → 索引 `shang-pivot-logs-*` | 同上（标记块） |
| `/opt/monitoring/alertmanager/alertmanager.yml` | 一条抑制规则（尚品汇服务不可用时压掉它自己的 warning） | 同上（标记块） |
| `/etc/systemd/system/shang-pivot.service.d/otel.conf` | OTel Java Agent：trace → 127.0.0.1:4318，采样率 0.1 | `scripts/deploy-app.sh` |
| `/etc/shang-pivot/shang-pivot.env` | `DB_URL` 追加 `stringtype=unspecified`（jsonb 下单必需） | `scripts/deploy-app.sh` |

回退：`deploy-platform-to-server.sh --revert`、`deploy-app.sh --rollback`。

## 资源占用

平台在服务器上约占 2.5–3 GB 内存；数据落在 `/opt/monitoring/{prometheus,elasticsearch,tempo,...}`。
服务器 16 GB 内存 / 29 GB 磁盘，实测余量充足。开发机不再跑这套平台（原先的 Docker 方案已删除）。

## 出问题时

| 现象 | 查哪里 |
| --- | --- |
| 采集目标 down | `platform.sh status`；应用侧 `systemctl status shang-pivot`、`curl 127.0.0.1:8087/actuator/prometheus` |
| 没有 trace | `platform.sh traces`；服务器 `systemctl status tempo`；应用启动日志搜 opentelemetry |
| 没有日志 | `platform.sh logs`；服务器 `systemctl status filebeat`、`tail /opt/monitoring/filebeat/logs/filebeat` |
| 告警不弹窗 | 本机 `alert-watch.sh` 是否在跑；服务器 `tail /opt/monitoring/docs/performance-test-records/alerts.log` |
| UI 打不开 | 隧道是否在跑：`bash ./scripts/open-dashboards.sh --daemon` |
