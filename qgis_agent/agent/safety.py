# -*- coding: utf-8 -*-
"""
安全控制工具

提供 Agent 操作的安全控制：
- 危险操作确认
- 执行日志记录
- 工具调用速率限制
"""

import time
import os
from typing import Optional, List, Dict
from datetime import datetime


class SafetyGuard:
    """
    安全守卫。

    管理工具调用的安全策略：
    - 危险操作二次确认
    - 执行日志
    - 速率限制
    """

    def __init__(self, log_path: Optional[str] = None):
        """
        初始化安全守卫。

        :param log_path: 日志文件路径
        """
        # 危险操作列表（需要二次确认）
        self.dangerous_operations = [
            'remove_layer',
            'delete_feature',
            'delete_selected_features',
            'run_algorithm',  # 可能修改数据
            'execute_python_code',  # 任意代码执行
            'qgis_api_call',  # 任意 API 链式调用，等价于任意代码执行
            'save_project',  # 可能覆盖
            'new_project',  # 清空项目
            'save_layer_as',  # 覆盖文件
        ]

        # 操作日志
        self.log_path = log_path or self._default_log_path()
        self.call_log: List[Dict] = []
        # call_log 内存条数上限，防止长会话无限增长
        self.max_log_entries = 500

        # 速率限制：每分钟最多 60 次调用
        self.max_calls_per_minute = 60
        self.call_timestamps: List[float] = []

    def _default_log_path(self) -> str:
        """获取默认日志路径。"""
        import tempfile
        return os.path.join(
            tempfile.gettempdir(), 'qgis_agent_calls.log'
        )

    def is_dangerous(self, tool_name: str, params: Optional[dict] = None) -> bool:
        """
        判断工具调用是否危险。

        仅依据工具名白名单判定，不再使用易绕过、易误报的参数字符串启发式
        （例如 exec("__import__('shutil').rmtree(...)") 这类无法用字符串匹配拦截）。
        真正的拦截以工具名为准，由调用方在执行前弹窗确认。

        :param tool_name: 工具名称
        :param params: 工具参数（保留参数以兼容调用签名，当前不参与判定）
        :return: 是否危险
        """
        return tool_name in self.dangerous_operations

    def log_call(self, tool_name: str, params: Optional[dict] = None,
                 result: Optional[str] = None, duration_ms: int = 0):
        """
        记录工具调用日志。

        :param tool_name: 工具名称
        :param params: 工具参数
        :param result: 调用结果
        :param duration_ms: 执行耗时（毫秒）
        """
        entry = {
            'timestamp': datetime.now().isoformat(),
            'tool': tool_name,
            'params': self._sanitize_params(params),
            'result': result,
            'duration_ms': duration_ms,
            'is_dangerous': self.is_dangerous(tool_name, params),
        }
        self.call_log.append(entry)
        # 限制内存中日志条数，仅保留最近 max_log_entries 条
        if len(self.call_log) > self.max_log_entries:
            self.call_log = self.call_log[-self.max_log_entries:]

        # 写入日志文件
        try:
            with open(self.log_path, 'a', encoding='utf-8') as f:
                f.write(f"[{entry['timestamp']}] {tool_name} | "
                        f"dangerous={entry['is_dangerous']} | "
                        f"duration={duration_ms}ms\n")
        except Exception:
            pass

    def check_rate_limit(self) -> bool:
        """
        检查是否超过速率限制。

        :return: 是否允许调用
        """
        now = time.time()
        # 清理超过 60 秒的旧记录
        self.call_timestamps = [
            t for t in self.call_timestamps
            if now - t < 60
        ]

        if len(self.call_timestamps) >= self.max_calls_per_minute:
            return False

        self.call_timestamps.append(now)
        return True

    def _sanitize_params(self, params: Optional[dict]) -> dict:
        """
        脱敏处理参数（隐藏 API Key 等敏感信息）。

        :param params: 原始参数
        :return: 脱敏后的参数
        """
        if not params:
            return {}

        sensitive_keys = ['api_key', 'password', 'token', 'secret']
        sanitized = {}
        for key, value in params.items():
            if any(s in key.lower() for s in sensitive_keys):
                sanitized[key] = '***REDACTED***'
            elif isinstance(value, str) and len(value) > 100:
                sanitized[key] = value[:100] + '...'
            else:
                sanitized[key] = value
        return sanitized

    def get_stats(self) -> Dict:
        """
        获取调用统计。

        :return: 统计信息
        """
        total = len(self.call_log)
        dangerous = sum(1 for e in self.call_log if e.get('is_dangerous'))

        return {
            'total_calls': total,
            'dangerous_calls': dangerous,
            'calls_today': sum(
                1 for e in self.call_log
                if e['timestamp'].startswith(datetime.now().strftime('%Y-%m-%d'))
            ),
            'log_path': self.log_path,
        }


def create_safety_guard(log_path: Optional[str] = None) -> SafetyGuard:
    """
    创建安全守卫实例。

    :param log_path: 日志路径
    :return: SafetyGuard 实例
    """
    return SafetyGuard(log_path=log_path)


def confirm_dangerous_operation(tool_name: str, params: Optional[dict] = None,
                                 user_confirm: bool = False) -> dict:
    """
    确认危险操作。

    :param tool_name: 工具名称
    :param params: 工具参数
    :param user_confirm: 用户是否已确认
    :return: 操作结果
    """
    guard = SafetyGuard()

    if not guard.is_dangerous(tool_name, params):
        return {'allowed': True, 'message': '操作非危险，已允许'}

    if user_confirm:
        return {'allowed': True, 'message': '用户已确认，操作允许'}

    return {
        'allowed': False,
        'warning': f'危险操作: {tool_name}',
        'params_summary': guard._sanitize_params(params),
        'message': '请确认此操作是否安全',
    }
