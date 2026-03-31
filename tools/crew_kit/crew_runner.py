"""CrewAI agents, LLM factory, and task wiring."""

from __future__ import annotations

import os
from pathlib import Path

from crewai import Agent, Crew, Process, Task
from langchain_openai import ChatOpenAI

from .config import DEFAULT_CREW_MODEL, OPENROUTER_DEFAULT_BASE_URL
from .repo_tools import default_repo_tools


def _resolve_llm_credentials() -> tuple[str, str | None]:
    """
    Return (api_key, base_url).

    OpenRouter: OPENROUTER_API_KEY → default OpenRouter base URL.
    OpenAI: OPENAI_API_KEY → no custom base.
    Custom: CREW_OPENAI_BASE_URL + either key.
    """
    explicit_base = (
        os.environ.get("CREW_OPENAI_BASE_URL") or os.environ.get("OPENROUTER_BASE_URL") or ""
    ).strip()

    or_key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    oa_key = (os.environ.get("OPENAI_API_KEY") or "").strip()

    if explicit_base:
        key = or_key or oa_key
        if not key:
            raise RuntimeError(
                "CREW_OPENAI_BASE_URL is set but neither OPENROUTER_API_KEY nor OPENAI_API_KEY is set."
            )
        return key, explicit_base

    if or_key:
        return or_key, OPENROUTER_DEFAULT_BASE_URL

    if oa_key:
        return oa_key, None

    raise RuntimeError(
        "Set OPENROUTER_API_KEY (OpenRouter) or OPENAI_API_KEY (OpenAI). See docs/SPEC_KIT.md."
    )


def _prompt_path(name: str) -> Path:
    return Path(__file__).resolve().parent / "prompts" / f"{name}.md"


def load_prompt(name: str) -> str:
    p = _prompt_path(name)
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8").strip()


def make_llm(*, temperature: float = 0.2, verbose: bool = False) -> ChatOpenAI:
    """ChatOpenAI: OpenAI, OpenRouter, or custom OpenAI-compatible base_url."""
    key, base_url = _resolve_llm_credentials()
    kwargs: dict = {
        "model": DEFAULT_CREW_MODEL,
        "temperature": temperature,
        "verbose": verbose,
        "api_key": key,
    }
    if base_url:
        kwargs["base_url"] = base_url
    return ChatOpenAI(**kwargs)


def task_output_text(task: Task) -> str:
    """Normalize CrewAI task output to string."""
    out = getattr(task, "output", None)
    if out is None:
        return ""
    raw = getattr(out, "raw", None)
    if raw is not None:
        return str(raw)
    return str(out)


def build_agents(llm: ChatOpenAI, *, verbose: bool) -> tuple[Agent, Agent, Agent]:
    tools = default_repo_tools()
    architect = Agent(
        role="Software Architect",
        goal="Produce a concise architecture note aligned with the constitution and spec.",
        backstory=load_prompt("architect") or "Senior architect for Python/FastAPI/Telegram/Mini App systems.",
        llm=llm,
        verbose=verbose,
        tools=tools,
        allow_delegation=False,
    )
    implementer = Agent(
        role="Implementer",
        goal="Produce reviewable patches (diffs) and implementation notes without applying them.",
        backstory=load_prompt("implementer") or "Senior Python engineer focused on clean architecture.",
        llm=llm,
        verbose=verbose,
        tools=tools,
        allow_delegation=False,
    )
    reviewer = Agent(
        role="Code Reviewer",
        goal="Validate the proposal against spec and security basics; emit a structured PASS/FAIL verdict.",
        backstory=load_prompt("reviewer") or "Strict reviewer; ends with CREW_VERDICT block.",
        llm=llm,
        verbose=verbose,
        tools=tools,
        allow_delegation=False,
    )
    return architect, implementer, reviewer


def run_architect_crew(
    *,
    architect: Agent,
    system_context: str,
    verbose: bool,
) -> str:
    """Single-task crew: architecture note only."""
    task = Task(
        description=(
            "Using the context below, write the design note.\n\n"
            f"{system_context}\n"
        ),
        expected_output="Markdown design note with layers, risks, and out-of-scope items.",
        agent=architect,
    )
    crew = Crew(
        agents=[architect],
        tasks=[task],
        process=Process.sequential,
        verbose=verbose,
    )
    crew.kickoff()
    return task_output_text(task)


def run_implement_review_crew(
    *,
    implementer: Agent,
    reviewer: Agent,
    system_context: str,
    design_note: str,
    iteration: int,
    previous_review: str,
    pytest_log: str,
    verbose: bool,
) -> tuple[str, str]:
    """Sequential implementer then reviewer; returns (implement_text, review_text)."""
    impl_desc = (
        f"Iteration {iteration}.\n\n"
        f"{system_context}\n\n"
        "## Prior architecture note\n\n"
        f"{design_note}\n\n"
        "## Previous review feedback\n\n"
        f"{previous_review or '(none)'}\n\n"
        "## Latest pytest log (may be empty)\n\n"
        f"```text\n{pytest_log or '(none)'}\n```\n"
    )
    implement_task = Task(
        description=impl_desc,
        expected_output="Summary, proposed.diff or file blocks, rollout notes.",
        agent=implementer,
    )
    review_task = Task(
        description=(
            "Review the implementation proposal from the prior task against the spec and constitution. "
            "Follow your verdict instructions exactly."
        ),
        expected_output="Findings + ---CREW_VERDICT--- block with status PASS or FAIL.",
        agent=reviewer,
        context=[implement_task],
    )
    crew = Crew(
        agents=[implementer, reviewer],
        tasks=[implement_task, review_task],
        process=Process.sequential,
        verbose=verbose,
    )
    crew.kickoff()
    return task_output_text(implement_task), task_output_text(review_task)
