# Support

## Getting Help

- **[README](README.md)** — overview and quick start
- **[AGENTS.md](AGENTS.md)** — coding standards, architecture principles, and API reference
- **[Examples](examples/)** — working examples with YAML configs

## Reporting Issues

If you encounter a bug or have a feature request:

1. Search [existing issues](https://github.com/strands-compose/bedrock-agentcore/issues) to avoid duplicates
2. Open a new issue with:
   - Clear title describing the problem
   - Steps to reproduce (for bugs)
   - Minimal `config.yaml` that reproduces the issue
   - Python version and strands-compose-agentcore version

## Security

If you discover a potential security issue, please see [SECURITY.md](SECURITY.md).

## Troubleshooting

**Import errors:**
- Install the package: `pip install strands-compose-agentcore`
- Ensure Python 3.11+ is being used

**AgentCore connection issues:**
- Verify your AWS credentials are configured
- Check that the agent runtime ARN is correct
- Ensure the `bedrock-agentcore` service is available in your region

## Related Projects

- **[strands-compose](https://github.com/strands-compose/sdk-python)** — the core declarative orchestration library
- **[strands-agents](https://github.com/strands-agents/sdk-python)** — the underlying agent SDK
- **[bedrock-agentcore](https://pypi.org/project/bedrock-agentcore/)** — AWS Bedrock AgentCore Runtime SDK
