import os

from pydantic import BaseModel, ValidationError

MODEL = os.getenv("CV_AGENT_MODEL", "claude-sonnet-5-5")
_client = None


def _get_client():
    global _client
    if _client is None:
        from anthropic import Anthropic
        _client = Anthropic()          # đọc ANTHROPIC_API_KEY từ biến môi trường
    return _client


def call_structured(model_cls: type[BaseModel], prompt: str, max_tokens: int = 4000, retries: int = 2):
    """Gọi LLM bằng tool use để ép đúng schema (không phải parse ```json bằng tay).
    Output sai schema thì gửi lại lỗi cho LLM sửa, tối đa `retries` lần."""
    tool = {
        "name": "submit",
        "description": "Nộp kết quả theo đúng schema.",
        "input_schema": model_cls.model_json_schema(),
    }
    current = prompt
    last_err = "LLM không gọi tool"
    for _ in range(retries + 1):
        resp = _get_client().messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            tools=[tool],
            tool_choice={"type": "tool", "name": "submit"},
            messages=[{"role": "user", "content": current}],
        )
        block = next((b for b in resp.content if b.type == "tool_use"), None)
        if block is None:
            continue
        try:
            return model_cls.model_validate(block.input)
        except ValidationError as e:
            last_err = str(e)
            current = prompt + f"\n\nLần trước kết quả không hợp lệ:\n{last_err}\nHãy sửa và gọi lại tool submit."
    raise RuntimeError(f"Không lấy được output hợp lệ sau {retries + 1} lần: {last_err}")
