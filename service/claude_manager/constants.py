"""
Claude Control Constants

Constants and configuration values used across the Claude manager modules.
"""

# Buffer limit: 16MB
STDIO_BUFFER_LIMIT = 16 * 1024 * 1024

# Claude execution timeout (default 30 minutes)
CLAUDE_DEFAULT_TIMEOUT = 1800

# Claude Code environment variable keys (automatically passed to sessions)
CLAUDE_ENV_KEYS = [
    # Anthropic API
    'ANTHROPIC_API_KEY',
    'ANTHROPIC_AUTH_TOKEN',
    'ANTHROPIC_MODEL',
    'ANTHROPIC_DEFAULT_SONNET_MODEL',
    'ANTHROPIC_DEFAULT_OPUS_MODEL',
    'ANTHROPIC_DEFAULT_HAIKU_MODEL',

    # Claude Code settings
    'MAX_THINKING_TOKENS',
    'BASH_DEFAULT_TIMEOUT_MS',
    'BASH_MAX_TIMEOUT_MS',
    'BASH_MAX_OUTPUT_LENGTH',

    # Disable options
    'DISABLE_AUTOUPDATER',
    'DISABLE_ERROR_REPORTING',
    'DISABLE_TELEMETRY',
    'DISABLE_COST_WARNINGS',
    'DISABLE_PROMPT_CACHING',

    # Proxy settings
    'HTTP_PROXY',
    'HTTPS_PROXY',
    'NO_PROXY',

    # AWS Bedrock
    'CLAUDE_CODE_USE_BEDROCK',
    'AWS_REGION',
    'AWS_ACCESS_KEY_ID',
    'AWS_SECRET_ACCESS_KEY',
    'AWS_BEARER_TOKEN_BEDROCK',

    # Google Vertex AI
    'CLAUDE_CODE_USE_VERTEX',
    'GOOGLE_CLOUD_PROJECT',
    'GOOGLE_CLOUD_REGION',

    # Microsoft Foundry
    'CLAUDE_CODE_USE_FOUNDRY',
    'ANTHROPIC_FOUNDRY_API_KEY',
    'ANTHROPIC_FOUNDRY_BASE_URL',
    'ANTHROPIC_FOUNDRY_RESOURCE',

    # GitHub (for git push, PR creation)
    'GITHUB_TOKEN',
    'GH_TOKEN',
    'GITHUB_USERNAME',
]
