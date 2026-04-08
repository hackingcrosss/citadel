"""Shared Azure OpenAI client factory used by website generator, email template generator, etc."""

from app.services.credential_service import get_credential


def get_client():
    """Build an AzureOpenAI client from stored credentials.

    Returns (client, deployment_name) tuple.
    """
    from openai import AzureOpenAI

    api_key = get_credential('openai', 'api_key')
    if not api_key:
        raise ValueError('OpenAI API key not configured. Go to Settings → OpenAI to add it.')

    endpoint = get_credential('openai', 'endpoint') or 'https://swedencentral.api.cognitive.microsoft.com/'
    api_version = get_credential('openai', 'api_version') or '2025-01-01-preview'
    deployment = get_credential('openai', 'deployment') or 'model-router'

    client = AzureOpenAI(
        api_version=api_version,
        azure_endpoint=endpoint,
        api_key=api_key,
    )
    return client, deployment
