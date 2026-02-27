#!/usr/bin/env python3
"""Test the project path conversion functionality."""

from pathlib import Path
from claude_code_log.cli import convert_project_path_to_claude_dir


def test_path_conversion():
    """Test that project paths are correctly converted to ~/.claude/projects/ format."""

    # Test case 1: Regular project path
    input_path = Path("/Users/ezyang/projects/my-app")
    expected = Path.home() / ".claude" / "projects" / "Users-ezyang-projects-my-app"
    result = convert_project_path_to_claude_dir(input_path)
    print(f"Input: {input_path}")
    print(f"Expected: {expected}")
    print(f"Result: {result}")
    print(f"Match: {result == expected}")
    print()

    # Test case 2: Current directory reference
    input_path = Path(".")
    result = convert_project_path_to_claude_dir(input_path)
    print(f"Input: {input_path}")
    print(f"Resolved: {input_path.resolve()}")
    print(f"Result: {result}")
    print()

    # Test case 3: Absolute path with symlinks resolved
    input_path = Path("/Users/ezyang/Nursery/claude-code-log")
    result = convert_project_path_to_claude_dir(input_path)
    print(f"Input: {input_path}")
    print(f"Result: {result}")
    print()


if __name__ == "__main__":
    test_path_conversion()
