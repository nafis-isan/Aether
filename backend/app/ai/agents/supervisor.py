from typing import Literal

AgentName = Literal["assistant", "researcher", "developer", "productivity", "document"]

AGENT_DESCRIPTIONS: dict[AgentName, str] = {
    "assistant": "General conversation and everyday help",
    "researcher": "Research planning and source synthesis when search is configured",
    "developer": "Code explanation, debugging, and software design",
    "productivity": "Tasks, priorities, and planning",
    "document": "Document and uploaded-file analysis",
}

_ROUTES: tuple[tuple[AgentName, tuple[str, ...]], ...] = (
    ("developer", ("code", "debug", "bug", "program", "function", "api", "react", "vue", "nuxt", "python")),
    ("productivity", ("task", "todo", "to-do", "priority", "schedule", "deadline", "plan my day")),
    ("researcher", ("research", "sources", "source", "compare", "latest", "search for", "find information")),
    ("document", ("document", "uploaded file", "pdf", "attachment")),
)


def select_agent(request: str) -> AgentName:
    normalized = request.casefold()
    for agent, phrases in _ROUTES:
        if any(phrase in normalized for phrase in phrases):
            return agent
    return "assistant"


def route_basis(request: str, selected: AgentName) -> str:
    normalized = request.casefold()
    for agent, phrases in _ROUTES:
        if agent == selected:
            matched = next((phrase for phrase in phrases if phrase in normalized), None)
            if matched is not None:
                return f"Matched request phrase: '{matched}'."
    return "No specialist routing phrase matched; the general assistant was selected."
