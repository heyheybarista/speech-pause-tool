# Easy-Turn 集成说明

这份文档记录仓库中实际需要的 Easy-Turn 集成边界。完整的云主机源码、压缩包和历史手册属于本地参考材料，不属于停顿标注工具的运行时依赖。

## 文件归属

- 适配器：[`easyturn_adapter.py`](../../easyturn_adapter.py)
- 适配器依赖：[`requirements.txt`](../../requirements.txt) 中的 `requests` 和 `python-socketio[client]`
- JSON 备份：`data/easyturn_backups/`，仅本地保存，不提交到 GitHub
- 云主机源码快照：`.local-reference/easyturn-cloud-snapshot/`，已被 `.gitignore` 排除
- 脱敏后的 API 示例：[`../../scripts/pipeline_client.py`](../../scripts/pipeline_client.py)

## 工作流

```text
AutoDL / Easy-Turn :6006
        │ SSH local forward 6006
        ▼
本地 easyturn_adapter.py
        │ POST /api/pipeline/sessions
        ▼
Render 停顿标注工具
        │ 待确认说话人
        ▼
主试端：/admin-detail.html?id={session_id}
        │ 确认并生成链接
        ▼
被试端：/a/{access_token}
```

适配器监听 `final_transcription` 和（云端广播补丁提供的）`final_transcription_broadcast`。同一个 `result_id` 的较高 `revision` 会替换旧结果，因此跨话轮边界 pause 不会被重复或丢弃。

### 浏览器输入源

Easy-Turn 浏览器页支持在录音前选择输入源：

- `麦克风`：通过 `getUserMedia()` 采集本机麦克风，保持原有流程；
- `系统声音`：通过 `getDisplayMedia()` 打开浏览器共享选择器，需要选择标签页、窗口或屏幕并勾选共享音频。

两种模式最终都复用同一个 AudioWorklet 和 `audio_binary` Socket.IO 协议，录音期间不能切换输入源。系统声音共享结束时，本次录音会自动停止；如果共享时没有音频轨道，页面会提示重新选择并勾选共享音频。

## 当前数据契约

一个 utterance 可以包含多个 pause：

只有 `≥0.5s` 的停顿会被视为 pause；更短的停顿会从原始文本和 pause 列表中移除。界面保留基于时长的颜色区分，但不显示 `short`、`medium`、`long` 等级名称。

```json
{
  "seq": 2,
  "speaker": "participant",
  "text": "我看到一个人正在思考。",
  "raw_text": "我看到一个人<PAUSE:0.52s>正在思考<PAUSE:1.15s>。",
  "pauses": [
    {"duration": 0.52},
    {"duration": 1.15}
  ],
  "extra": {
    "pauses": [
      {"duration": 0.52},
      {"duration": 1.15}
    ]
  }
}
```

`pauses` 是当前规范字段；`extra.pauses` 只为历史备份兼容。主试确认说话人后，服务端只为被试话语中的 pause 创建 `annotation_target`，并用 `target_index` 保持句内顺序。

如果被试话语后紧接主试话轮，服务端只移除该被试话语的最后一个 pause；同一句前面的 pause 不受影响。

## 操作要点

1. 在 AutoDL 上启动 Easy-Turn，并建立 `ssh -L 6006:127.0.0.1:6006 ...` 隧道。
2. 在本地运行 `python easyturn_adapter.py`。Adapter 先连接 Easy-Turn，再提示输入第一轮的被试编号和对话标题；看到“信息已确认”后开始录音。需要自动化启动时，仍可使用 `--participant P001 --title "口语任务"` 跳过第一轮的交互输入。
3. 输入 `submit` 时会先在 `data/easyturn_backups/` 写入备份，再把被试编号、对话标题和 utterances 一起请求 Render。
4. 请求失败时不会清空当前 utterances；修复网络或服务后可再次输入 `submit`。
5. 请求成功后，Adapter 打印主试说话人审核地址。主试勾选自己说的话并确认后，页面才生成被试链接；主试话语不需要被试标注。
6. 成功后会清空当前轮次，并立即要求填写下一轮的被试编号和对话标题；完成后再开始下一轮录音。`clear` 只会手动丢弃当前轮次的转录，不会提交。

历史备份可以用下面的命令重新提交：

```powershell
python scripts/pipeline_client.py `
  --base-url https://你的-render-地址 `
  --token "$env:PIPELINE_TOKEN" `
  --participant P001 `
  --title "补交的口语任务" `
  --utterances data/easyturn_backups/easyturn_backup_YYYYMMDD_HHMMSS.json
```

## 云端快照与安全

本地快照中包含历史密码、Pipeline token 和私钥文件，不能发布到公开仓库。相关凭据应视为已经泄露，并在 AutoDL / Render 上轮换；`.local-reference/` 只是为了保留排障参考，不是安全存储。

快照中的旧版 web demo 使用 `client_id` 注册机制，而当前适配器还依赖云端的 `final_transcription_broadcast` 广播补丁。发布前应以实际运行的 AutoDL 版本为准，不要把快照当作可直接部署的源码包。
