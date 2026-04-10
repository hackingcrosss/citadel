"""Shared OpenAI / Azure OpenAI client factory used by website generator, email template generator, etc."""

from app.services.credential_service import get_credential


def _get_float(key):
    """Read an openai credential as a float, returning None if unset or empty."""
    val = get_credential('openai', key)
    if val is None or val.strip() == '':
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _get_int(key):
    """Read an openai credential as an int, returning None if unset or empty."""
    val = get_credential('openai', key)
    if val is None or val.strip() == '':
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def get_client():
    """Build an OpenAI client from stored credentials.

    Returns (client, model_or_deployment) tuple.

    - If api_version is set to 'none', uses the standard OpenAI client
      (for non-Azure OpenAI-compatible endpoints).
    - Otherwise uses AzureOpenAI with the configured (or default) api_version.
    """
    api_key = get_credential('openai', 'api_key')
    if not api_key:
        raise ValueError('OpenAI API key not configured. Go to Settings → OpenAI to add it.')

    endpoint = get_credential('openai', 'endpoint') or 'https://swedencentral.api.cognitive.microsoft.com/'
    api_version = get_credential('openai', 'api_version')
    deployment = get_credential('openai', 'deployment') or 'model-router'

    # Client-level optional params
    client_kwargs = {}
    timeout = _get_float('timeout')
    if timeout is not None:
        client_kwargs['timeout'] = timeout
    max_retries = _get_int('max_retries')
    if max_retries is not None:
        client_kwargs['max_retries'] = max_retries

    if api_version and api_version.lower() == 'none':
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=endpoint, **client_kwargs)
    else:
        from openai import AzureOpenAI
        client = AzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version=api_version or '2025-01-01-preview',
            **client_kwargs,
        )

    return client, deployment


def completion_kwargs(*, max_tokens=None, temperature=None):
    """Build kwargs dict for chat.completions.create() from stored settings.

    Per-call values (max_tokens, temperature) are used as defaults that can be
    overridden by stored credential settings. Returns a dict ready to be
    unpacked with **.

    Stored settings (all under provider 'openai'):
      - token_param:        'max_tokens' | 'max_completion_tokens' | 'none'
      - temperature:        float 0-2
      - top_p:              float 0-1
      - frequency_penalty:  float -2 to 2
      - presence_penalty:   float -2 to 2
      - reasoning_effort:   'low' | 'medium' | 'high'
    """
    kwargs = {}

    # Token limit
    token_param = get_credential('openai', 'token_param') or 'max_tokens'
    if token_param.lower() != 'none' and max_tokens is not None:
        kwargs[token_param] = max_tokens

    # Temperature: stored value overrides per-call default
    stored_temp = _get_float('temperature')
    if stored_temp is not None:
        kwargs['temperature'] = stored_temp
    elif temperature is not None:
        kwargs['temperature'] = temperature

    # Optional completion params — only included when explicitly set
    top_p = _get_float('top_p')
    if top_p is not None:
        kwargs['top_p'] = top_p

    freq_penalty = _get_float('frequency_penalty')
    if freq_penalty is not None:
        kwargs['frequency_penalty'] = freq_penalty

    pres_penalty = _get_float('presence_penalty')
    if pres_penalty is not None:
        kwargs['presence_penalty'] = pres_penalty

    reasoning = get_credential('openai', 'reasoning_effort')
    if reasoning and reasoning.strip().lower() in ('low', 'medium', 'high'):
        kwargs['reasoning_effort'] = reasoning.strip().lower()

    return kwargs
