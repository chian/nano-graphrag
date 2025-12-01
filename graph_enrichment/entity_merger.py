"""
Entity Merger
Handles entity matching and merging across papers (e.g., "dolutegravir" = "DTG")
"""

from typing import Dict, List, Tuple, Optional
from difflib import SequenceMatcher


# Common synonyms and abbreviations for biological entities
KNOWN_SYNONYMS = {
    # HIV drugs
    'dolutegravir': ['dtg', 'tivicay'],
    'lamivudine': ['3tc', 'epivir'],
    'tenofovir': ['tdf', 'taf', 'viread'],
    'emtricitabine': ['ftc', 'emtriva'],
    'efavirenz': ['efv', 'sustiva'],
    'raltegravir': ['ral', 'isentress'],

    # Common proteins
    'tumor necrosis factor': ['tnf', 'tnf-alpha', 'tnfa'],
    'interleukin': ['il'],
    'interferon': ['ifn'],

    # Add more domain-specific synonyms as needed
}


def normalize_entity_name(name: str) -> str:
    """
    Normalize entity name for comparison.

    Args:
        name: Entity name

    Returns:
        Normalized name (lowercase, stripped)
    """
    return name.strip().lower()


def calculate_similarity(name1: str, name2: str) -> float:
    """
    Calculate similarity score between two entity names.

    Args:
        name1: First entity name
        name2: Second entity name

    Returns:
        Similarity score between 0 and 1
    """
    norm1 = normalize_entity_name(name1)
    norm2 = normalize_entity_name(name2)

    # Exact match
    if norm1 == norm2:
        return 1.0

    # Check known synonyms
    for canonical, synonyms in KNOWN_SYNONYMS.items():
        all_forms = [canonical] + synonyms
        if norm1 in all_forms and norm2 in all_forms:
            return 0.95  # High confidence for known synonyms

    # Check if one is a substring of the other
    if norm1 in norm2 or norm2 in norm1:
        return 0.8

    # Check if one is an abbreviation of the other
    if is_abbreviation(norm1, norm2) or is_abbreviation(norm2, norm1):
        return 0.85

    # Use sequence matching for similar strings
    return SequenceMatcher(None, norm1, norm2).ratio()


def is_abbreviation(abbr: str, full: str) -> bool:
    """
    Check if one string is an abbreviation of another.

    Args:
        abbr: Potential abbreviation
        full: Full string

    Returns:
        True if abbr is an abbreviation of full
    """
    # Simple check: first letters match
    if len(abbr) >= 2 and len(full) >= len(abbr):
        words = full.split()
        if len(words) >= len(abbr):
            first_letters = ''.join(w[0] for w in words if w)
            if abbr == first_letters:
                return True

    return False


def find_entity_matches(
    new_entity: Dict,
    existing_entities: Dict[str, Dict],
    entity_type_match: bool = True,
    similarity_threshold: float = 0.85
) -> List[Tuple[str, float]]:
    """
    Find potential matches for a new entity in existing entities.

    Args:
        new_entity: New entity dict with 'entity_name' and 'entity_type'
        existing_entities: Dict of existing entities (name -> entity_dict)
        entity_type_match: Whether to require entity_type to match
        similarity_threshold: Minimum similarity score to consider a match

    Returns:
        List of (entity_name, similarity_score) tuples, sorted by score
    """
    new_name = new_entity['entity_name']
    new_type = new_entity.get('entity_type', '')

    matches = []

    for existing_name, existing_entity in existing_entities.items():
        # Check type if required
        if entity_type_match:
            existing_type = existing_entity.get('entity_type', '')
            if existing_type != new_type:
                continue

        # Calculate similarity
        similarity = calculate_similarity(new_name, existing_name)

        if similarity >= similarity_threshold:
            matches.append((existing_name, similarity))

    # Sort by similarity (highest first)
    matches.sort(key=lambda x: x[1], reverse=True)

    return matches


def merge_entities(
    existing_entity: Dict,
    new_entity: Dict,
    source_uuid: str
) -> Dict:
    """
    Merge a new entity into an existing entity.

    Args:
        existing_entity: Existing entity dict
        new_entity: New entity dict to merge in
        source_uuid: UUID of the paper this entity came from

    Returns:
        Merged entity dict
    """
    merged = existing_entity.copy()

    # Update importance score to the maximum
    new_importance = new_entity.get('importance_score', 0)
    existing_importance = merged.get('importance_score', 0)
    merged['importance_score'] = max(new_importance, existing_importance)

    # Combine descriptions (avoid duplication)
    new_desc = new_entity.get('description', '').strip()
    existing_desc = merged.get('description', '').strip()

    if new_desc and new_desc.lower() not in existing_desc.lower():
        if existing_desc:
            merged['description'] = f"{existing_desc} | {new_desc}"
        else:
            merged['description'] = new_desc

    # Add source chunk
    if 'source_chunks' not in merged:
        merged['source_chunks'] = []

    if 'source_chunk' in new_entity:
        merged['source_chunks'].append(new_entity['source_chunk'])

    # Track source papers via UUIDs
    if 'source_papers' not in merged:
        merged['source_papers'] = []

    if source_uuid not in merged['source_papers']:
        merged['source_papers'].append(source_uuid)

    # Track alternative names
    if 'alternative_names' not in merged:
        merged['alternative_names'] = []

    new_name = new_entity.get('entity_name', '')
    if new_name and new_name not in merged['alternative_names']:
        merged['alternative_names'].append(new_name)

    return merged


def add_synonym(canonical: str, synonym: str):
    """
    Add a synonym pair to the known synonyms dictionary.

    Args:
        canonical: Canonical form
        synonym: Synonym to add
    """
    canonical_norm = normalize_entity_name(canonical)
    synonym_norm = normalize_entity_name(synonym)

    if canonical_norm in KNOWN_SYNONYMS:
        if synonym_norm not in KNOWN_SYNONYMS[canonical_norm]:
            KNOWN_SYNONYMS[canonical_norm].append(synonym_norm)
    else:
        KNOWN_SYNONYMS[canonical_norm] = [synonym_norm]


def get_canonical_name(entity_name: str, existing_entities: Dict[str, Dict]) -> str:
    """
    Get the canonical name for an entity (handles synonyms).

    Args:
        entity_name: Entity name to look up
        existing_entities: Dict of existing entities

    Returns:
        Canonical name (or original if no match found)
    """
    norm_name = normalize_entity_name(entity_name)

    # Check if exact match exists
    for existing_name in existing_entities.keys():
        if normalize_entity_name(existing_name) == norm_name:
            return existing_name

    # Check known synonyms
    for canonical, synonyms in KNOWN_SYNONYMS.items():
        all_forms = [canonical] + synonyms
        if norm_name in all_forms:
            # Find which existing entity uses this canonical form
            for existing_name in existing_entities.keys():
                if normalize_entity_name(existing_name) in all_forms:
                    return existing_name

    return entity_name
