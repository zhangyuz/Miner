import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ._log import get_logger

_logger = get_logger('Detonator.GeminiCLI')

_GEMINI_CLI_BIN = 'gemini'


@dataclass
class GeminiResult:
    success: bool
    output: str
    exit_code: int
    error: str = ''


@dataclass
class GeminiCLIConfig:
    timeout_seconds: int = 300
    working_dir: Optional[str] = None
    model: Optional[str] = None
    sandbox: bool = False
    extra_args: list[str] = field(default_factory=list)


def _find_gemini_binary() -> str:
    """Locate the gemini binary, checking NVM paths inside Docker."""
    if direct := shutil.which(_GEMINI_CLI_BIN):
        return direct

    nvm_dir = os.environ.get('NVM_DIR', os.path.expanduser('~/.nvm'))
    node_versions_dir = Path(nvm_dir) / 'versions' / 'node'
    if node_versions_dir.is_dir():
        for version_dir in sorted(node_versions_dir.iterdir(), reverse=True):
            candidate = version_dir / 'bin' / _GEMINI_CLI_BIN
            if candidate.is_file():
                return str(candidate)

    raise FileNotFoundError(
        'Gemini CLI binary not found. Ensure @google/gemini-cli is installed globally via npm.'
    )


def _validate_api_key() -> None:
    if not os.environ.get('GEMINI_API_KEY'):
        raise EnvironmentError(
            'GEMINI_API_KEY environment variable is not set. '
            'Obtain one from https://aistudio.google.com/app/apikey'
        )


def _build_env() -> dict[str, str]:
    """Build the subprocess environment with NVM paths resolved."""
    env = os.environ.copy()
    nvm_dir = env.get('NVM_DIR', os.path.expanduser('~/.nvm'))
    node_versions_dir = Path(nvm_dir) / 'versions' / 'node'
    if node_versions_dir.is_dir():
        for version_dir in sorted(node_versions_dir.iterdir(), reverse=True):
            bin_path = str(version_dir / 'bin')
            if bin_path not in env.get('PATH', ''):
                env['PATH'] = f'{bin_path}:{env.get("PATH", "")}'
            break
    return env


def run_gemini_prompt(
    prompt: str,
    config: Optional[GeminiCLIConfig] = None,
) -> GeminiResult:
    """
    Run a single prompt through Gemini CLI in non-interactive (headless) mode.
    Authentication is handled via GEMINI_API_KEY env var.
    """
    if config is None:
        config = GeminiCLIConfig()

    _validate_api_key()
    gemini_bin = _find_gemini_binary()
    _logger.info('Using Gemini CLI at: %s', gemini_bin)

    cmd = [gemini_bin, '-p', prompt]

    if config.sandbox:
        cmd.append('--sandbox')

    if config.model:
        cmd.extend(['-m', config.model])

    cmd.extend(config.extra_args)

    _logger.info('Running Gemini CLI: %s...', ' '.join(cmd[:4]))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=config.timeout_seconds,
            cwd=config.working_dir,
            env=_build_env(),
        )

        if result.returncode == 0:
            _logger.info('Gemini CLI completed successfully (%d chars output)', len(result.stdout))
            return GeminiResult(
                success=True,
                output=result.stdout.strip(),
                exit_code=0,
            )
        else:
            _logger.error('Gemini CLI failed (exit=%d): %s', result.returncode, result.stderr[:500])
            return GeminiResult(
                success=False,
                output=result.stdout.strip(),
                exit_code=result.returncode,
                error=result.stderr.strip(),
            )

    except subprocess.TimeoutExpired:
        _logger.error('Gemini CLI timed out after %ds', config.timeout_seconds)
        return GeminiResult(
            success=False,
            output='',
            exit_code=-1,
            error=f'Timed out after {config.timeout_seconds} seconds',
        )
    except FileNotFoundError as e:
        _logger.error('Gemini CLI binary not found: %s', e)
        return GeminiResult(
            success=False,
            output='',
            exit_code=-2,
            error=str(e),
        )


def run_gemini_on_file(
    filepath: str,
    instruction: str,
    config: Optional[GeminiCLIConfig] = None,
) -> GeminiResult:
    """
    Run Gemini CLI with a prompt that references a specific file.
    Useful for code review, analysis, or transformation tasks.
    """
    abs_path = os.path.abspath(filepath)
    if not os.path.isfile(abs_path):
        return GeminiResult(
            success=False,
            output='',
            exit_code=-3,
            error=f'File not found: {abs_path}',
        )

    prompt = f'{instruction}\n\nFile: {abs_path}'
    working_dir = os.path.dirname(abs_path)

    if config is None:
        config = GeminiCLIConfig()
    config.working_dir = config.working_dir or working_dir

    return run_gemini_prompt(prompt, config)


def check_gemini_cli_ready() -> dict:
    """
    Verify Gemini CLI is installed, binary is findable, and API key is set.
    Returns a status dict for health checks.
    """
    status = {
        'binary_found': False,
        'binary_path': None,
        'api_key_set': bool(os.environ.get('GEMINI_API_KEY')),
        'ready': False,
        'error': None,
    }

    try:
        binary = _find_gemini_binary()
        status['binary_found'] = True
        status['binary_path'] = binary
    except FileNotFoundError as e:
        status['error'] = str(e)
        return status

    status['ready'] = status['binary_found'] and status['api_key_set']
    if not status['api_key_set']:
        status['error'] = 'GEMINI_API_KEY not set'

    return status
