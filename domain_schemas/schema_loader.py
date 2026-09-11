"""
Domain Schema Loader
Loads and manages domain-specific entity and relationship schemas
"""

import yaml
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field


ASSOCIATION_FIELD_KINDS = frozenset({
    "comparison_relation",
    "context_factor",
    "context_relation",
    "country_scope",
    "dose_measure",
    "dose_reproduction_relation",
    "narrow_scope",
    "numeric_value",
    "relation_term",
    "reported_scalar",
    "reproduction_measure",
    "temporal_relation",
    "temporal_scope",
})

@dataclass
class EntityType:
    name: str
    description: str
    examples: List[str]
    extraction_enabled: bool = True
    role: str = "concept"
    merge_policy: str = "canonical"
    properties: Dict[str, Any] = field(default_factory=dict)
    association_fields: List[str] = field(default_factory=list)
    association_field_kinds: Dict[str, str] = field(default_factory=dict)
    association_connector_policy: str = "none"

@dataclass
class RelationshipType:
    name: str
    description: str
    inverse: Optional[str]
    symmetric: bool
    examples: List[str]
    extraction_enabled: bool = True
    role: str = "source_reported_relationship"
    merge_policy: str = "source_local"
    properties: Dict[str, Any] = field(default_factory=dict)
    endpoints: Dict[str, List[str]] = field(default_factory=dict)

@dataclass
class DomainSchema:
    domain_name: str
    domain_description: str
    entity_types: Dict[str, EntityType]
    relationship_types: Dict[str, RelationshipType]

