"""Unit tests for ErrorParser — verifies Godot error format parsing."""

import pytest

from src.error_parser import ErrorParser


class TestScriptError:
    """Pattern 1: SCRIPT ERROR with multi-line at: continuation."""

    def test_script_error_with_at_line(self):
        parser = ErrorParser()
        # First line — should return None (pending)
        result = parser.feed_line(
            "SCRIPT ERROR: Invalid call. Nonexistent function 'foo' in base 'Node2D'.",
            elapsed=1.0,
        )
        assert result is None

        # Second line — continuation with "   at:"
        result = parser.feed_line(
            "   at: res://scripts/foo.gd:42 (process)",
            elapsed=1.0,
        )
        assert result is not None
        assert result.category == "SCRIPT_ERROR"
        assert result.source == "res://scripts/foo.gd"
        assert result.line == 42
        assert result.level == "error"
        assert "Invalid call" in result.message


class TestParseError:
    """Pattern 2: Parse Error (single line)."""

    def test_parse_error(self):
        parser = ErrorParser()
        result = parser.feed_line(
            'res://scripts/bar.gd:10 - Parse Error: Expected ")"',
            elapsed=2.0,
        )
        assert result is not None
        assert result.category == "PARSE_ERROR"
        assert result.source == "res://scripts/bar.gd"
        assert result.line == 10
        assert result.level == "error"
        assert 'Expected ")"' in result.message


class TestResourceError:
    """Patterns 3/4: Resource errors."""

    def test_cannot_open_file(self):
        parser = ErrorParser()
        result = parser.feed_line(
            "Cannot open file: res://missing.tscn",
            elapsed=0.5,
        )
        assert result is not None
        assert result.category == "RESOURCE_ERROR"
        assert result.source == "res://missing.tscn"
        assert result.level == "error"

    def test_failed_to_load_resource(self):
        parser = ErrorParser()
        result = parser.feed_line(
            'Failed to load resource: "res://textures/gone.png"',
            elapsed=0.7,
        )
        assert result is not None
        assert result.category == "RESOURCE_ERROR"
        assert result.source == "res://textures/gone.png"


class TestWarning:
    """Patterns 7/8: WARNING with and without at: line."""

    def test_warning_with_at_line(self):
        parser = ErrorParser()
        result = parser.feed_line(
            "WARNING: Integer division, use float() if a float is expected.",
            elapsed=3.0,
        )
        assert result is None  # pending

        result = parser.feed_line(
            "   at: res://scripts/baz.gd:5 (ready)",
            elapsed=3.0,
        )
        assert result is not None
        assert result.level == "warning"
        assert result.source == "res://scripts/baz.gd"
        assert result.line == 5

    def test_warning_standalone(self):
        parser = ErrorParser()
        parser.feed_line(
            "WARNING: Some standalone warning.",
            elapsed=4.0,
        )
        # Feed a non-at: line to flush the pending warning
        parser.feed_line("Some normal output", elapsed=4.1)
        warnings = parser.get_warnings()
        assert len(warnings) == 1
        assert warnings[0].level == "warning"
        assert warnings[0].source == ""


class TestDeduplication:
    """Same error repeated multiple times should be deduplicated."""

    def test_duplicate_errors_counted(self):
        parser = ErrorParser()
        for _ in range(3):
            parser.feed_line(
                'res://scripts/bar.gd:10 - Parse Error: Expected ")"',
                elapsed=1.0,
            )
        errors = parser.get_errors()
        assert len(errors) == 1
        assert errors[0].count == 3


class TestErrorWithoutAt:
    """Pattern 6: ERROR: without a following at: line."""

    def test_error_standalone(self):
        parser = ErrorParser()
        parser.feed_line("ERROR: Something went wrong.", elapsed=5.0)
        # Feed a non-at: line to trigger completion
        parser.feed_line("Godot Engine v4.3.stable", elapsed=5.1)

        errors = parser.get_errors()
        assert len(errors) == 1
        assert errors[0].category == "GENERAL_ERROR"
        assert errors[0].source == ""
        assert errors[0].line == -1


class TestNormalOutput:
    """Normal print() output should not be detected as errors."""

    def test_normal_output_ignored(self):
        parser = ErrorParser()
        result = parser.feed_line("Hello from _ready()!", elapsed=0.1)
        assert result is None
        result = parser.feed_line("Score: 42", elapsed=0.2)
        assert result is None
        result = parser.feed_line("", elapsed=0.3)
        assert result is None

        assert len(parser.get_errors()) == 0
        assert len(parser.get_warnings()) == 0


class TestIgnoreShutdownMessages:
    """Godot headless shutdown noise should be silently ignored."""

    def test_ignore_resources_still_in_use(self):
        parser = ErrorParser()
        result = parser.feed_line(
            "ERROR: resources still in use at exit (run with --verbose for details)",
            elapsed=10.0,
        )
        assert result is None
        assert len(parser.get_errors()) == 0

    def test_ignore_orphan_stringname(self):
        parser = ErrorParser()
        result = parser.feed_line(
            "ERROR: orphan StringName: @GlobalScope",
            elapsed=10.0,
        )
        assert result is None
        assert len(parser.get_errors()) == 0

    def test_ignore_objectdb_leaked(self):
        parser = ErrorParser()
        result = parser.feed_line(
            "WARNING: ObjectDB instances leaked at exit (run with --verbose for details)",
            elapsed=10.0,
        )
        assert result is None
        assert len(parser.get_warnings()) == 0

    def test_ignore_leaked_instance(self):
        parser = ErrorParser()
        result = parser.feed_line(
            "Leaked instance: RenderingDevice",
            elapsed=10.0,
        )
        assert result is None
        assert len(parser.get_errors()) == 0

    def test_real_error_still_caught(self):
        """Ensure the filter doesn't suppress real errors."""
        parser = ErrorParser()
        parser.feed_line("ERROR: Something actually wrong.", elapsed=1.0)
        parser.feed_line("Some normal output", elapsed=1.1)
        assert len(parser.get_errors()) == 1


class TestFlush:
    """flush() should complete any pending multi-line error."""

    def test_flush_pending(self):
        parser = ErrorParser()
        parser.feed_line("ERROR: Pending error message.", elapsed=6.0)
        # No continuation line — flush manually
        result = parser.flush()
        assert result is not None
        assert result.category == "GENERAL_ERROR"
        assert result.message == "Pending error message."

    def test_flush_no_pending(self):
        parser = ErrorParser()
        result = parser.flush()
        assert result is None


class TestToDict:
    """ParsedError.to_dict() should produce a well-formed dict."""

    def test_to_dict(self):
        parser = ErrorParser()
        result = parser.feed_line(
            'res://scripts/bar.gd:10 - Parse Error: Expected ")"',
            elapsed=2.0,
        )
        assert result is not None
        d = result.to_dict()
        assert d["level"] == "error"
        assert d["category"] == "PARSE_ERROR"
        assert d["source"] == "res://scripts/bar.gd"
        assert d["line"] == 10
        assert d["count"] == 1
        assert isinstance(d["timestamp"], float)
