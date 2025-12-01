"""
Domain Schema Loader
Loads and manages domain-specific entity and relationship schemas
"""

import yaml
import os
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass

@dataclass
class EntityType:
    name: str
    description: str
    examples: List[str]

@dataclass
class RelationshipType:
    name: str
    description: str
    inverse: Optional[str]
    symmetric: bool
    examples: List[str]

@dataclass
class DomainSchema:
    domain_name: str
    domain_description: str
    entity_types: Dict[str, EntityType]
    relationship_types: Dict[str, RelationshipType]
    suitability_criteria: Dict
    contrastive_patterns: List[str]
    question_generation_focus: List[str]

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
            entity_types[entity_name] = EntityType(
                name=entity_name,
                description=entity_data.get('description', ''),
                examples=entity_data.get('examples', [])
            )

        # Parse relationship types
        relationship_types = {}
        for rel_name, rel_data in data.get('relationship_types', {}).items():
            relationship_types[rel_name] = RelationshipType(
                name=rel_name,
                description=rel_data.get('description', ''),
                inverse=rel_data.get('inverse'),
                symmetric=rel_data.get('symmetric', False),
                examples=rel_data.get('examples', [])
            )

        return DomainSchema(
            domain_name=data.get('domain_name', schema_name),
            domain_description=data.get('domain_description', ''),
            entity_types=entity_types,
            relationship_types=relationship_types,
            suitability_criteria=data.get('suitability_criteria', {}),
            contrastive_patterns=data.get('contrastive_patterns', []),
            question_generation_focus=data.get('question_generation_focus', [])
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

    def format_entity_types_for_prompt(self, schema: DomainSchema) -> str:
        """Format entity types as text for LLM prompts"""
        lines = []
        for entity_name, entity_type in schema.entity_types.items():
            lines.append(f"- {entity_name}: {entity_type.description}")
            if entity_type.examples:
                examples_str = ", ".join(entity_type.examples[:3])
                lines.append(f"  Examples: {examples_str}")
        return "\n".join(lines)

    def format_relationship_types_for_prompt(self, schema: DomainSchema) -> str:
        """Format relationship types as text for LLM prompts"""
        lines = []
        for rel_name, rel_type in schema.relationship_types.items():
            lines.append(f"- {rel_name}: {rel_type.description}")
            if rel_type.examples:
                examples_str = ", ".join(rel_type.examples[:2])
                lines.append(f"  Examples: {examples_str}")
        return "\n".join(lines)

    def get_entity_type_names(self, schema: DomainSchema) -> List[str]:
        """Get list of entity type names"""
        return list(schema.entity_types.keys())

    def get_relationship_type_names(self, schema: DomainSchema) -> List[str]:
        """Get list of relationship type names"""
        return list(schema.relationship_types.keys())

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
        print(f"Contrastive patterns: {len(schema.contrastive_patterns)}")
        print()
