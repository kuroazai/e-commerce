"""The smolagents wrapping, when smolagents is actually installed.

The tool functions are tested without the framework in test_agents.py. This
checks the other half: that the decorated versions carry the name, description
and argument schema smolagents needs to describe them to a model. A tool with a
missing docstring fails at agent-construction time, which is a bad place to find
out.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("smolagents")

from cardshop.agents import build_smolagent_tools  # noqa: E402

EXPECTED = {"look_up_stock", "match_listing_title", "price_card"}


def test_every_tool_is_described(stocked_inventory) -> None:
    tools = build_smolagent_tools(stocked_inventory)
    assert {tool.name for tool in tools} == EXPECTED

    for tool in tools:
        assert tool.description, f"{tool.name} has no description"
        assert tool.inputs, f"{tool.name} declares no arguments"
        for argument, schema in tool.inputs.items():
            assert schema.get("description"), f"{tool.name}.{argument} is undocumented"


def test_a_wrapped_tool_returns_the_same_answer(stocked_inventory) -> None:
    tools = {tool.name: tool for tool in build_smolagent_tools(stocked_inventory)}
    payload = json.loads(tools["look_up_stock"]("Dark Magician"))
    assert payload["total"] == 3


def test_the_title_tool_resolves_a_messy_listing(stocked_inventory) -> None:
    tools = {tool.name: tool for tool in build_smolagent_tools(stocked_inventory)}
    payload = json.loads(
        tools["match_listing_title"]("Yugioh Mirror Force MRD-138 1st Ed NM UK")
    )
    assert payload["candidates"][0]["card_name"] == "Mirror Force"
