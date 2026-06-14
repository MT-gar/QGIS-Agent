# -*- coding: utf-8 -*-
"""
会话管理

管理 Agent 的对话历史和会话状态。
支持多会话、持久化存储。
"""

import json
import os
from typing import Optional, List, Dict
from datetime import datetime
from uuid import uuid4


def _log(message: str):
    """统一日志输出：优先写 QGIS 消息日志，无 QGIS 环境时回退到 print。"""
    try:
        from qgis.core import QgsMessageLog, Qgis
        QgsMessageLog.logMessage(message, 'QGIS Agent', Qgis.Warning)
    except Exception:
        print(message)


class Session:
    """
    单个对话会话。

    包含：
    - 会话 ID
    - 会话名称
    - 创建时间
    - 消息历史
    - 配置（LLM 模型、provider、采样参数；**不含 API Key**，敏感信息不落盘）
    """

    def __init__(self, session_id: Optional[str] = None, name: str = '新会话'):
        """
        初始化会话。

        :param session_id: 会话 ID（自动生成，使用 uuid4 保证唯一）
        :param name: 会话名称
        """
        # 用 uuid4 生成唯一 ID，避免秒级时间戳在同一秒内创建多个会话相互覆盖
        self.session_id = session_id or uuid4().hex
        self.name = name
        self.created_at = datetime.now().isoformat()
        self.messages: List[Dict] = []
        self.config: Dict = {
            'model': 'gpt-4o',
            'provider': 'openai',
            'temperature': 0.0,
            'max_tokens': 4096,
        }

    def add_message(self, role: str, content: str):
        """
        添加消息到会话历史。

        :param role: 角色 ('user' / 'assistant' / 'system')
        :param content: 消息内容
        """
        self.messages.append({
            'role': role,
            'content': content,
            'timestamp': datetime.now().isoformat(),
        })

    def get_history(self, limit: Optional[int] = None) -> List[Dict]:
        """
        获取消息历史。

        :param limit: 最大返回条数（None 表示全部）
        :return: 消息列表
        """
        if limit is None:
            return self.messages
        if limit <= 0:
            # limit=0 明确表示不返回任何历史（避免 messages[-0:] 返回全部的陷阱）
            return []
        return self.messages[-limit:]

    def clear(self):
        """清空消息历史。"""
        self.messages = []

    def to_dict(self) -> dict:
        """
        转换为字典（用于序列化）。

        :return: 会话字典
        """
        return {
            'session_id': self.session_id,
            'name': self.name,
            'created_at': self.created_at,
            'messages': self.messages,
            'config': self.config,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Session':
        """
        从字典反序列化。

        :param data: 会话字典
        :return: Session 实例
        """
        session = cls(
            session_id=data.get('session_id'),
            name=data.get('name', '新会话'),
        )
        session.created_at = data.get('created_at', session.created_at)
        session.messages = data.get('messages', [])
        session.config = data.get('config', session.config)
        return session


class SessionManager:
    """
    会话管理器。

    管理多个会话的创建、切换、保存和加载。
    持久化到 JSON 文件。
    """

    def __init__(self, storage_path: Optional[str] = None):
        """
        初始化会话管理器。

        :param storage_path: 持久化存储路径（默认 QGIS 配置目录，回退到系统临时目录）
        """
        if storage_path is None:
            storage_path = os.path.join(
                self._default_storage_dir(), 'qgis_agent_sessions.json'
            )
        self.storage_path = storage_path
        self.sessions: Dict[str, Session] = {}
        self.active_session_id: Optional[str] = None

        # 加载持久化的会话
        self._load()

        # 如果没有活跃会话，创建一个新的
        if not self.sessions:
            self.create_session()

    def create_session(self, name: str = '新会话') -> Session:
        """
        创建新会话。

        :param name: 会话名称
        :return: 新创建的 Session
        """
        session = Session(name=name)
        self.sessions[session.session_id] = session
        self.active_session_id = session.session_id
        self._save()
        return session

    def switch_session(self, session_id: str) -> bool:
        """
        切换到指定会话。

        :param session_id: 会话 ID
        :return: 是否成功
        """
        if session_id in self.sessions:
            self.active_session_id = session_id
            return True
        return False

    def get_active_session(self) -> Optional[Session]:
        """
        获取当前活跃会话。

        :return: Session 或 None
        """
        if self.active_session_id and self.active_session_id in self.sessions:
            return self.sessions[self.active_session_id]
        return None

    def list_sessions(self) -> List[dict]:
        """
        列出所有会话。

        :return: 会话信息列表
        """
        result = []
        for sid, session in self.sessions.items():
            result.append({
                'session_id': sid,
                'name': session.name,
                'created_at': session.created_at,
                'message_count': len(session.messages),
                'is_active': sid == self.active_session_id,
            })
        # 按创建时间倒序
        result.sort(key=lambda x: x['created_at'], reverse=True)
        return result

    def delete_session(self, session_id: str) -> bool:
        """
        删除会话。

        :param session_id: 会话 ID
        :return: 是否成功
        """
        if session_id in self.sessions:
            del self.sessions[session_id]
            if self.active_session_id == session_id:
                self.active_session_id = (
                    list(self.sessions.keys())[0] if self.sessions else None
                )
            self._save()
            return True
        return False

    def add_message(self, role: str, content: str):
        """
        向当前活跃会话添加消息。

        :param role: 角色
        :param content: 内容
        """
        session = self.get_active_session()
        if session:
            session.add_message(role, content)
            self._save()

    @staticmethod
    def _default_storage_dir() -> str:
        """返回会话持久化目录：优先 QGIS 配置目录，回退系统临时目录。"""
        try:
            from qgis.core import QgsApplication
            path = QgsApplication.qgisSettingsDirPath()
            if path:
                return path
        except Exception:
            pass
        import tempfile
        return tempfile.gettempdir()

    def _save(self):
        """保存所有会话到 JSON 文件。"""
        data = {
            'active_session_id': self.active_session_id,
            'sessions': {
                sid: session.to_dict()
                for sid, session in self.sessions.items()
            }
        }
        try:
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            _log(f'[SessionManager] 保存失败: {e}')

    def _load(self):
        """从 JSON 文件加载会话。"""
        if not os.path.exists(self.storage_path):
            return

        try:
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            for sid, sdata in data.get('sessions', {}).items():
                self.sessions[sid] = Session.from_dict(sdata)

            self.active_session_id = data.get('active_session_id')
        except Exception as e:
            _log(f'[SessionManager] 加载失败: {e}')
