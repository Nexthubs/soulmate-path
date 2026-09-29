# Soulmate Path — Ubuntu 服务器部署说明（Stage-1 人工测试版）

> **目的：** 把系统部署到外网 Ubuntu 服务器（`https://soulmate.giaogiao.work`）进行**人工全流程测试**。
> **阶段定位：** 本文档是 Stage-1（PayPal **sandbox** + 人工测试）部署。真正的生产 go-live（Stage-2）差异见文末 §12。
> **关联：** SP-1006 smoke runbook（`docs/handoffs/SP-1006.md`）；本部署完成后即可按该 runbook §6 逐项执行 smoke。
> **安全基线：** 密钥只存在服务器上的 `.env`，永不提交；数据库不对公网暴露。

---

## 1. 架构与流量路径

```text
浏览器 / PayPal
      │ https (443, Caddy 自动 TLS)
      ▼
┌────────────────────────── Ubuntu 服务器 ──────────────────────────┐
│ Caddy（边缘反代）                                                 │
│   /api/*        → 127.0.0.1:8000   (FastAPI / uvicorn, systemd)  │
│   /*            → 127.0.0.1:3000   (Next.js 15, systemd)         │
│                                                                  │
│ backend: 读仓库根目录 .env；内含 sketch/report 生成 worker         │
│ frontend: next build 时内联 NEXT_PUBLIC_* 变量                    │
│ postgres: docker compose，仅绑定 127.0.0.1                       │
└──────────────────────────────────────────────────────────────────┘
      │ 出站
      ▼
PayPal sandbox API/Webhook 校验 · 图片网关 (images.aihappy.indevs.in/v1)
· Report 网关 (litellm.giaogiao.work / gemma-4-26b) · Cloudflare R2
```

**为什么 `/api/*` 必须由 Caddy 直达后端：** `frontend/next.config.ts` 的 rewrite 只覆盖 `/api/soulmate/:path*`，**不覆盖 `/api/webhooks/paypal`**。若让 Next 接住全部流量，PayPal 的 webhook 通知会 404，订阅永远不会被确认（PAY-AUTH-01 链路断裂）。

---

## 2. 前置条件

| 项 | 要求 |
|---|---|
| 服务器 | Ubuntu 22.04/24.04，公网 IP，1C2G 起步（生成 worker 与 Next 构建略吃内存，建议 2C4G） |
| 域名 | `soulmate.giaogiao.work` 的 **A 记录指向服务器 IP**。建议在 Cloudflare 把该记录设为 **仅 DNS（灰色云）**，由 Caddy 直接签发 Let's Encrypt 证书 |
| 本地密钥 | 你本地仓库根目录 `.env` 中的 sandbox PayPal 凭证、R2 凭证、两个网关 key（部署时拷贝到服务器） |
| PayPal 开发者后台 | 能登录（用于注册 webhook 和创建 sandbox 买家账号） |

---

## 3. 服务器基础环境

```bash
# 以 root 或 sudo 用户执行
apt update && apt upgrade -y
apt install -y git curl ufw

# 防火墙：只放行 SSH/HTTP/HTTPS；PostgreSQL 端口不放开
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp
ufw enable

# Docker（只用于 PostgreSQL）
curl -fsSL https://get.docker.com | sh

# Node.js 22（Next.js 15 前端）
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt install -y nodejs

# Python 3.12 + venv（Ubuntu 24.04 自带 3.12；22.04 需 deadsnakes）
apt install -y python3.12 python3.12-venv
```

---

## 4. 获取代码

```bash
adduser --disabled-password --gecos "" soulmate || true
su - soulmate
# 换成你的仓库地址或用 scp/rsync 上传
git clone <YOUR_REPO_URL> soulmate
cd soulmate
```

以下命令均假定工作目录为 `/home/soulmate/soulmate`（仓库根）。

---

## 5. PostgreSQL（仅本机可连）

仓库自带的 `docker-compose.yml` 把 5432 映射到了 `0.0.0.0`——**在公网服务器上必须覆盖**：

