"""Discover model IDs from the configured OpenAI-compatible service."""
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI


class ModelCatalogError(Exception):
    """User-facing upstream error, without credentials or raw response bodies."""


async def fetch_available_models(*, base_url: str, api_key: str, timeout: int = 20) -> list[dict[str, str]]:
    try:
        async with AsyncOpenAI(
            base_url=base_url, api_key=api_key, timeout=timeout, max_retries=0,
        ) as client:
            page = await client.models.list()
            if not isinstance(page.data, list):
                raise ModelCatalogError("模型服务返回的列表格式无效")
            models: dict[str, dict[str, str]] = {}
            async for model in page:
                model_id = getattr(model, "id", None)
                if isinstance(model_id, str) and model_id.strip():
                    models[model_id] = {"id": model_id, "owned_by": str(getattr(model, "owned_by", "") or "")}
            return sorted(models.values(), key=lambda model: model["id"].casefold())
    except APITimeoutError as exc:
        raise ModelCatalogError("获取模型列表超时，请稍后重试") from exc
    except APIConnectionError as exc:
        raise ModelCatalogError("无法连接模型服务，请检查 API URL 和网络") from exc
    except APIStatusError as exc:
        if exc.status_code in (401, 403):
            message = "模型服务鉴权失败，请检查 API KEY 及其访问权限"
        elif exc.status_code in (404, 405):
            message = "该 API URL 未提供模型列表，请确认地址包含正确的 API 路径（例如 /v1）"
        elif exc.status_code == 429:
            message = "模型服务请求过于频繁，请稍后重试"
        else:
            message = f"模型服务返回错误（HTTP {exc.status_code}），请稍后重试"
        raise ModelCatalogError(message) from exc
