from __future__ import annotations as _annotations

from dataclasses import dataclass
from typing import Any, Callable

import pytest
from dirty_equals import IsInt, IsJson, IsStr
from inline_snapshot import snapshot
from typing_extensions import NotRequired, TypedDict

from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

try:
    from logfire.testing import CaptureLogfire
except ImportError:
    logfire_installed = False
else:
    logfire_installed = True


class SpanSummary(TypedDict):
    id: int
    message: str
    children: NotRequired[list[SpanSummary]]


@dataclass(init=False)
class LogfireSummary:
    traces: list[SpanSummary]
    attributes: dict[int, dict[str, Any]]

    def __init__(self, capfire: CaptureLogfire):
        spans = capfire.exporter.exported_spans_as_dict()
        spans.sort(key=lambda s: s['start_time'])
        self.traces = []
        span_lookup: dict[tuple[str, str], SpanSummary] = {}
        self.attributes = {}
        id_counter = 0
        for span in spans:
            tid = span['context']['trace_id'], span['context']['span_id']
            span_lookup[tid] = span_summary = SpanSummary(id=id_counter, message=span['attributes']['logfire.msg'])
            self.attributes[id_counter] = span['attributes']
            id_counter += 1
            if parent := span['parent']:
                parent_span = span_lookup[(parent['trace_id'], parent['span_id'])]
                parent_span.setdefault('children', []).append(span_summary)
            else:
                self.traces.append(span_summary)


@pytest.fixture
def get_logfire_summary(capfire: CaptureLogfire) -> Callable[[], LogfireSummary]:
    def get_summary() -> LogfireSummary:
        return LogfireSummary(capfire)

    return get_summary


@pytest.mark.skipif(not logfire_installed, reason='logfire not installed')
def test_logfire(get_logfire_summary: Callable[[], LogfireSummary], set_event_loop: None) -> None:
    my_agent = Agent(model=TestModel())

    @my_agent.tool_plain
    async def my_ret(x: int) -> str:
        return str(x + 1)

    result = my_agent.run_sync('Hello')
    assert result.data == snapshot('{"my_ret":"1"}')

    summary = get_logfire_summary()
    assert summary.traces == snapshot(
        [
            {
                'id': 0,
                'message': 'my_agent run prompt=Hello',
                'children': [
                    {'id': 1, 'message': 'preparing model and tools run_step=1'},
                    {'id': 2, 'message': 'model request -> model-structured-response'},
                    {
                        'id': 3,
                        'message': 'handle model response -> tool-return',
                        'children': [{'id': 4, 'message': "running tools=['my_ret']"}],
                    },
                    {'id': 5, 'message': 'preparing model and tools run_step=2'},
                    {'id': 6, 'message': 'model request -> model-text-response'},
                    {'id': 7, 'message': 'handle model response -> final result'},
                ],
            }
        ]
    )
    assert summary.attributes[0] == snapshot(
        {
            'code.filepath': 'agent.py',
            'code.function': 'run',
            'code.lineno': 123,
            'prompt': 'Hello',
            'agent': IsJson(
                {
                    'model': {
                        'call_tools': 'all',
                        'custom_result_text': None,
                        'custom_result_args': None,
                        'seed': 0,
                        'agent_model_function_tools': None,
                        'agent_model_allow_text_result': None,
                        'agent_model_result_tools': None,
                    },
                    'name': 'my_agent',
                    'last_run_messages': None,
                }
            ),
            'mode_selection': 'from-agent',
            'model_name': 'test-model',
            'agent_name': 'my_agent',
            'logfire.msg_template': '{agent_name} run {prompt=}',
            'logfire.msg': 'my_agent run prompt=Hello',
            'logfire.span_type': 'span',
            'all_messages': IsJson(
                [
                    {'content': 'Hello', 'timestamp': IsStr(regex=r'\d{4}-\d{2}-.+'), 'role': 'user'},
                    {
                        'calls': [{'tool_name': 'my_ret', 'args': {'args_dict': {'x': 0}}, 'tool_id': None}],
                        'timestamp': IsStr(regex=r'\d{4}-\d{2}-.+'),
                        'role': 'model-structured-response',
                    },
                    {
                        'tool_name': 'my_ret',
                        'content': '1',
                        'tool_id': None,
                        'timestamp': IsStr(regex=r'\d{4}-\d{2}-.+'),
                        'role': 'tool-return',
                    },
                    {
                        'content': '{"my_ret":"1"}',
                        'timestamp': IsStr(regex=r'\d{4}-\d{2}-.+'),
                        'role': 'model-text-response',
                    },
                ]
            ),
            'cost': IsJson({'request_tokens': None, 'response_tokens': None, 'total_tokens': None, 'details': None}),
            'logfire.json_schema': IsJson(
                {
                    'type': 'object',
                    'properties': {
                        'prompt': {},
                        'agent': {
                            'type': 'object',
                            'title': 'Agent',
                            'x-python-datatype': 'dataclass',
                            'properties': {
                                'model': {'type': 'object', 'title': 'TestModel', 'x-python-datatype': 'dataclass'}
                            },
                        },
                        'mode_selection': {},
                        'model_name': {},
                        'agent_name': {},
                        'all_messages': {
                            'type': 'array',
                            'prefixItems': [
                                {
                                    'type': 'object',
                                    'title': 'UserPrompt',
                                    'x-python-datatype': 'dataclass',
                                    'properties': {'timestamp': {'type': 'string', 'format': 'date-time'}},
                                },
                                {
                                    'type': 'object',
                                    'title': 'ModelStructuredResponse',
                                    'x-python-datatype': 'dataclass',
                                    'properties': {
                                        'calls': {
                                            'type': 'array',
                                            'items': {
                                                'type': 'object',
                                                'title': 'ToolCall',
                                                'x-python-datatype': 'dataclass',
                                                'properties': {
                                                    'args': {
                                                        'type': 'object',
                                                        'title': 'ArgsDict',
                                                        'x-python-datatype': 'dataclass',
                                                    }
                                                },
                                            },
                                        },
                                        'timestamp': {'type': 'string', 'format': 'date-time'},
                                    },
                                },
                                {
                                    'type': 'object',
                                    'title': 'ToolReturn',
                                    'x-python-datatype': 'dataclass',
                                    'properties': {'timestamp': {'type': 'string', 'format': 'date-time'}},
                                },
                                {
                                    'type': 'object',
                                    'title': 'ModelTextResponse',
                                    'x-python-datatype': 'dataclass',
                                    'properties': {'timestamp': {'type': 'string', 'format': 'date-time'}},
                                },
                            ],
                        },
                        'cost': {'type': 'object', 'title': 'Cost', 'x-python-datatype': 'dataclass'},
                    },
                }
            ),
        }
    )
    assert summary.attributes[1] == snapshot(
        {
            'code.filepath': 'agent.py',
            'code.function': 'run',
            'code.lineno': IsInt(),
            'run_step': 1,
            'logfire.msg_template': 'preparing model and tools {run_step=}',
            'logfire.span_type': 'span',
            'logfire.msg': 'preparing model and tools run_step=1',
            'logfire.json_schema': '{"type":"object","properties":{"run_step":{}}}',
        }
    )