```bash
# docker-compose.override.yml —— 只绑定回环 + 强密码
cat > docker-compose.override.yml <<'EOF'
services:
  postgres:
    ports: !override
      - "127.0.0.1:5432:5432"
    environment:
      POSTGRES_PASSWORD: "换成强密码_例如_openssl_rand_-hex_16的输出"
EOF

docker compose up -d
docker compose ps        # 确认 healthy
ss -tlnp | grep 5432     # 必须显示 127.0.0.1:5432，而不是 0.0.0.0:5432
```

记住这个密码，第 7 步 `DATABASE_URL` 要用。

---

## 6. 注册 PayPal Sandbox Webhook（关键步骤）

签名验证按 webhook ID 校验，**每个 webhook URL 对应一个新 ID**。dev 环境 tunnel 用的是旧 ID，在这台服务器上必须重新注册：

1. 登录 [developer.paypal.com](https://developer.paypal.com) → **Apps & Credentials → Sandbox** → 打开你现有的 app（client ID 与本地 `.env` 中一致的那个）。
2. **Add Webhook**，URL 填：
   ```text
   https://soulmate.giaogiao.work/api/webhooks/paypal
   ```
3. 勾选事件（DEV-SPEC §9.5 全集）：
   `BILLING.SUBSCRIPTION.CREATED / ACTIVATED / UPDATED / PAYMENT.FAILED / SUSPENDED / CANCELLED / EXPIRED`，以及 `PAYMENT.SALE.COMPLETED / REFUNDED / REVERSED`。
4. 保存后复制 **Webhook ID**（`WH-xxxxx`），第 7 步用。
5. 同页确认 **Sandbox 买家账号** 存在（Account type: Personal），测试时用它付款。

> DNS 生效且 Caddy 启动前 webhook URL 不可达没关系，PayPal 会重试；先把 ID 拿到即可。

---

## 7. 后端 .env（Stage-1 人工测试值）

```bash
cat > .env <<'EOF'
# ============ 应用 ============
ENVIRONMENT=staging
DEBUG=false
APP_BASE_URL=https://soulmate.giaogiao.work
CORS_ALLOW_ORIGINS=["https://soulmate.giaogiao.work"]

# ============ 数据库 ============
DATABASE_URL=postgresql://soulmate:<第5步的密码>@127.0.0.1:5432/soulmate_dev

# ============ 业务参数 ============
SOULMATE_QUIZ_VERSION=soulmate-quiz-v1
# 人工测试用快速解锁（≈11秒出 Sketch）——Stage-2 上线必须改回 12/24！
SOULMATE_SKETCH_UNLOCK_HOURS=0.003
SOULMATE_REPORT_UNLOCK_HOURS=24
SOULMATE_SKETCH_GENERATION_MODE=on_demand
SOULMATE_REPORT_GENERATION_MODE=on_demand

# ============ PayPal（Stage-1 = sandbox + 已决价格） ============
PAYPAL_ENV=sandbox
PAYPAL_CLIENT_ID=<从本地 .env 拷贝 sandbox client id>
PAYPAL_CLIENT_SECRET=<从本地 .env 拷贝 sandbox secret>
PAYPAL_WEBHOOK_ID=<第6步新注册的 WH-xxxx>
PAYPAL_PRODUCT_ID=PROD-8P691118RU8268612
PAYPAL_SOULMATE_INTRO_PLAN_ID=P-4P4826888W778062ENK5V6NA
PAYPAL_SOULMATE_STANDARD_PLAN_ID=P-32R04621GG544483CNK5V6NY

SOULMATE_CURRENCY=USD
SOULMATE_INTRO_PRICE=0.10
SOULMATE_REGULAR_PRICE=29.90
# PAY-02 决议：必须显式设置（代码默认 blocked，漏写会静默拒绝回头用户）
SOULMATE_RESUBSCRIPTION_POLICY=single_intro

# ============ Sketch 图片生成 ============
OPENAI_BASE_URL=https://images.aihappy.indevs.in/v1
OPENAI_API_KEY=<从本地 .env 拷贝>
SOULMATE_IMAGE_MODEL=gpt-image-2

# ============ Report 生成（测试阶段开启；Stage-2 上线默认关闭） ============
SOULMATE_REPORT_PROVIDER=openai_compatible
SOULMATE_REPORT_MODEL=gemma-4-26b
SOULMATE_REPORT_API_BASE_URL=<从本地 .env 拷贝 litellm 网关地址>
SOULMATE_REPORT_API_KEY=<从本地 .env 拷贝>

# ============ 对象存储（R2，测试期与 dev 共用桶） ============
OBJECT_STORAGE_BUCKET=<从本地 .env 拷贝>
OBJECT_STORAGE_REGION=<从本地 .env 拷贝>
OBJECT_STORAGE_ENDPOINT=<从本地 .env 拷贝>
OBJECT_STORAGE_ACCESS_KEY=<从本地 .env 拷贝>
OBJECT_STORAGE_SECRET_KEY=<从本地 .env 拷贝>
# ASSET-ACCESS-01：生产必须留空（一小时预签名 URL）
OBJECT_STORAGE_PUBLIC_URL_PREFIX=

# ============ 密钥（服务器上新生成，勿复用 dev 值） ============
SESSION_SECRET_KEY=<openssl rand -hex 32 的输出>
SUPPORT_API_KEY=<openssl rand -hex 32 的输出，与上一个不同>

# ============ Worker ============
JOB_WORKER_ENABLED=true
JOB_WORKER_CONCURRENCY=4
EOF
chmod 600 .env
```

生成密钥：`openssl rand -hex 32`（执行两次，分别填入两个 KEY）。
说明：`ENVIRONMENT=staging` 不触发生产配置强校验（允许 sandbox PayPal）；`ENVIRONMENT=production` 时启动会 fail-fast 校验全量生产配置（那是 Stage-2 的路径）。

---

## 8. 后端依赖、数据库迁移、Quiz 种子

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt

# 迁移到 head
PYTHONPATH=backend backend/.venv/bin/alembic -c backend/alembic.ini upgrade head

# Quiz 配置种子（soulmate-quiz-v1）
PYTHONPATH=backend backend/.venv/bin/python -m app.quiz.seed
```

启动冒烟（先手动跑一次看日志是否干净）：

```bash
PYTHONPATH=backend backend/.venv/bin/uvicorn app.main:app --app-dir backend \
  --host 127.0.0.1 --port 8000 &
sleep 3
curl -s http://127.0.0.1:8000/api/soulmate/health        # 期望 200
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8000/api/webhooks/paypal
# 期望 400（端点活着且 fail-closed：空 body/无签名被拒）
kill %1
```

---

## 9. 前端构建（先写 env 再 build —— NEXT_PUBLIC_* 是构建期内联的）

```bash
cd frontend
cat > .env.production <<'EOF'
NEXT_PUBLIC_APP_BASE_URL=https://soulmate.giaogiao.work
NEXT_PUBLIC_API_BASE_URL=https://soulmate.giaogiao.work/api/soulmate
NEXT_PUBLIC_PAYPAL_CLIENT_ID=<与后端同一个 sandbox client id>
NEXT_PUBLIC_SOULMATE_CURRENCY=USD
NEXT_PUBLIC_SOULMATE_INTRO_PRICE=0.10
NEXT_PUBLIC_SOULMATE_REGULAR_PRICE=29.90
NEXT_PUBLIC_ACCELERATED_PRICE=3.99
EOF

npm ci
npm run build        # prebuild 会自动同步 canonical quiz 配置
npm run check:prod-config   # 前端生产配置门禁：全部通过才继续
```

**`.env.production` 加载策略（重要）：**

1. **构建期**：`next build` / `next start` 自动加载 `frontend/.env.production`，并把所有 `NEXT_PUBLIC_*` **内联进打包产物**——它们是构建期常量，不是运行时读取。改了值必须重新 `npm run build` 才生效（build 日志的 `- Environments: .env.production` 行即加载确认）。
2. **优先级**（高→低）：shell 环境变量 → `.env.production.local` → `.env.local` → `.env.production` → `.env`。⚠️ `.env.local` **未入库且优先级更高**——如果它被手工拷贝到服务器，会用 localhost 值覆盖你的生产配置。服务器上保持没有这个文件（`ls frontend/.env.local` 确认；正常 git 克隆不会带下来）。
3. **门禁脚本**：`check:prod-config.mjs` 是裸 Node 脚本，Node 不会自动加载 `.env` 文件——已修复为经 `--env-file-if-exists` 按 Next 同款优先级链自行加载（`git pull` 后直接 `npm run check:prod-config` 即可，无需手工 export）。

---

## 10. systemd 常驻服务

> **路径与用户适配：** 下面两个 unit 文件假定仓库在 `/home/soulmate/soulmate`、运行用户 `soulmate`。若实际布局不同（例如 `ubuntu` 用户的 `~/soulmate-path`），把 `User=`、`WorkingDirectory=`、`ExecStart=` 中的绝对路径全部替换成你的真实值后再启用。

```bash
sudo tee /etc/systemd/system/soulmate-backend.service <<'EOF'
[Unit]
Description=Soulmate Path backend (FastAPI)
After=network.target docker.service

[Service]
User=soulmate
WorkingDirectory=/home/soulmate/soulmate
Environment=PYTHONPATH=/home/soulmate/soulmate/backend
ExecStart=/home/soulmate/soulmate/backend/.venv/bin/uvicorn app.main:app \
  --app-dir backend --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/soulmate-frontend.service <<'EOF'
[Unit]
Description=Soulmate Path frontend (Next.js)
After=network.target soulmate-backend.service

[Service]
User=soulmate
WorkingDirectory=/home/soulmate/soulmate/frontend
ExecStart=/usr/bin/npm run start
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now soulmate-backend soulmate-frontend
sudo systemctl status soulmate-backend soulmate-frontend --no-pager | head -20
```

> `--workers 2` 说明：uvicorn 多 worker 时生成 worker 也在每个进程内各起一份，DB 队列的两段式认领（SP-604）保证不重复消费，可放心使用。若遇到异常可先退回单 worker 排查。

---

## 11. Caddy（TLS 终结 + 路由）

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install caddy

sudo tee /etc/caddy/Caddyfile <<'EOF'
soulmate.giaogiao.work {
    encode zstd gzip
    # /api/* 直达后端：覆盖 /api/soulmate/* 与 /api/webhooks/paypal
    handle /api/* {
        reverse_proxy 127.0.0.1:8000
    }
    handle {
        reverse_proxy 127.0.0.1:3000
    }
}
EOF

sudo systemctl reload caddy
curl -s -o /dev/null -w "%{http_code}\n" https://soulmate.giaogiao.work/api/soulmate/health   # 200
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://soulmate.giaogiao.work/api/webhooks/paypal  # 400
curl -s -o /dev/null -w "%{http_code}\n" https://soulmate.giaogiao.work/                       # 200
```

Caddy 首次启动会自动向 Let's Encrypt 签发证书（前提：§2 的 DNS A 记录已生效）。

---

## 12. 人工测试清单（按顺序走）

用**浏览器正常操作**（不要用 curl 模拟前端），每次付款用 sandbox 买家账号：

| # | 场景 | 通过标准 |
|---|---|---|
| 1 | Landing → 完整 Quiz（Q2–Q18，含过场页） → Email | 答案逐题保存；中途刷新可恢复（§23.3 Recovery） |
| 2 | Subscribe 页 | PayPal 按钮加载（sandbox）；披露文案显示今日扣款 $0.10、次月起 $29.90、自动续费、取消方式 |
| 3 | Sandbox 买家批准 → payment-processing | 期间**不出现**任何成功提示（PAY-AUTH-01） |
| 4 | Webhook 到达 → 自动跳 Result | 服务器日志出现验签成功 + ledger 恰好一条；Result 显示状态与 server_time |
| 5 | Webhook 重复投递（PayPal 后台 Resend 同一事件） | 无重复入账、无状态回退（SP-1003 已自动化，人工抽查日志即可） |
| 6 | Sketch（解锁约 11 秒后） | 生成一次 → R2 持久化 → 页面显示；**刷新/换设备重进返回同一张图**（ASSET-01） |
| 7 | Report | 解锁 24h 后触发生成；或临时把 `SOULMATE_REPORT_UNLOCK_HOURS` 调小重启后端再测（**测完改回 24**） |
| 8 | Settings / 取消 | Settings 显示计划与价格；取消对话流（含退款文案）；取消后 paid-through 内已完成工件仍可看 |
| 9 | 回头订阅（PAY-02 抽查） | 同邮箱第二次订阅只能走 standard 计划（无第二次 $0.10） |
| 10 | 未授权路径抽查 | 未登录直接访问 `/soulmate/result` 被重定向；换一个无痕窗口无法看到上一个会话的 Sketch/Report |

日志位置：`journalctl -u soulmate-backend -f`（结构化 JSON，含 `payment_metric` / `generation_metric` 流）。

已知无害现象：首次加载 Subscribe 页偶发 `zoid destroyed all components` 横幅——刷新即消失（SP-1002 已记录的 PayPal SDK quirk）。

---

## 13. Stage-2（真正上线）与 Stage-1 的差异

| 项 | Stage-1（本文档） | Stage-2（生产 go-live） |
|---|---|---|
| `ENVIRONMENT` | `staging` | `production`（启动时全量 fail-fast 校验） |
| PayPal | sandbox + 新配置的 $0.10/$29.90 计划 | 生产凭证 + 在**生产账号**执行 `provision_paypal.py --env production` 取得生产计划 ID；生产 webhook 注册 |
| 解锁时长 | sketch 0.003h（快速测试） | **必须改回 12 / 24**（TIME-01） |
| 报告生成开关 | 开启（便于测试） | 按默认保持关闭，除非 owner 明确下令开启 |
| 密钥 | 新生成 | 可沿用本机生成的；或再次轮换 |
| R2 | 与 dev 共用桶 | 建议独立生产桶 + 独立密钥；`OBJECT_STORAGE_PUBLIC_URL_PREFIX` 仍必须留空 |
| 回滚/禁用 | — | 见 `docs/handoffs/SP-1006.md` §7（各能力独立开关） |

---

## 14. 故障排查速查

| 症状 | 检查 |
|---|---|
| 后端起不来，报 ConfigurationError | `journalctl -u soulmate-backend`；对照第 7 步逐个键检查（生产模式才会强校验全量） |
| 付款后一直 processing | ① webhook 是否打到后端：`journalctl -u soulmate-backend | grep webhook`；② `PAYPAL_WEBHOOK_ID` 是否为第 6 步新 ID（旧 tunnel ID 会验签失败）；③ DNS/443 是否通 |
| Sketch 一直 QUEUED/PROCESSING | worker 是否在跑（`JOB_WORKER_ENABLED=true`）；图片网关 `OPENAI_BASE_URL` 是否可达（注意必须带 `/v1`）；看 `generation_metric` 日志 |
| Sketch 图挂了但状态 COMPLETED | R2 凭证/endpoint；`OBJECT_STORAGE_PUBLIC_URL_PREFIX` 必须为空（走预签名） |
| 前端 API 全 404/405 | Caddy 是否把 `/api/*` 给了后端而不是 Next；`NEXT_PUBLIC_API_BASE_URL` 是否含 `/api/soulmate` 路径且**重新 build 过** |
| `check:prod-config` 全部报缺失 | 你在跑修复前的旧脚本或未 `git pull`；确认 `package.json` 的 `check:prod-config` 带 `--env-file-if-exists` 参数链。另检查服务器上是否存在会被更高优先级加载的 `frontend/.env.local`（有则删除后重新 build） |
| 改了 .env 不生效 | `sudo systemctl restart soulmate-backend soulmate-frontend`；前端变量是构建期内联，改完必须 `npm run build` 再重启 |
