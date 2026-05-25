from backend.decoder import UIState, apply_event
from backend.render_markdown import render_tree_to_markdown
from tests.test_decoder import _canonical_event_list


def test_canonical_run_renders_expected_shape():
    s = UIState()
    for ev in _canonical_event_list():
        apply_event(s, ev)
    out = render_tree_to_markdown(s.tree)
    # Hand-built expected shape — update intentionally if event list changes
    assert "✓ root" in out
    assert "lead-analyst" in out
    assert "web-researcher — sub1" in out
    assert "web-researcher — sub2" in out
    # Researchers are children of lead-analyst (indented 2 spaces deeper)
    lines = out.splitlines()
    lead_line = next(i for i, l in enumerate(lines) if "lead-analyst" in l)
    sub_line = next(i for i, l in enumerate(lines) if "sub1" in l)
    assert sub_line > lead_line
    assert lines[sub_line].startswith("    ")  # deeper indent than lead
