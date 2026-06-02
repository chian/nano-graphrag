from __future__ import annotations

from domain_schemas.schema_loader import load_domain_schema


def test_low_dose_radiation_schema_loads():
    schema = load_domain_schema("low_dose_radiation_dna_damage_repair")

    assert schema.domain_name == "Low-Dose Radiation DNA Damage and Repair"
    assert len(schema.entity_types) == 10
    assert len(schema.relationship_types) == 14
    assert "SUBJECT_OR_POPULATION" in schema.entity_types
    assert "EXPOSED_TO" in schema.relationship_types
