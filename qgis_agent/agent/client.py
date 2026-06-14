# -*- coding: utf-8 -*-
"""
LLM 客户端抽象层

支持多 LLM 后端：OpenAI（默认）、Anthropic、Ollama。
通过 litellm 统一接口，方便切换和扩展。

核心功能：
- 普通聊天补全（纯文本回复）
- 带工具定义的聊天补全（函数调用/工具调用）
- 流式输出
"""

from typing import Optional, List, Any, Dict, Tuple
import json


class ToolCallInfo:
    """LLM 返回的工具调用信息。"""
    name: str
    args: dict
    id: str

    def __init__(self, name: str, args: dict, id: str = ''):
        self.name = name
        self.args = args
        self.id = id


class LLMClient:
    """
    LLM 客户端包装器。

    支持多种 LLM 后端：
    - OpenAI (gpt-4o, gpt-4-turbo)
    - Anthropic (claude-sonnet-4-8, claude-haiku-4-5)
    - Ollama (本地模型)
    - litellm 兼容的任意后端

    配置方式：
    通过环境变量或配置文件设置：
    - OPENAI_API_KEY: OpenAI API 密钥
    - ANTHROPIC_API_KEY: Anthropic API 密钥
    - OLLAMA_BASE_URL: Ollama 地址（默认 http://localhost:11434）
    """

    def __init__(
        self,
        model: str = 'gpt-4o',
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 8192,  # 提高到 8192，复杂任务链需要更多空间
    ):
        """
        初始化 LLM 客户端。

        :param model: 模型名称
        :param base_url: API 基础 URL（Ollama 需要设置）
        :param api_key: API 密钥
        :param temperature: 采样温度（0.0 = 确定性）
        :param max_tokens: 最大输出 token 数
        """
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def create_chat_completion(self, messages: List[dict]) -> str:
        """
        创建聊天补全请求（纯文本回复，不携带工具调用）。

        :param messages: 对话消息列表
        :return: LLM 回复文本
        """
        return self._chat(messages, tools=None)

    def create_chat_completion_with_tools(
        self,
        messages: List[dict],
        tools: List[dict],
        tool_choice: Optional[str] = None,
    ) -> Tuple[Optional[str], List[ToolCallInfo]]:
        """
        创建带工具定义的聊天补全请求。

        :param messages: 对话消息列表
        :param tools: 工具定义列表（OpenAI tools 格式）
        :param tool_choice: 工具选择策略（None / 'auto' / 'required'）
        :return: (纯文本内容, 工具调用列表)
        """
        return self._chat(messages, tools=tools, tool_choice=tool_choice)

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _chat(
        self,
        messages: List[dict],
        tools: Optional[List[dict]] = None,
        tool_choice: Optional[str] = None,
    ) -> Any:
        """
        核心聊天补全逻辑。

        :param messages: 对话消息列表
        :param tools: 工具定义列表（OpenAI tools 格式）
        :param tool_choice: 工具选择策略
        :return: 纯字符串（无工具）或 (content, tool_calls) 元组
        """
        try:
            return self._litellm_chat(messages, tools, tool_choice)
        except ImportError:
            # 仅在 litellm 未安装时回退到直接 OpenAI 调用；
            # 其余异常（认证失败、限流、参数错误等）原样抛出，由上层显示给用户
            if tools is not None:
                return self._fallback_chat_with_tools(messages, tools, tool_choice)
            return self._fallback_chat(messages)

    def _litellm_chat(
        self,
        messages: List[dict],
        tools: Optional[List[dict]],
        tool_choice: Optional[str],
    ) -> Any:
        """使用 litellm 统一接口发起请求。"""
        import litellm

        kwargs: Dict[str, Any] = {
            'model': self.model,
            'messages': messages,
            'temperature': self.temperature,
            'max_tokens': self.max_tokens,
            # 关键：显式关闭流式，防止流式解码错误
            'stream': False,
            # 超时防止服务端挂起时永久阻塞 UI
            'timeout': 60,
        }

        if self.base_url:
            kwargs['base_url'] = self.base_url
        if self.api_key:
            kwargs['api_key'] = self.api_key
        if tools:
            kwargs['tools'] = tools
        if tool_choice:
            kwargs['tool_choice'] = tool_choice

        response = litellm.completion(**kwargs)
        message = response.choices[0].message

        # 带工具调用模式（tools 非空）：无论本轮模型是否真的调用了工具，
        # 都必须返回 (content, tool_calls) 二元组，供上层统一解包。
        # 否则模型只回文本时返回裸字符串，上层 `content, tc = ...` 会按字符
        # 解包字符串而报 "too many values to unpack"。
        if tools is not None:
            tool_calls = []
            for tc in (getattr(message, 'tool_calls', None) or []):
                # 统一用 getattr 兼容对象/字典两种返回形态
                func = getattr(tc, 'function', None)
                args_str = getattr(func, 'arguments', '{}') if func else '{}'
                tc_name = getattr(func, 'name', '') if func else ''
                try:
                    args = json.loads(args_str)
                except (json.JSONDecodeError, TypeError):
                    args = {}
                tool_calls.append(ToolCallInfo(
                    name=tc_name,
                    args=args,
                    id=getattr(tc, 'id', '') or '',
                ))
            return (message.content or None, tool_calls)

        # 纯文本模式（无 tools）：返回字符串
        return message.content or ''

    def _fallback_chat(self, messages: List[dict]) -> str:
        """
        回退到直接 OpenAI API 调用（litellm 不可用时）。

        :param messages: 对话消息列表
        :return: LLM 回复文本
        """
        try:
            from openai import OpenAI

            kwargs: Dict[str, Any] = {'timeout': 60}
            if self.api_key:
                kwargs['api_key'] = self.api_key
            if self.base_url:
                kwargs['base_url'] = self.base_url

            client = OpenAI(**kwargs)
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            return response.choices[0].message.content or ''

        except ImportError:
            return '错误: 无法加载 LLM 客户端。请安装 langchain-openai 或 litellm。'

    def _fallback_chat_with_tools(
        self,
        messages: List[dict],
        tools: List[dict],
        tool_choice: Optional[str],
    ) -> Tuple[Optional[str], List[ToolCallInfo]]:
        """
        使用直接 OpenAI API 进行带工具的聊天（litellm 不可用时的回退）。
        """
        try:
            from openai import OpenAI

            kwargs: Dict[str, Any] = {'timeout': 60}
            if self.api_key:
                kwargs['api_key'] = self.api_key
            if self.base_url:
                kwargs['base_url'] = self.base_url

            client = OpenAI(**kwargs)
            params: Dict[str, Any] = {
                'model': self.model,
                'messages': messages,
                'temperature': self.temperature,
                'max_tokens': self.max_tokens,
                'tools': tools,
            }
            if tool_choice:
                params['tool_choice'] = tool_choice

            response = client.chat.completions.create(**params)
            message = response.choices[0].message

            tool_calls = []
            if message.tool_calls:
                for tc in message.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except (json.JSONDecodeError, AttributeError):
                        args = {}
                    tool_calls.append(ToolCallInfo(
                        name=tc.function.name,
                        args=args,
                        id=getattr(tc, 'id', '') or '',
                    ))
            return (message.content or None, tool_calls)

        except ImportError:
            return (None, [])

    def create_stream(self, messages: List[dict]):
        """
        创建流式聊天补全请求。

        :param messages: 对话消息列表
        :yield: 逐块返回回复文本
        """
        try:
            import litellm

            kwargs = {
                'model': self.model,
                'messages': messages,
                'temperature': self.temperature,
                'max_tokens': self.max_tokens,
                'stream': True,
            }

            if self.base_url:
                kwargs['base_url'] = self.base_url
            if self.api_key:
                kwargs['api_key'] = self.api_key

            response = litellm.completion(**kwargs)
            for chunk in response:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except ImportError:
            yield '错误: 流式输出不可用。'


def create_client(config: Optional[dict] = None) -> LLMClient:
    """
    根据配置创建 LLM 客户端。

    :param config: 配置字典
        - model: 模型名称（默认 gpt-4o）
        - base_url: API 基础 URL
        - api_key: API 密钥
        - provider: 提供商（openai/anthropic/ollama）
    :return: LLMClient 实例
    """
    if config is None:
        config = {}

    provider = config.get('provider', 'openai')
    # 不给死默认值，便于按 provider 分支补各自的默认模型
    model = config.get('model')
    api_key = config.get('api_key')
    base_url = config.get('base_url')

    # 根据提供商设置默认模型
    if provider == 'anthropic':
        model = model or 'claude-sonnet-4-8'
        if not api_key:
            import os
            api_key = os.environ.get('ANTHROPIC_API_KEY')
    elif provider == 'ollama':
        model = model or 'llama3'
        base_url = base_url or 'http://localhost:11434'
    else:  # openai (默认)
        model = model or 'gpt-4o'
        if not api_key:
            import os
            api_key = os.environ.get('OPENAI_API_KEY')

    return LLMClient(
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=config.get('temperature', 0.0),
        max_tokens=config.get('max_tokens', 8192),  # 默认也提高到 8192
    )