class SchemaLoader:
    """Load and manage domain schemas"""

    def __init__(self, schemas_dir: str = None):
        if schemas_dir is None:
            # Default to domain_schemas directory
            schemas_dir = Path(__file__).parent
        self.schemas_dir = Path(schemas_dir)
        self.schemas: Dict[str, DomainSchema] = {}
        self._load_all_schemas()

    def _load_all_schemas(self):
        """Load all YAML schema files from the schemas directory"""
        for schema_file in self.schemas_dir.glob("*.yaml"):
            if schema_file.stem == "schema_loader":
                continue  # Skip this file

            try:
                schema = self.load_schema(schema_file.stem)
                self.schemas[schema_file.stem] = schema
                print(f"✓ Loaded schema: {schema.domain_name}")
            except Exception as e:
                print(f"✗ Failed to load {schema_file.stem}: {e}")

    def load_schema(self, schema_name: str) -> DomainSchema:
        """Load a specific domain schema by name"""
        schema_path = self.schemas_dir / f"{schema_name}.yaml"

        if not schema_path.exists():
            raise FileNotFoundError(f"Schema not found: {schema_path}")

        with open(schema_path, 'r') as f:
            data = yaml.safe_load(f)

        # Parse entity types
        entity_types = {}
        for entity_name, entity_data in data.get('entity_types', {}).items():
            properties = dict(entity_data.get('properties') or {})
            association_fields = [
                str(value)
                for value in (entity_data.get('association_fields') or [])
            ]
            association_field_kinds = {
                str(key): str(value)
                for key, value in dict(
                    entity_data.get('association_field_kinds') or {}
                ).items()
            }
            if len(association_fields) != len(set(association_fields)):
                raise ValueError(
                    f"{entity_name}: association fields must be unique"
                )
            unknown_association_fields = sorted(
                set(association_fields) - set(properties)
            )
            if unknown_association_fields:
                raise ValueError(
                    f"{entity_name}: association fields are not declared "
                    f"properties: {unknown_association_fields}"
                )
            if set(association_field_kinds) != set(association_fields):
                raise ValueError(
                    f"{entity_name}: association_field_kinds must declare "
                    "exactly every association field"
                )
            unknown_association_kinds = sorted(
                set(association_field_kinds.values()) - ASSOCIATION_FIELD_KINDS
            )
            if unknown_association_kinds:
                raise ValueError(
                    f"{entity_name}: unsupported association field kinds: "
                    f"{unknown_association_kinds}"
                )
            association_connector_policy = str(
                entity_data.get('association_connector_policy') or 'none'
            )
            if association_connector_policy not in {
                'none',
                'binary_between',
                'binary_pair',
            }:
                raise ValueError(
                    f"{entity_name}: unsupported association connector policy: "
                    f"{association_connector_policy}"
                )
            entity_types[entity_name] = EntityType(
                name=entity_name,
                description=entity_data.get('description', ''),
                examples=entity_data.get('examples', []),
                extraction_enabled=bool(entity_data.get('extraction_enabled', True)),
                role=str(entity_data.get('role', 'concept')),
                merge_policy=str(entity_data.get('merge_policy', 'canonical')),
                properties=properties,
                association_fields=association_fields,
                association_field_kinds=association_field_kinds,
                association_connector_policy=association_connector_policy,
            )

        # Parse relationship types
        relationship_types = {}
        for rel_name, rel_data in data.get('relationship_types', {}).items():
            relationship_types[rel_name] = RelationshipType(
                name=rel_name,
                description=rel_data.get('description', ''),
                inverse=rel_data.get('inverse'),
                symmetric=rel_data.get('symmetric', False),
                examples=rel_data.get('examples', []),
                extraction_enabled=bool(rel_data.get('extraction_enabled', True)),
                role=str(rel_data.get('role', 'source_reported_relationship')),
                merge_policy=str(rel_data.get('merge_policy', 'source_local')),
                properties=dict(rel_data.get('properties') or {}),
                endpoints={
                    str(endpoint): [str(value) for value in (values or [])]
                    for endpoint, values in dict(rel_data.get('endpoints') or {}).items()
                },
            )

        return DomainSchema(
            domain_name=data.get('domain_name', schema_name),
            domain_description=data.get('domain_description', ''),
            entity_types=entity_types,
            relationship_types=relationship_types,
        )

    def get_schema(self, schema_name: str) -> Optional[DomainSchema]:
        """Get a loaded schema by name"""
        return self.schemas.get(schema_name)

    def list_schemas(self) -> List[str]:
        """List all available schema names"""
        return list(self.schemas.keys())

    def get_all_schemas(self) -> Dict[str, DomainSchema]:
        """Get all loaded schemas"""
        return self.schemas

    def format_entity_types_for_prompt(
        self,
        schema: DomainSchema,
        *,
        extraction_only: bool = True,
    ) -> str:
        """Format entity types as text for LLM prompts"""
        lines = []
        for entity_name, entity_type in schema.entity_types.items():
            if extraction_only and not entity_type.extraction_enabled:
                continue
            lines.append(f"- {entity_name}: {entity_type.description}")
            if entity_type.properties:
                lines.append(
                    "  Structured attributes: "
                    + ", ".join(entity_type.properties)
                )
            if entity_type.association_fields:
                lines.append(
                    "  Required association tuple: "
                    + " + ".join(entity_type.association_fields)
                )
                lines.append(
                    "  Association constraints: "
                    + ", ".join(
                        f"{field_name}={entity_type.association_field_kinds[field_name]}"
                        for field_name in entity_type.association_fields
                    )
                    + (
                        f"; connector_policy={entity_type.association_connector_policy}"
                        if entity_type.association_connector_policy != "none"
                        else ""
                    )
                )
            if entity_type.examples:
                examples_str = ", ".join(entity_type.examples[:3])
                lines.append(f"  Examples: {examples_str}")
        return "\n".join(lines)

    def format_relationship_types_for_prompt(
        self,
        schema: DomainSchema,
        *,
        extraction_only: bool = True,
    ) -> str:
        """Format relationship types as text for LLM prompts"""
        lines = []
        for rel_name, rel_type in schema.relationship_types.items():
            if extraction_only and not rel_type.extraction_enabled:
                continue
            lines.append(f"- {rel_name}: {rel_type.description}")
            if rel_type.endpoints:
                source_types = ", ".join(rel_type.endpoints.get("source", []))
                target_types = ", ".join(rel_type.endpoints.get("target", []))
                lines.append(f"  Endpoints: [{source_types}] -> [{target_types}]")
            if rel_type.properties:
                lines.append(
                    "  Structured attributes: "
                    + ", ".join(rel_type.properties)
                )
            if rel_type.examples:
                examples_str = ", ".join(rel_type.examples[:2])
                lines.append(f"  Examples: {examples_str}")
        return "\n".join(lines)

    def get_entity_type_names(
        self,
        schema: DomainSchema,
        *,
        extraction_only: bool = True,
    ) -> List[str]:
        """Get list of entity type names"""
        return [
            name
            for name, entity_type in schema.entity_types.items()
            if not extraction_only or entity_type.extraction_enabled
        ]

    def get_relationship_type_names(
        self,
        schema: DomainSchema,
        *,
        extraction_only: bool = True,
    ) -> List[str]:
        """Get list of relationship type names"""
        return [
            name
            for name, relationship_type in schema.relationship_types.items()
            if not extraction_only or relationship_type.extraction_enabled
        ]

# Global loader instance
_loader = None

def get_schema_loader() -> SchemaLoader:
    """Get or create the global schema loader"""
    global _loader
    if _loader is None:
        _loader = SchemaLoader()
    return _loader

# Convenience functions
def load_domain_schema(schema_name: str) -> DomainSchema:
    """Load a specific domain schema"""
    loader = get_schema_loader()
    schema = loader.get_schema(schema_name)
    if schema is None:
        raise ValueError(f"Schema not found: {schema_name}")
    return schema

def list_available_domains() -> List[str]:
    """List all available domain schemas"""
    loader = get_schema_loader()
    return loader.list_schemas()

if __name__ == "__main__":
    # Test the loader
    print("Testing Schema Loader\n")

    loader = SchemaLoader()

    print(f"Available domains: {loader.list_schemas()}\n")

    for schema_name in loader.list_schemas():
        schema = loader.get_schema(schema_name)
        print(f"=== {schema.domain_name} ===")
        print(f"Description: {schema.domain_description}")
        print(f"Entity types: {len(schema.entity_types)}")
        print(f"Relationship types: {len(schema.relationship_types)}")
        print()
