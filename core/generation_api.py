"""Helpers shared by image/video model probes and generation requests."""


def generation_endpoint(endpoint: str, media_type: str) -> str:
    if media_type not in {"image", "video"}:
        raise ValueError(f"Unsupported generation type: {media_type}")
    suffix = "/images/generations" if media_type == "image" else "/video/generations"
    base = (endpoint or "").strip().rstrip("/")
    if not base:
        raise ValueError("模型服务地址不能为空")
    if base.endswith(suffix):
        return base
    if base.endswith("/v1"):
        return base + suffix
    return base + "/v1" + suffix
