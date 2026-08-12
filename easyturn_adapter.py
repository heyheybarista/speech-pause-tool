#!/usr/bin/env python3
"""
Easy-Turn 到停顿标注工具的适配脚本

功能：
1. 连接到 Easy-Turn Socket.IO 服务（通过 SSH 隧道）
2. 监听 final_transcription 事件
3. 解析停顿和标签
4. 累积 utterances
5. 任务结束时 POST 到停顿标注工具 API

用法：
    python easyturn_adapter.py

也可通过参数跳过启动时的交互输入：
    python easyturn_adapter.py --participant P001 --title "预实验-口语任务"
"""

import re
import json
import time
import argparse
import sys
from typing import List, Dict, Optional
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

try:
    import socketio
    import requests
except ImportError:
    print("缺少依赖，正在安装...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install",
                          "python-socketio[client]", "requests"])
    import socketio
    import requests


PAUSE_ANNOTATION_THRESHOLD_SECONDS = 0.5


class EasyTurnAdapter:
    """Easy-Turn 到停顿标注工具的适配器"""

    def __init__(self,
                 easyturn_url: str = "http://127.0.0.1:6006",
                 annotation_tool_url: str = "https://ting-dun-biao-zhu-gong-ju.onrender.com",
                 pipeline_token: str = "change-me",
                 client_id: Optional[str] = None):
        self.easyturn_url = easyturn_url
        self.annotation_tool_url = annotation_tool_url
        self.pipeline_token = pipeline_token
        self.client_id = client_id  # 与浏览器共享，使服务端广播给本脚本

        self.sio = socketio.Client(logger=False, engineio_logger=False)
        self.utterances: List[Dict] = []
        self.sequence_counter = 0
        self.participant_id: Optional[str] = None
        self.session_title: Optional[str] = None
        self._result_groups = OrderedDict()
        self.backup_dir = Path(__file__).resolve().parent / "data" / "easyturn_backups"

        self._register_handlers()

    def _register_handlers(self):
        """注册 Socket.IO 事件处理器"""

        @self.sio.on('connect')
        def on_connect():
            print("✓ 已连接到 Easy-Turn 服务")
            # 注册 client_id，使服务端将事件广播给本脚本
            if self.client_id:
                self.sio.emit('register_client', {
                    'client_id': self.client_id,
                    'last_result_seq': 0
                })
                print(f"✓ 已注册 client_id: {self.client_id}")
            print("=" * 60)
            print("连接已建立，请先在 Adapter 终端填写本轮录音信息。")
            print("=" * 60)

        @self.sio.on('disconnect')
        def on_disconnect():
            print("\n✗ 与 Easy-Turn 断开连接")

        def _handle_final(data):
            """处理最终转录结果，保留同一结果的最高 revision。"""
            data = data or {}
            result_id = (data or {}).get('result_id')
            revision = self._revision_number(data.get('revision', 1))
            if result_id:
                previous = self._result_groups.get(result_id)
                if previous and revision <= previous['revision']:
                    return
            try:
                annotated = data.get('annotated_text') or data.get('text', '')
                annotated = self._remove_short_pause_tags(annotated)
                if '<TURN_TRANSITION>' in (annotated or ''):
                    utterances = self._split_by_turn_transitions(
                        annotated,
                        data.get('label'),
                        result_id=result_id,
                        revision=revision,
                    )
                else:
                    u = self._parse_transcription(data)
                    utterances = [u] if u else []
                if not utterances:
                    return
                if result_id:
                    self._result_groups[result_id] = {
                        'revision': revision,
                        'utterances': utterances,
                    }
                else:
                    key = f'legacy-{time.time_ns()}'
                    self._result_groups[key] = {
                        'revision': revision,
                        'utterances': utterances,
                    }
                self._rebuild_utterances()
                for u in utterances:
                    self._display_utterance(u)
            except Exception as e:
                print(f"⚠ 解析转录结果失败: {e}")
                print(f"   原始数据: {json.dumps(data, ensure_ascii=False, indent=2)}")

        # 全局广播事件（服务端为外部脚本额外发送的一份）
        @self.sio.on('final_transcription_broadcast')
        def on_final_broadcast(data):
            _handle_final(data)

        # 本连接自身的结果（注册了相同 client_id 时也会收到）
        @self.sio.on('final_transcription')
        def on_final_transcription(data):
            _handle_final(data)

        @self.sio.on('error')
        def on_error(data):
            print(f"⚠ Easy-Turn 错误: {data.get('message', data)}")

    def _parse_transcription(self, data: Dict) -> Optional[Dict]:
        """
        解析 final_transcription 数据

        返回格式：
        {
            "seq": 1,
            "speaker": "participant",
            "text": "纯文本",
            "raw_text": "带标记的文本",
            "easyturn_label": "complete",
            "pauses": [...],
            "pause_duration_ms": 最长停顿时长
        }
        """
        # 提取基本字段
        annotated_text = data.get('annotated_text') or data.get('text', '')
        annotated_text = self._remove_short_pause_tags(annotated_text)
        transcript = data.get('transcript', '')
        label = data.get('label')
        pauses = []
        for pause in (data.get('pauses', []) or []):
            if not isinstance(pause, dict) or not self._is_annotatable_pause(pause.get('duration')):
                continue
            normalized = dict(pause)
            normalized['duration'] = round(float(normalized['duration']), 3)
            normalized.pop('level', None)
            pauses.append(normalized)

        if not annotated_text and not transcript:
            return None

        # 如果没有 transcript，从 annotated_text 清理标记
        if not transcript:
            transcript = self._clean_annotations(annotated_text)

        # 从 annotated_text 提取停顿（如果 pauses 为空）
        if not pauses:
            pauses = self._extract_pauses_from_text(annotated_text)

        # 计算最长停顿时长
        max_pause_ms = 0
        if pauses:
            max_pause_ms = int(max(p.get('duration', 0) for p in pauses) * 1000)

        return {
            "seq": 0,
            "speaker": "participant",
            "text": transcript.strip(),
            "raw_text": annotated_text,
            "easyturn_label": label,
            "pauses": pauses,
            "pause_duration_ms": max_pause_ms,
            "extra": {
                "result_id": data.get('result_id'),
                "revision": data.get('revision', 1),
                "timestamp": time.time(),
                "pauses": pauses,
            }
        }

    def _split_by_turn_transitions(
            self,
            annotated_text: str,
            label: Optional[str],
            result_id: Optional[str] = None,
            revision: int = 1) -> List[Dict]:
        """
        按 <TURN_TRANSITION> 拆分 annotated_text，每段生成一个 utterance。

        规则：
        - <PAUSE> 出现在 <TURN_TRANSITION> 之前 → 自然归属当前段末尾（无需处理）
        - <PAUSE> 出现在 <TURN_TRANSITION> 之后 → 移到 <TURN_TRANSITION> 之前，归上一段末尾
        """
        # 把 <TURN_TRANSITION> 后紧跟的 <PAUSE:x.xs> 移到前面
        text = re.sub(
            r'<TURN_TRANSITION>\s*(<PAUSE:\d+(?:\.\d+)?s>)',
            r'\1 <TURN_TRANSITION>',
            annotated_text
        )

        # 按 <TURN_TRANSITION> 拆分
        segments = re.split(r'\s*<TURN_TRANSITION>\s*', text)
        segments = [s.strip() for s in segments if s.strip()]

        if not segments:
            return []

        results = []
        for i, seg_text in enumerate(segments):
            is_last = (i == len(segments) - 1)
            clean_text = self._clean_annotations(seg_text)
            pauses = self._extract_pauses_from_text(seg_text)

            if not clean_text and not pauses:
                continue

            # 中间段（后接 TURN_TRANSITION）= 语义完整
            # 最后一段 = 使用 Easy-Turn 实际返回的标签
            seg_label = label if is_last else 'complete'
            max_pause_ms = int(max(p['duration'] for p in pauses) * 1000) if pauses else 0

            results.append({
                "seq": 0,
                "speaker": "participant",
                "text": clean_text,
                "raw_text": seg_text,
                "easyturn_label": seg_label,
                "pauses": pauses,
                "pause_duration_ms": max_pause_ms,
                "extra": {
                    "result_id": result_id,
                    "revision": revision,
                    "timestamp": time.time(),
                    "segment_index": i,
                    "total_segments": len(segments),
                    "pauses": pauses,  # 传给标注工具用于创建 AnnotationTarget
                }
            })

        return results

    @staticmethod
    def _revision_number(value) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 1

    def _rebuild_utterances(self):
        """Flatten the latest result groups and renumber utterances."""
        flattened = []
        for group in self._result_groups.values():
            flattened.extend(group['utterances'])
        for seq, utterance in enumerate(flattened, start=1):
            utterance['seq'] = seq
        self.sequence_counter = len(flattened)
        self.utterances = flattened

    def _clean_annotations(self, text: str) -> str:
        """清理文本中的标注标记"""
        # 移除 <PAUSE:x.xxs>
        text = re.sub(r'<PAUSE:\d+\.\d+s>', '', text)
        # 移除 <TURN_TRANSITION>
        text = re.sub(r'<TURN_TRANSITION>', '', text)
        # 移除其他标签
        text = re.sub(r'<[^>]+>', '', text)
        # 清理多余空格
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    def _extract_pauses_from_text(self, text: str) -> List[Dict]:
        """从 annotated_text 提取停顿信息，记录每个停顿在文本中的位置"""
        pauses = []
        pattern = r'<PAUSE:(\d+(?:\.\d+)?)s>'
        offset = 0  # 累积已移除标签的字符偏移
        for match in re.finditer(pattern, text):
            duration = float(match.group(1))
            if not self._is_annotatable_pause(duration):
                offset += len(match.group(0))
                continue
            # 停顿在清理后文本中的位置
            position_in_clean = match.start() - offset
            offset += len(match.group(0))

            pauses.append({
                "duration": round(duration, 3),
                "kind": "pause",
                "position": match.start(),
                "position_in_clean_text": position_in_clean,
            })
        return pauses

    @staticmethod
    def _is_annotatable_pause(duration) -> bool:
        try:
            return float(duration) >= PAUSE_ANNOTATION_THRESHOLD_SECONDS
        except (TypeError, ValueError):
            return False

    @classmethod
    def _remove_short_pause_tags(cls, text: str) -> str:
        pattern = re.compile(r'<PAUSE:(\d+(?:\.\d+)?)s>')
        return pattern.sub(
            lambda match: match.group(0)
            if cls._is_annotatable_pause(match.group(1)) else '',
            text or '',
        )

    def _display_utterance(self, utterance: Dict):
        """显示转录结果"""
        seq = utterance['seq']
        text = utterance['text']
        label = utterance.get('easyturn_label') or 'unknown'
        pauses = utterance.get('pauses', [])

        # 标签颜色映射
        label_colors = {
            'complete': '\033[92m',      # 绿色
            'incomplete': '\033[93m',    # 黄色
            'backchannel': '\033[94m',   # 蓝色
        }
        color = label_colors.get(label, '\033[0m')
        reset = '\033[0m'

        print(f"\n[{seq}] {color}{label.upper()}{reset}")
        print(f"    {text}")

        if pauses:
            pause_str = ", ".join([f"{p['duration']:.3f}s" for p in pauses])
            print(f"    停顿: {pause_str}")

    def connect(self):
        """连接到 Easy-Turn 服务"""
        try:
            print(f"正在连接到 Easy-Turn: {self.easyturn_url}")
            print("提示: 连接后在浏览器进行录音，转录结果会自动同步到这里")
            self.sio.connect(
                self.easyturn_url,
                transports=['polling', 'websocket'],
                wait_timeout=10
            )
            # 连接成功后等待一下确保事件注册完成
            time.sleep(0.5)
            return True
        except Exception as e:
            print(f"✗ 连接失败: {e}")
            print(f"  请确认:")
            print(f"    1. SSH 隧道已建立 (ssh -L 6006:127.0.0.1:6006 ...)")
            print(f"    2. Easy-Turn 服务正在运行")
            print(f"    3. 浏览器能访问 http://127.0.0.1:6006")
            return False

    def disconnect(self):
        """断开连接"""
        if self.sio.connected:
            self.sio.disconnect()

    def create_annotation_session(self) -> Optional[Dict]:
        """创建停顿标注会话"""
        if not self.utterances:
            print("⚠ 没有可提交的转录内容")
            return None

        # 构建请求数据
        payload = {
            "external_participant_id": self.participant_id,
            "title": self.session_title,
            "utterances": self.utterances
        }

        url = f"{self.annotation_tool_url}/api/pipeline/sessions"
        headers = {
            "Authorization": f"Bearer {self.pipeline_token}",
            "Content-Type": "application/json"
        }

        try:
            print(f"\n正在创建标注会话...")
            print(f"  参与者: {self.participant_id}")
            print(f"  标题: {self.session_title}")
            print(f"  语句数: {len(self.utterances)}")

            response = requests.post(url, json=payload, headers=headers, timeout=(10, 120))
            response.raise_for_status()

            result = response.json()
            print(f"\n✓ 标注会话创建成功!")
            print(f"  Session ID: {result['session_id']}")
            print(f"\n请先在主试端标注说话人:")
            print(f"  {result['admin_url']}")
            print("  确认后，页面会生成可发送给被试的链接。")

            return result

        except requests.exceptions.ConnectionError:
            print(f"✗ 无法连接到停顿标注工具 ({self.annotation_tool_url})")
            print("  请确认标注工具服务已启动")
            return None
        except requests.exceptions.HTTPError as e:
            print(f"✗ API 请求失败: {e}")
            if e.response is not None:
                try:
                    error_detail = e.response.json()
                    print(f"  详情: {error_detail}")
                except:
                    print(f"  响应: {e.response.text}")
            return None
        except Exception as e:
            print(f"✗ 创建会话失败: {e}")
            return None

    def save_to_json(self, filepath: str):
        """保存 utterances 到 JSON 文件"""
        path = Path(filepath)
        if not path.is_absolute():
            path = self.backup_dir / path
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "participant_id": self.participant_id,
            "title": self.session_title,
            "timestamp": time.time(),
            "utterances": self.utterances
        }
        with path.open('w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✓ 数据已保存到: {path}")
        return path

    def _configure_round(
            self,
            participant_id: Optional[str] = None,
            title: Optional[str] = None):
        """Collect and display metadata before a recording round starts."""
        self.participant_id = participant_id or prompt_required("被试编号")
        self.session_title = title or prompt_required("对话标题")
        print("\n本轮录音信息")
        print(f"  被试编号: {self.participant_id}")
        print(f"  对话标题: {self.session_title}")
        print("信息已确认，可以开始本轮录音。")

    def run_daemon(
            self,
            participant_id: Optional[str] = None,
            title: Optional[str] = None):
        """常驻模式：持续运行，自动同步转录结果"""
        if not self.connect():
            return

        try:
            self._configure_round(participant_id, title)

            print("\n" + "=" * 60)
            print("常驻模式已启动")
            print("=" * 60)
            print("在 Easy-Turn 页面录音，每条转录会自动记录并备份。")
            print()
            print("命令:")
            print("  submit  - 提交本轮并填写下一轮信息")
            print("  save    - 保存 JSON 备份")
            print("  clear   - 清空当前累积的 utterances")
            print("  quit    - 退出脚本")
            print("  Ctrl+C  - 快速退出（不创建会话）")
            print("=" * 60 + "\n")

            while True:
                try:
                    cmd = input("输入命令: ").strip().lower()

                    if cmd == 'submit':
                        if not self.utterances:
                            print("⚠ 没有可提交的内容")
                            continue

                        # 保存备份
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                        backup_file = f"easyturn_backup_{timestamp}.json"
                        self.save_to_json(backup_file)

                        # 创建会话
                        result = self.create_annotation_session()
                        if result is None:
                            print("\n提交未成功，当前内容仍保留，可修复服务后再次输入 submit 重试。")
                            print("=" * 60 + "\n")
                            continue

                        # 清空当前累积，准备下一轮
                        self.utterances.clear()
                        self.sequence_counter = 0
                        self._result_groups.clear()
                        print("\n本轮已提交并清空。请填写下一轮录音信息。")
                        print("若不再录音，可按 Ctrl+C 退出。")
                        self._configure_round()
                        print("=" * 60 + "\n")

                    elif cmd == 'save':
                        if not self.utterances:
                            print("⚠ 没有内容可保存")
                            continue
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                        filename = f"easyturn_{self.participant_id}_{timestamp}.json"
                        self.save_to_json(filename)

                    elif cmd == 'clear':
                        count = len(self.utterances)
                        self.utterances.clear()
                        self.sequence_counter = 0
                        self._result_groups.clear()
                        print(f"✓ 已清空 {count} 条记录")

                    elif cmd == 'quit':
                        print("退出中...")
                        break

                    elif cmd == '':
                        continue

                    else:
                        print(f"未知命令: {cmd}")

                except EOFError:
                    # Ctrl+D on Unix or Ctrl+Z on Windows
                    print("\n收到 EOF，退出")
                    break

        except KeyboardInterrupt:
            print("\n\n收到 Ctrl+C，退出 Adapter；尚未 submit 的当前内容未上传")

        finally:
            self.disconnect()
            print("连接已关闭")


def prompt_required(label: str) -> str:
    """Prompt until a non-empty session metadata value is entered."""
    while True:
        try:
            value = input(f"请输入{label}: ").strip()
        except EOFError as exc:
            raise SystemExit(f"未输入{label}，无法开始录音") from exc
        if value:
            return value
        print(f"⚠ {label}不能为空，请重新输入")


def main():
    parser = argparse.ArgumentParser(
        description="Easy-Turn 到停顿标注工具的适配脚本"
    )
    parser.add_argument(
        "--participant",
        default=None,
        help="被试编号；不提供时在录音前输入"
    )
    parser.add_argument(
        "--title",
        default=None,
        help="对话标题；不提供时在录音前输入"
    )
    parser.add_argument(
        "--easyturn-url",
        default="http://127.0.0.1:6006",
        help="Easy-Turn 服务地址 (默认: http://127.0.0.1:6006)"
    )
    parser.add_argument(
        "--annotation-url",
        default="https://ting-dun-biao-zhu-gong-ju.onrender.com",
        help="停顿标注工具地址 (默认: Render 部署地址)"
    )
    parser.add_argument(
        "--token",
        default="change-me",
        help="Pipeline API Token (默认: change-me，从 .env 读取)"
    )
    parser.add_argument(
        "--client-id",
        default=None,
        help="与浏览器共享的 client_id（从浏览器 localStorage 获取）"
    )

    args = parser.parse_args()

    # 尝试从环境变量或 .env 读取 token
    if args.token == "change-me":
        try:
            env_path = Path(__file__).resolve().parent / ".env"
            with env_path.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("PIPELINE_TOKEN="):
                        args.token = line.split("=", 1)[1].strip().strip('"')
                        break
        except FileNotFoundError:
            pass

    adapter = EasyTurnAdapter(
        easyturn_url=args.easyturn_url,
        annotation_tool_url=args.annotation_url,
        pipeline_token=args.token,
        client_id=args.client_id
    )

    adapter.run_daemon(
        participant_id=args.participant,
        title=args.title
    )


if __name__ == "__main__":
    main()
