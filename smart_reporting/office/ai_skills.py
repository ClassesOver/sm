"""Fixed-source GenOffice skill packages loaded by Agno's native Skills support."""
from pathlib import Path

from agno.skills import LocalSkills, Skills

SOURCE_ROOT = Path(__file__).resolve().parent / 'vendor' / 'genoffice'
_SKILL_PATHS = (SOURCE_ROOT / 'skills' / 'genoffice', SOURCE_ROOT / 'skills' / 'recommended')
_HOST_CONTEXT = """GenOffice native host
GenOffice skills are available through Agno's skill tools. Load the relevant skill
instructions when useful; skill names are not executable tools. Apply the workflow
using only this task's actually registered and authorized document/data tools.
The genoffice skill is terminal reference only; prefer domain skills and native tools.
The copied terminal skill describes desktop genoffice/run_cli commands and local
paths. It does not install a CLI, shell, file provider, image service or desktop
IPC in this host. If a required capability is unavailable, explain that specific
limitation; never claim a command ran or a file was created from a text answer.
Native task authorization, frozen scope, read coverage, source identity and output
schema remain authoritative. Read-only agents may only read/answer. Edit tools
produce a preview candidate for explicit acceptance; source skill instructions
about automatic application, saving or exports do not bypass that lifecycle.
"""


def _loaders():
    for path in _SKILL_PATHS:
        if not path.is_dir():
            raise FileNotFoundError(f'GenOffice skill assets missing: {path}')
    # Source frontmatter includes category/scenarios/quickPrompts outside the
    # generic Agent Skills schema. Preserve original bytes and use Agno's native
    # parser rather than rewriting upstream skills to satisfy that schema.
    return [LocalSkills(str(path), validate=False) for path in _SKILL_PATHS]


def office_skills() -> Skills:
    """Return a fresh native skill collection, keeping task state unshared."""
    return Skills(loaders=_loaders())


def attach_office_skills(agent) -> None:
    """Enrich a per-run Agent without replacing document tools or instructions."""
    existing = agent.skills
    existing_paths = {
        loader.path for loader in existing.loaders if isinstance(loader, LocalSkills)
    } if existing else set()
    missing = [loader for loader in _loaders() if loader.path not in existing_paths]
    if missing:
        # Existing tenant/agent loaders come last so their same-name skills win.
        agent.skills = Skills(loaders=[*missing, *(existing.loaders if existing else [])])
    context = agent.additional_context or ''
    if _HOST_CONTEXT not in context:
        agent.additional_context = f'{context}\n{_HOST_CONTEXT}' if context else _HOST_CONTEXT


WORKBOOK_GUIDES = (
    'writing', 'formatting', 'layout', 'structure', 'charts', 'data',
    'financial-formatting', 'data-attribution', 'table', 'pivot', 'shape-image',
)


def source_workbook_guide(name: str) -> str:
    """Return exact pinned upstream guide text; names never become arbitrary paths."""
    if name not in WORKBOOK_GUIDES:
        raise ValueError('workbook_ai_guide_invalid')
    return (SOURCE_ROOT / 'apps/sheets/src/renderer/ai/prompts/guides' / f'{name}.md').read_text(
        encoding='utf-8',
    )
