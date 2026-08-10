# 口语停顿回溯标注工具

英语口语任务结束后，把「完整对话转录 + EasyTurn 停顿/话轮标记」呈现给被试；被试在每个标记处填写：

1. **原因类别**（必选）
2. **原因与心理过程**（开放描述）
3. **置信度 1–7**（点选）

全部填完后提交。新会话需由主试先确认每句话的说话人，再生成被试链接；主试还可在后台查看进度、导出数据、修改指导语与账号。

---

## 目录

1. [系统能做什么](#1-系统能做什么)
2. [环境要求](#2-环境要求)
3. [安装（Linux / 服务器）](#3-安装linux--服务器)
4. [安装（Windows）](#4-安装windows)
5. [配置 `.env`](#5-配置-env)
6. [启动服务](#6-启动服务)（含 [停止服务 / Ctrl+C 无效](#61-停止服务)）
7. [如何打开主试端](#7-如何打开主试端)
8. [主试端常用操作](#8-主试端常用操作)
9. [如何打开被试端](#9-如何打开被试端)
10. [被试如何填写与提交](#10-被试如何填写与提交)
11. [流水线如何创建会话](#11-流水线如何创建会话)
12. [局域网 / 公网部署说明](#12-局域网--公网部署说明)（含 [GitHub + Render 免费公网部署](#125-github--render-免费公网部署推荐)）
13. [换机迁移](#13-换机迁移)
14. [备份与恢复](#14-备份与恢复)
15. [常见问题](#15-常见问题)
16. [目录结构](#16-目录结构)
17. [验收清单](#17-验收清单)

---

## 1. 系统能做什么

| 角色 | 能做什么 |
|------|----------|
| **流水线**（VAD / ASR / EasyTurn） | 任务结束后 `POST` 创建待确认说话人的会话 |
| **主试** | 登录后台、确认主试话语、生成并复制被试链接、看进度、导出 CSV/JSON、重置/删除会话、改指导语与类别（管理员）、管理账号（管理员） |
| **被试** | 用私密链接打开填写页，无需登录；自动暂存；全部填完后提交 |

**当前范围：** 每句话可以包含多个 pause 标注点；仅 `≥0.5s` 的停顿会作为 pause 并对应独立标注表单，较短停顿会被忽略。暂不包含音频回放、自动发邮件/微信。

主试确认说话人后，若某条被试话语紧接主试话轮，仅移除该被试话语的最后一个 pause；同一句更早的 pause 仍保留并继续标注。

---

## 2. 环境要求

- **Python ≥ 3.11**（推荐 3.11–3.13）
- 可访问本机/服务器的网络
- **线上被试**需要服务对被试网络**可达**（局域网同 WiFi，或公网 IP/域名）
- 建议端口：**8000**（可在 `.env` 修改）

检查 Python：

```bash
python --version
# 或
python3 --version
```

---

## 3. 安装（Linux / 服务器）

```bash
# 1. 进入项目目录
cd 停顿标注工具

# 2. 一键安装（创建虚拟环境 + 装依赖 + 生成 .env）
bash scripts/install.sh

# 3. 编辑配置（见第 5 节）
nano .env   # 或 vim / 任意编辑器

# 4. 启动
bash scripts/run.sh
```

安装脚本会：

- 创建 `.venv` 虚拟环境
- `pip install -r requirements.txt`
- 若没有 `.env`，从 `.env.example` 复制一份

---

## 4. 安装（Windows）

在 **PowerShell** 或 **Git Bash** 中：

```powershell
cd 停顿标注工具

# 创建虚拟环境
python -m venv .venv

# 激活
.\.venv\Scripts\Activate.ps1
# 若报执行策略错误，可先：
# Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

# 安装依赖
pip install -r requirements.txt

# 生成配置文件
copy .env.example .env

# 用记事本或 VS Code 编辑 .env（见第 5 节）
notepad .env
```

启动：

```powershell
.\.venv\Scripts\Activate.ps1
mkdir data -ErrorAction SilentlyContinue
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

也可用 Git Bash：

```bash
bash scripts/run.sh
```

---

## 5. 配置 `.env`

项目根目录的 `.env` 示例：

```text
HOST=0.0.0.0
PORT=8000
PUBLIC_BASE_URL=http://192.168.1.150:8000
PIPELINE_TOKEN=change-me-to-a-random-secret
SECRET_KEY=change-me-to-another-random-secret
DATABASE_PATH=./data/app.db
```

### 字段说明

| 变量 | 含义 | 怎么填 |
|------|------|--------|
| `HOST` | 监听地址 | 固定 `0.0.0.0`（允许局域网/公网访问） |
| `PORT` | 端口 | 默认 `8000` |
| `PUBLIC_BASE_URL` | **生成被试/主试链接时用的对外地址** | 见下表 |
| `PIPELINE_TOKEN` | 流水线调用 API 的密钥 | 改成随机长字符串 |
| `SECRET_KEY` | 主试登录 session 密钥 | 改成另一串随机字符串 |
| `DATABASE_PATH` | SQLite 路径 | 一般保持 `./data/app.db` |

### `PUBLIC_BASE_URL` 怎么填

| 场景 | 示例 |
|------|------|
| 只在本机测 | `http://127.0.0.1:8000` |
| 同一 WiFi 的手机/电脑 | `http://192.168.x.x:8000`（本机局域网 IP） |
| 公网固定 IP | `http://47.xx.xx.xx:8000` |
| 有域名 | `http://pause.example.com:8000` 或以后上 HTTPS 后的 `https://...` |

**注意：**

- 不要末尾多写 `/`
- 改完 `.env` 后**必须重启服务**，新创建的会话才会用新地址
- 网络变了（换 WiFi、换 IP）→ 改这里 → 重启 → 主试端重新复制链接

查看本机局域网 IP：

- Windows：`ipconfig`，看「无线局域网」或 WLAN 的 IPv4
- Linux：`ip a` 或 `hostname -I`

---

## 6. 启动服务

### Linux

```bash
cd 停顿标注工具
bash scripts/run.sh
```

### Windows

```powershell
cd 停顿标注工具
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

看到类似输出表示成功：

```text
Uvicorn running on http://0.0.0.0:8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/api/health
# 应返回：{"status":"ok"}
```

**防火墙：** 若其他设备访问不了，需放行端口 8000（见第 12 节）。

### 6.1 停止服务

#### 情况 A：服务就在你当前这个终端前台运行

窗口里能看到 `Uvicorn running on http://0.0.0.0:8000`，且光标还在该窗口时：

- 按 **`Ctrl+C`** 即可正常停止。

#### 情况 B：Ctrl+C 无效 / 提示端口被占用（很常见）

说明 **8000 端口被另一个 Python 进程占用**，往往不在你当前这个终端里（例如：之前后台启动过、其它窗口启动过、或启动失败后仍有残留进程）。此时在当前窗口按 Ctrl+C **杀不到**那个进程。

**方法 1（推荐，Windows）：用停服脚本**

在资源管理器中进入 `停顿标注工具\scripts\`，双击 **`stop.bat`**。

或在 PowerShell / CMD 中：

```bat
cd 停顿标注工具
scripts\stop.bat
```

脚本会查找占用 8000 端口的进程并强制结束，结束后应提示 `Port 8000 is free`。

**方法 2：PowerShell 手动结束**

```powershell
# 1. 查看谁占用了 8000（看 LISTENING 那一行最后的 PID）
netstat -ano | findstr :8000

# 2. 把 12345 换成上一步的 PID
taskkill /PID 12345 /F
```

**方法 3：结束所有 python.exe（慎用）**

会关掉本机其它正在跑的 Python 程序：

```powershell
taskkill /IM python.exe /F
```

**方法 4：Linux**

```bash
# 查占用 8000 的进程
ss -lptn 'sport = :8000'
# 或
lsof -i :8000

# 结束（把 PID 换成实际值）
kill PID
# 仍不退出时
kill -9 PID
```

#### 启动失败报错「端口只允许使用一次 / Errno 10048」

含义：8000 已被占用。请先按上面 **情况 B** 释放端口，再重新启动：

```powershell
cd 停顿标注工具
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

#### 使用习惯建议

| 做法 | 说明 |
|------|------|
| 尽量在**同一个终端前台**启动服务 | 这样 `Ctrl+C` 就能停 |
| 不要重复开多个 uvicorn | 第二个会报端口占用 |
| 忘记在哪个窗口启动了 | 直接运行 `scripts\stop.bat` |
| 改完 `.env` 后 | 先停服，再启动，新链接才会用新 IP |

---

## 7. 如何打开主试端

### 7.1 地址

| 访问方式 | 地址 |
|----------|------|
| 本机 | http://127.0.0.1:8000/admin-login.html |
| 局域网 | http://\<局域网IP\>:8000/admin-login.html |
| 公网 | http://\<公网IP\>:8000/admin-login.html |

例如当前局域网 IP 为 `192.168.1.150` 时：

```text
http://192.168.1.150:8000/admin-login.html
```

### 7.2 首次登录

- 用户名：`admin`
- 密码：`admin`

登录成功后进入 **会话列表**。

> 安全建议：登录后立刻在「账号」里改密码，或新增主试账号后停用默认弱口令习惯；同时修改 `.env` 里的 `PIPELINE_TOKEN` 与 `SECRET_KEY`。

### 7.3 顶栏导航

| 菜单 | 页面 | 作用 |
|------|------|------|
| 列表 | `/admin-sessions.html` | 所有会话、进度、删除 |
| 设置 | `/admin-settings.html` | 指导语、可标注标签、原因类别（需管理员） |
| 账号 | `/admin-users.html` | 主试账号管理（需管理员） |
| 登出 | — | 退出登录 |

---

## 8. 主试端常用操作

### 8.1 会话列表

路径：登录后默认，或打开 `/admin-sessions.html`

表格字段：

- **被试编号**、**标题**、**状态**（待确认说话人 / 待打开 / 填写中 / 已提交）
- **进度**（已完成标注数 / 总标注数）
- **时间**
- **操作**：详情、删除

按钮：

- **刷新**：重新拉取列表
- **清理未提交测试会话**：一键删除所有「非已提交」会话（调试用，正式数据请谨慎）

### 8.2 会话详情（确认说话人并生成链接）

1. 对状态为 **待确认说话人** 的会话，点 **标注说话人**
2. 逐句检查对话，勾选所有 **主试说的** 话语；未勾选的视为被试话语
3. 点 **确认说话人并生成链接**。确认后说话人锁定，主试话语不产生被试标注点
4. 页面出现 **被试链接** 后点 **复制链接**
5. 若浏览器禁止自动复制：链接会处于选中状态，用 **Ctrl+C** / 手机长按复制
6. 把链接发给被试（微信、邮件等）

还可：

- **导出 JSON / CSV**
- **重置提交**：清空已填标注，允许被试再填
- **删除会话**：永久删除（不可恢复）

### 8.3 设置（管理员）

路径：`/admin-settings.html`

| 项 | 说明 |
|----|------|
| 指导语 | 被试页中央说明；新会话会快照保存 |
| 可标注标签 | 默认 `incomplete`、`wait`；可勾选 complete / backchannel |
| 原因类别 | 被试下拉选项，可增删改 |

改完点 **保存设置**。

### 8.4 账号（管理员）

路径：`/admin-users.html`

- 添加主试（实验员 / 管理员）
- 启用 / 停用
- 重置密码

所有主试登录后可看**全部会话**（不按人隔离）。

### 8.5 导出数据

在详情页：

- **导出 CSV**：一行一个标注点，便于 Excel / SPSS / R
- **导出 JSON**：整场结构，含指导语快照

CSV 主要列：`session_id`、`external_participant_id`、`seq`、`speaker`、`text`、`easyturn_label`、`category`、`description`、`confidence` 等。

---

## 9. 如何打开被试端

被试**不需要账号**，只用主试发来的链接：

```text
http://<PUBLIC_BASE_URL主机>/a/<一长串token>
```

例如：

```text
http://192.168.1.150:8000/a/A3PSYO0TF9VrEnQlIiImV1J_rQ-En0zuzS9X7T84Q0k
```

链接来源：

1. 主试在详情页复制  
2. 流水线创建会话后打印的主试审核地址；完成说话人确认后再从详情页复制

**注意：**

- token 相当于钥匙，不要发公开群
- 换网络后旧 IP 的链接会失效，需主试重新复制（token 可不变，主机部分随 `PUBLIC_BASE_URL` 变）

---

## 10. 被试如何填写与提交

1. 手机或电脑浏览器打开链接  
2. 阅读上方 **填写说明**（可折叠）  
3. 浏览完整对话（主试 + 被试）  
4. 仅在带标记的位置填写：
   - **原因类别**（须主动选择，不要只停在「请选择」）
   - **原因与心理过程**
   - **置信度 1–7**（点数字）
5. 右上角出现 **「已保存」** 表示草稿已写入  
6. 进度为 **全部完成**（如 `2/2`）后，点 **提交**  
7. 确认后锁定，不可再改（除非主试重置）

**建议：** 每个标记都填完并看到「已保存」再提交。系统会在提交前尽量冲刷未保存的输入。

---

## 11. 流水线如何创建会话

口语任务结束后，由 VAD/ASR/EasyTurn 流程调用 API。

### 11.1 使用自带客户端（推荐）

准备 `utterances.json`，例如：

```json
{
  "utterances": [
    {
      "seq": 1,
      "speaker": "experimenter",
      "text": "你有没有发生过一些童年趣事呀",
      "easyturn_label": "complete"
    },
    {
      "seq": 2,
      "speaker": "participant",
      "text": "因为小时候我去过那里。",
      "raw_text": "因为小时候<PAUSE:0.52s>我去过那里<PAUSE:1.15s>。",
      "pauses": [
        {"duration": 0.52},
        {"duration": 1.15}
      ]
    },
    {
      "seq": 3,
      "speaker": "participant",
      "text": "我小时候有一次",
      "easyturn_label": "wait",
      "pause_duration_ms": 1200
    }
  ]
}
```

字段说明：

| 字段 | 必填 | 说明 |
|------|------|------|
| `seq` | 是 | 对话顺序 |
| `speaker` | 是 | `participant`（被试）或 `experimenter`（主试） |
| `text` | 是 | 转写文本（可不含标签） |
| `easyturn_label` | 建议有 | 传统话轮标签；没有 `pauses` 时可用于兼容旧版按标签创建目标 |
| `raw_text` | 可选 | 可含 `<PAUSE:x.xs>`，用于页面显示原始停顿位置 |
| `pauses` | 推荐 | 当前规范；一个 utterance 可含多个 `{duration, ...}` pause，服务端只保留 `≥0.5s` 的停顿 |
| `extra.pauses` | 兼容 | 旧备份格式；服务端会按与顶层 `pauses` 相同的规则读取 |
| `pause_duration_ms` | 可选 | 旧版最长停顿字段，仍保留用于兼容 |

同机调用：

```bash
python scripts/pipeline_client.py \
  --base-url http://127.0.0.1:8000 \
  --token "你的PIPELINE_TOKEN" \
  --participant P001 \
  --title "预实验-口语任务" \
  --utterances /path/to/utterances.json
```

成功时会打印：

```text
Session created: ...
Speaker review: http://.../admin-detail.html?id=...
Confirm the speakers there to generate the participant URL.
```

打开 **Speaker review** 地址，标记主试话语并确认；页面生成链接后再发给被试。

> 提交历史 adapter 备份时，可直接把 `data/easyturn_backups/*.json` 作为
> `--utterances` 输入；服务端同时兼容顶层 `pauses` 和旧版 `extra.pauses`。

### 11.2 直接 HTTP

```bash
curl -X POST http://127.0.0.1:8000/api/pipeline/sessions \
  -H "Authorization: Bearer 你的PIPELINE_TOKEN" \
  -H "Content-Type: application/json" \
  -d @utterances_full_body.json
```

请求体需包含 `utterances` 数组，可选 `external_participant_id`、`title`、`annotatable_labels`。

**默认可标注标签：** `incomplete`、`wait`（仅被试侧会生成填写点）。

---

## 12. 局域网 / 公网部署说明

### 12.1 局域网（同一 WiFi）

1. `.env` 中 `PUBLIC_BASE_URL=http://本机局域网IP:8000`  
2. `HOST=0.0.0.0`，启动服务  
3. 防火墙放行 8000  
4. 手机连**同一 WiFi** 打开链接  

适合实验室内测；**手机 4G 打不开**。

### 12.2 公网固定 IP（线上被试推荐）

1. 使用有**固定公网 IP** 的云主机或实验室服务器  
2. 安全组 / 防火墙放行 TCP **8000**  
3. 上传本项目并安装  
4. `.env`：

```text
PUBLIC_BASE_URL=http://固定公网IP:8000
HOST=0.0.0.0
PORT=8000
```

5. 启动后用**手机 4G** 打开主试端与被试链接验收  

### 12.3 Windows 防火墙放行示例

管理员 PowerShell：

```powershell
New-NetFirewallRule -DisplayName "Pause Annotation 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow
```

### 12.4 家用路由端口转发（备选）

若本机在路由器后且有真公网 IP：

- 路由器：外网 `公网IP:8000` → 内网 `电脑IP:8000`  
- 电脑 IP 建议做 DHCP 静态绑定  
- `PUBLIC_BASE_URL=http://公网IP:8000`  

稳定性通常不如云主机。

### 12.5 GitHub + Render 免费公网部署（推荐）

无需购买服务器，利用 [Render](https://render.com) 免费层即可让主试端和被试端都通过公网访问。

#### 前提条件

- 已有 GitHub 账号，并将本项目上传到一个仓库（建议**私有仓库**，避免泄露密钥）
- `.gitignore` 中已包含 `.env` 和 `data/` 目录（项目默认已配置）

#### 第一步：注册并登录 Render

访问 [https://render.com](https://render.com)，用 GitHub 账号登录（授权后可直接读取仓库）。

#### 第二步：创建 Web Service

1. 点击右上角 **「New +」** → **「Web Service」**
2. 选择 **「Connect a repository」**，找到你的项目仓库，点击 **「Connect」**

#### 第三步：填写部署配置

| 字段 | 填写内容 |
|------|---------|
| **Root Directory** | 留空 |
| **Runtime** | `Python 3` |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| **Instance Type** | `Free`（$0/月） |

> ⚠️ Start Command 必须使用上面的命令，不要使用 Render 默认提示的 `gunicorn` 命令。

#### 第四步：配置环境变量

在 **Environment Variables** 部分，点击 **「+ Add Environment Variable」** 依次添加：

| Key | Value | 说明 |
|-----|-------|------|
| `HOST` | `0.0.0.0` | 监听所有网卡 |
| `DATABASE_PATH` | `./data/app.db` | 数据库路径 |
| `PIPELINE_TOKEN` | 点击右侧 **「Generate」** | 流水线鉴权密钥 |
| `SECRET_KEY` | 点击右侧 **「Generate」** | Session 密钥 |
| `PUBLIC_BASE_URL` | `https://temp.onrender.com` | 先填占位，部署后再改 |

#### 第五步：配置高级选项

在页面下方 **Advanced** 区域，只需修改一项：

- **Health Check Path**：填入 `/api/health`（其余保持默认）

#### 第六步：部署

点击底部 **「Create Web Service」**，Render 会自动克隆仓库、安装依赖并启动服务，等待 3–5 分钟，状态变为 **Live** 即表示成功。

部署完成后，你会得到一个公网地址，格式如：

```
https://your-app-name.onrender.com
```

#### 第七步：更新 PUBLIC_BASE_URL

这一步**非常重要**，否则生成的被试链接域名会错误。

1. 进入 Render Dashboard → 你的服务 → **「Environment」**
2. 找到 `PUBLIC_BASE_URL`，改为你的实际地址，例如：
   ```
   https://your-app-name.onrender.com
   ```
3. 点击 **「Save Changes」**，服务会自动重启

#### 第八步：验证

| 验证项 | 地址 |
|--------|------|
| 健康检查 | `https://your-app-name.onrender.com/api/health` → 应返回 `{"status":"ok"}` |
| 主试端 | `https://your-app-name.onrender.com/admin-login.html` |

首次登录账号：用户名 `admin`，密码 `admin`，**登录后请立即修改密码**。

#### 第九步：创建演示会话

首次部署后数据库为空，需用本地脚本创建会话。先在 Render Dashboard → Environment 中查看并复制 `PIPELINE_TOKEN` 的值，然后在本地 PowerShell 或 Git Bash 中运行：

```bash
# 进入项目目录
cd 停顿标注工具

# 激活虚拟环境（Windows）
.\.venv\Scripts\Activate.ps1

# 创建固定的演示会话
python scripts/create_demo_session.py \
  --base-url https://your-app-name.onrender.com \
  --token "你的PIPELINE_TOKEN"
```

成功后会打印主试说话人审核地址；完成审核后，在主试端「详情」页复制被试链接。

#### 后续代码更新

每次将代码 `git push` 到 GitHub，Render 会自动检测并重新部署，无需手动操作。

#### 免费层限制

| 限制 | 说明 |
|------|------|
| **自动休眠** | 15 分钟无请求后休眠，下次访问需等待约 50 秒冷启动 |
| **无持久化磁盘** | 服务重启后数据库会丢失；正式收数请升级到 Starter（$7/月）并挂载 Disk |
| **带宽** | 100 GB/月，日常实验足够使用 |

> 💡 **建议**：测试和演示阶段使用免费层；开始正式收集被试数据前，在 Render 升级 Starter 计划并添加 Disk（Mount Path: `/data`，Size: 1 GB），否则服务重启会导致数据丢失。

---

## 13. 换机迁移

**不麻烦。** 步骤：

1. 拷贝整个 `停顿标注工具` 文件夹到新机器  
2. 若需保留数据：确保带上 `data/app.db`  
3. 新机器安装 Python → 执行安装步骤  
4. 改 `.env` 里的 `PUBLIC_BASE_URL` 为新地址  
5. 启动并验收  

流水线若与标注工具同机，`--base-url` 仍可用 `http://127.0.0.1:8000`。

---

## 14. 备份与恢复

`easyturn_adapter.py` 产生的 JSON 备份统一写入 `data/easyturn_backups/`，不会再散落在仓库根目录。提交失败时，内存中的 utterances 不会清空，可修复服务后再次输入 `submit` 重试。

备份数据库：

```bash
# Linux
cp data/app.db data/app.db.$(date +%Y%m%d-%H%M%S).bak

# Windows PowerShell
Copy-Item data\app.db "data\app.db.$(Get-Date -Format yyyyMMdd-HHmmss).bak"
```

恢复：停服务 → 用备份覆盖 `data/app.db` → 再启动。

建议定期备份，尤其是正式收数期间。

---

## 15. 常见问题

### Q1：其他手机/电脑打不开链接？

- 链接是否写成了 `localhost`？（只有本机可用）  
- 服务是否监听 `0.0.0.0`？  
- `PUBLIC_BASE_URL` 是否为当前可达 IP？  
- 防火墙是否放行 8000？  
- 手机是否与电脑同一 WiFi？（局域网场景）  
- 线上被试是否应用公网 IP？（4G 打不开局域网地址是正常的）

### Q2：主试端「复制链接」没反应？

HTTP 局域网下浏览器可能禁用剪贴板 API。详情页已显示链接文本框：点选后 **Ctrl+C**，或使用页面上的复制按钮（失败会提示手动复制）。

### Q3：被试提交提示「还有未完成的标记」？

- 每个标记都要：选类别 + 写描述 + 点置信度  
- 类别不要停在「请选择类别…」  
- 等右上角「已保存」再提交  
- 页面已做提交前强制保存；仍失败时检查是否漏填某一处（如「等待」）

### Q4：改了 `.env` 但链接还是旧 IP？

必须**重启服务**。且只影响**新生成**的链接；旧消息里的旧链接不会自动变，请主试重新复制。

### Q5：列表里一堆测试会话？

主试列表可：

- 单行 **删除**  
- 或 **清理未提交测试会话**

已提交数据请勿误删。

### Q6：默认账号是什么？

- 用户名：`admin`  
- 密码：`admin`  
首次登录后请修改。

### Q7：流水线 401？

检查 `Authorization: Bearer <PIPELINE_TOKEN>` 是否与 `.env` 中完全一致。

### Q8：Ctrl+C 无法停止服务 / 启动报「端口只允许使用一次」？

说明 8000 端口被**另一个**进程占用，不一定在你当前终端里。

1. 运行 `scripts\stop.bat`（Windows），或用 `netstat -ano | findstr :8000` 查 PID 后 `taskkill /PID <PID> /F`
2. 确认端口空闲后再启动
3. 尽量只在一个前台终端启动服务，这样 `Ctrl+C` 才能直接停

详见 [§6.1 停止服务](#61-停止服务)。

---

## 16. 目录结构

```text
停顿标注工具/
├── app/                    # FastAPI 后端
│   ├── main.py             # 入口；/a/{token} 返回被试页
│   ├── config.py           # 读取 .env
│   ├── database.py         # SQLite
│   ├── sqlite_migrations.py # 旧数据库无损迁移
│   ├── models.py           # 数据表
│   ├── schemas.py          # 接口模型
│   ├── auth.py             # 主试登录 / 流水线鉴权
│   ├── utils.py            # token、EasyTurn 解析、默认指导语
│   └── routers/
│       ├── pipeline.py     # 创建会话
│       ├── participant.py  # 被试 API
│       └── admin.py        # 主试 API
├── static/                 # 前端（无需 npm 构建）
│   ├── participant.html    # 被试填写页
│   ├── admin-login.html    # 主试登录
│   ├── admin-sessions.html # 会话列表
│   ├── admin-detail.html   # 会话详情
│   ├── admin-settings.html # 设置
│   ├── admin-users.html    # 账号
│   └── css/style.css
├── scripts/
│   ├── install.sh          # 安装（Linux）
│   ├── run.sh              # 启动（Linux）
│   ├── stop.bat            # 停止：结束占用 8000 端口的进程（Windows）
│   └── pipeline_client.py  # 流水线客户端
├── data/                   # 数据库目录（app.db 自动生成）
│   └── easyturn_backups/   # adapter JSON 备份（不提交到 GitHub）
├── .env.example            # 配置模板
├── .env                    # 实际配置（勿提交密钥到公开仓库）
├── requirements.txt
└── README.md               # 本文件
```

Easy-Turn 云主机源码快照不属于本项目运行时依赖，也不应提交到 GitHub。它已移到被 `.gitignore` 忽略的 `.local-reference/easyturn-cloud-snapshot/`，仓库只保留脱敏后的集成说明：[`docs/easyturn/README.md`](docs/easyturn/README.md)。

---

## 17. 验收清单

安装部署后建议按顺序勾选：

- [ ] `curl http://127.0.0.1:8000/api/health` 返回 `{"status":"ok"}`
- [ ] 浏览器能打开主试登录页并使用 `admin` / `admin` 登录
- [ ] 流水线或 `pipeline_client.py` 能创建「待确认说话人」会话
- [ ] 主试详情页能标记主试话语，确认后才显示被试链接
- [ ] 本机或同 WiFi 手机能打开被试页并看到对话与标记
- [ ] 被试填写后自动暂存，全部完成后可提交
- [ ] 主试列表进度更新，可导出 CSV/JSON
- [ ] （线上场景）手机 **4G** 能打开 `PUBLIC_BASE_URL` 下的链接
- [ ] 已修改默认密码与 `PIPELINE_TOKEN` / `SECRET_KEY`
- [ ] 已确认 `data/app.db` 备份方式

---

## 附录：常用 URL 一览

假设 `PUBLIC_BASE_URL=http://192.168.1.150:8000`：

| 页面 | URL |
|------|-----|
| 健康检查 | http://192.168.1.150:8000/api/health |
| 主试登录 | http://192.168.1.150:8000/admin-login.html |
| 会话列表 | http://192.168.1.150:8000/admin-sessions.html |
| 设置 | http://192.168.1.150:8000/admin-settings.html |
| 账号 | http://192.168.1.150:8000/admin-users.html |
| 被试填写 | http://192.168.1.150:8000/a/\<token\> |

把 `192.168.1.150` 换成你的实际 IP 或域名即可。
