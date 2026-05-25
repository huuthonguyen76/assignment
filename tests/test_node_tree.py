import pytest
from backend.decoder import Node, UIState


def test_find_locates_descendant():
    root = Node(id="root", role="root", title="t", status="running")
    lead = Node(id="lead", role="lead-analyst", title=None, status="running",
                parent_id="root")
    root.children.append(lead)
    r1 = Node(id="r1", role="web-researcher", title="sub1", status="queued",
              parent_id="lead")
    lead.children.append(r1)
    assert root.find("r1") is r1
    assert root.find("missing") is None


def test_uistate_initial_shape():
    s = UIState()
    assert s.tree is None
    assert s.pending_question is None
    assert s.artifacts == []
    assert s.final_artifact_id is None
