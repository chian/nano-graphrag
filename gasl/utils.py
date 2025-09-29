"""Utility functions for GASL commands."""

def normalize_string(value: str) -> str:
    """Normalize string by stripping quotes and other formatting issues."""
    if not value:
        return ""
    # Strip quotes and whitespace, then convert to lowercase for consistent comparison
    normalized = value.strip().strip('"').strip("'").lower()
    return normalized

# Backward compatibility alias
normalize_node_id = normalize_string
