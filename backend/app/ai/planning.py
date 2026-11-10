import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


_ACTION_VERBS = re.compile(
    r"\b("
    r"analy[sz]e|compare|create|design|develop|find|implement|prepare|research|review|"
    r"search|summari[sz]e|translate|write|"
    r"analisis|bandingkan|buat|cari|kembangkan|periksa|siapkan|susun|terjemahkan|tulis"
    r")\b",
    re.IGNORECASE,
)
_MULTI_STEP_CONNECTOR = re.compile(
    r"\b(and then|after that|then|also|as well as|and|dan|lalu|kemudian|setelah itu|selanjutnya|serta)\b",
    re.IGNORECASE,
)


class GoalPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: list[str] = Field(min_length=1, max_length=8)

    @field_validator("steps")
    @classmethod
    def validate_steps(cls, steps: list[str]) -> list[str]:
        normalized = [step.strip() for step in steps]
        if any(not step or len(step) > 300 for step in normalized):
            raise ValueError("Each plan step must contain 1 to 300 characters")
        return normalized


def needs_explicit_plan(goal: str) -> bool:
    if any(len(line.strip()) > 0 for line in goal.splitlines()[1:]):
        return True
    sentences = [part for part in re.split(r"[.!?;]+", goal) if part.strip()]
    return len(sentences) > 1 or (
        len(_ACTION_VERBS.findall(goal)) > 1 and _MULTI_STEP_CONNECTOR.search(goal) is not None
    )


def parse_goal_plan(content: str, *, max_steps: int) -> list[str]:
    try:
        plan = GoalPlan.model_validate_json(content)
    except (ValidationError, ValueError):
        raise ValueError("The planner returned an invalid plan") from None
    if len(plan.steps) > max_steps:
        raise ValueError("The planner exceeded the configured plan step limit")
    return plan.steps
