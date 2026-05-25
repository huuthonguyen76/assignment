from backend.agents.lead import LEAD_SYSTEM_PROMPT, DECOMPOSE_SCHEMA_HINT
from backend.agents.web_researcher import WEB_RESEARCHER_PROMPT
from backend.agents.data_analyst import DATA_ANALYST_PROMPT
from backend.agents.report_writer import REPORT_WRITER_PROMPT


def test_prompts_are_nonempty_strings():
    assert isinstance(LEAD_SYSTEM_PROMPT, str) and len(LEAD_SYSTEM_PROMPT) > 100
    assert "decompose" in LEAD_SYSTEM_PROMPT.lower()
    assert "ask_user" in LEAD_SYSTEM_PROMPT.lower()
    assert "subtopics" in DECOMPOSE_SCHEMA_HINT
    for p in (WEB_RESEARCHER_PROMPT, DATA_ANALYST_PROMPT, REPORT_WRITER_PROMPT):
        assert isinstance(p, str) and len(p) > 100
