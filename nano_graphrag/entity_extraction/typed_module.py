"""
Enhanced Entity and Relationship Extraction with Domain-Specific Types
Extends the base module to support relationship typing from domain schemas
"""

import json
from pydantic import BaseModel, Field
from typing import List, Optional, Callable
from nano_graphrag._utils import clean_str, convert_response_to_json
from nano_graphrag.entity_extraction.module import Entity

class TypedRelationship(BaseModel):
    """Relationship with explicit type from domain schema"""
    src_id: str = Field(..., description="The name of the source entity.")
    tgt_id: str = Field(..., description="The name of the target entity.")
    relation_type: str = Field(
        ...,
        description="The type of relationship from the domain schema (e.g., INHIBITS, ACTIVATES, CAUSES)"
    )
    description: str = Field(
        ...,
        description="Detailed description of the relationship between source and target.",
    )
    weight: float = Field(
        ...,
        ge=0,
        le=1,
        description="The strength/confidence of the relationship. Should be between 0 and 1.",
    )
    order: int = Field(
        ...,
        ge=1,
        le=3,
        description="The order of the relationship. 1 for direct, 2 for second-order, 3 for third-order.",
    )

    def to_dict(self):
        return {
            "src_id": clean_str(self.src_id.upper()),
            "tgt_id": clean_str(self.tgt_id.upper()),
            "relation_type": clean_str(self.relation_type.upper()),
            "description": clean_str(self.description),
            "weight": float(self.weight),
            "order": int(self.order),
        }


class DomainTypedEntityRelationshipExtractor:
    """
    Entity and relationship extractor with domain-specific typing.
    Uses LLM directly without dspy.
    """

    def __init__(
        self,
        entity_types: List[str],
        relationship_types: List[str],
        entity_type_descriptions: str,
        relationship_type_descriptions: str,
        llm_func: Callable,
        num_refine_turns: int = 1,
        self_refine: bool = True
    ):
        self.entity_types = entity_types
        self.relationship_types = relationship_types
        self.entity_type_descriptions = entity_type_descriptions
        self.relationship_type_descriptions = relationship_type_descriptions
        self.llm_func = llm_func
        self.num_refine_turns = num_refine_turns
        self.self_refine = self_refine

    async def forward(self, input_text: str):
        """Extract entities and relationships with refinement"""
        import asyncio

        # Build extraction prompt
        prompt = self._build_extraction_prompt(input_text)

        # Call LLM (assume it's async)
        response = await self.llm_func(prompt)

        print(f"\n{'='*80}")
        print("INITIAL EXTRACTION LLM RESPONSE:")
        print(f"{'='*80}")
        print(response[:2000])  # First 2000 chars
        print(f"... (total length: {len(response)} chars)")
        print(f"{'='*80}\n")

        # Parse JSON response
        result = self._parse_json_response(response)

        entities = [Entity(**e) for e in result.get("entities", [])]

        # Clamp order values to valid range (1-3) before creating relationships
        relationships_data = result.get("relationships", [])
        for r in relationships_data:
            if 'order' in r:
                r['order'] = max(1, min(3, r['order']))  # Clamp to [1, 3]
        relationships = [TypedRelationship(**r) for r in relationships_data]

        # Self-refinement loop
        if self.self_refine:
            for turn_num in range(self.num_refine_turns):
                # Critique current extraction
                critique_prompt = self._build_critique_prompt(input_text, entities, relationships)
                critique_response = await self.llm_func(critique_prompt)
                critique = self._parse_json_response(critique_response)

                # Refine based on critique
                refine_prompt = self._build_refine_prompt(input_text, entities, relationships, critique)
                refine_response = await self.llm_func(refine_prompt)

                print(f"\n{'='*80}")
                print(f"REFINEMENT TURN {turn_num + 1} LLM RESPONSE:")
                print(f"{'='*80}")
                print(refine_response[:2000])  # First 2000 chars
                print(f"... (total length: {len(refine_response)} chars)")
                print(f"{'='*80}\n")

                refined = self._parse_json_response(refine_response)

                # Use the natural keys that LLM returns
                refined_entities_data = refined.get("entities", [])
                refined_relationships_data = refined.get("relationships", [])

                print(f"    Parsed from refinement: {len(refined_entities_data)} entities, {len(refined_relationships_data)} relationships")
                print(f"    Keys in refined dict: {list(refined.keys())}")

                # Clamp importance_score to valid range [0, 1] (LLM sometimes returns values > 1)
                for e in refined_entities_data:
                    if 'importance_score' in e:
                        e['importance_score'] = max(0.0, min(1.0, e['importance_score']))

                entities = [Entity(**e) for e in refined_entities_data]

                # Clamp order values to valid range (1-3) and ensure IDs are strings
                for r in refined_relationships_data:
                    if 'order' in r:
                        r['order'] = max(1, min(3, r['order']))  # Clamp to [1, 3]
                    # Ensure src_id and tgt_id are strings (LLM sometimes returns integers)
                    if 'src_id' in r:
                        r['src_id'] = str(r['src_id'])
                    if 'tgt_id' in r:
                        r['tgt_id'] = str(r['tgt_id'])
                relationships = [TypedRelationship(**r) for r in refined_relationships_data]

        # Validate and filter entities and relationships
        entities = self._validate_entities(entities)
        relationships = self._validate_relationships(relationships)

        # Return simple dict (not dspy.Prediction)
        return type('Prediction', (), {'entities': entities, 'relationships': relationships})()

    def _validate_entities(self, entities: List[Entity]) -> List[Entity]:
        """Filter entities to only include valid entity types"""
        valid_entities = []
        invalid_count = 0
        invalid_types = set()

        for entity in entities:
            # Try exact match first
            if entity.entity_type in self.entity_types:
                valid_entities.append(entity)
            else:
                # Try case-insensitive match
                entity_type_upper = entity.entity_type.upper()
                matched = False
                for valid_type in self.entity_types:
                    if entity_type_upper == valid_type.upper():
                        # Fix the type to match schema
                        entity.entity_type = valid_type
                        valid_entities.append(entity)
                        matched = True
                        break

                if not matched:
                    invalid_count += 1
                    invalid_types.add(entity.entity_type)
                    print(f"  ⚠ Filtered entity '{entity.entity_name}' with invalid type '{entity.entity_type}'")

        if invalid_count > 0:
            print(f"\n  ⚠ WARNING: Filtered {invalid_count} entities with invalid types: {invalid_types}")
            print(f"  Valid types are: {self.entity_types}\n")

        return valid_entities

    def _validate_relationships(self, relationships: List[TypedRelationship]) -> List[TypedRelationship]:
        """Filter relationships to only include valid relationship types"""
        valid_relationships = []
        invalid_count = 0
        invalid_types = set()

        for rel in relationships:
            # Try exact match first
            if rel.relation_type in self.relationship_types:
                valid_relationships.append(rel)
            else:
                # Try case-insensitive match
                relation_type_upper = rel.relation_type.upper()
                matched = False
                for valid_type in self.relationship_types:
                    if relation_type_upper == valid_type.upper():
                        # Fix the type to match schema
                        rel.relation_type = valid_type
                        valid_relationships.append(rel)
                        matched = True
                        break

                if not matched:
                    invalid_count += 1
                    invalid_types.add(rel.relation_type)
                    print(f"  ⚠ Filtered relationship '{rel.src_id} -> {rel.tgt_id}' with invalid type '{rel.relation_type}'")

        if invalid_count > 0:
            print(f"\n  ⚠ WARNING: Filtered {invalid_count} relationships with invalid types: {invalid_types}")
            print(f"  Valid types are: {self.relationship_types}\n")

        return valid_relationships

    def _build_extraction_prompt(self, input_text: str) -> str:
        """Build prompt for entity/relationship extraction"""
        return f"""Extract entities and relationships from the following text using domain-specific types.

Given a text document and domain-specific entity and relationship types, identify all entities and relationships that match the domain schema.

ENTITY TYPES (use exactly these):
{self.entity_type_descriptions}

RELATIONSHIP TYPES (use exactly these):
{self.relationship_type_descriptions}

Entity Guidelines:
1. Each entity must match one of the provided entity_types exactly.
2. Extract only entities relevant to the domain.
3. Entity names should be atomic words/phrases from the input text.
4. Avoid duplicates and generic terms.
5. Provide comprehensive descriptions covering:
   a). Entity's role in the domain context
   b). Key domain-relevant attributes
   c). Relationships to other entities
   d). Functional significance

Relationship Guidelines:
1. Each relationship MUST use a relation_type from the provided relationship_types list.
2. Choose the most specific and accurate relationship type.
3. Include comprehensive descriptions covering:
   a). The nature of the interaction (mechanism, effect, dependency)
   b). The biological/scientific significance
   c). Conditions under which the relationship holds
   d). Evidence or basis for the relationship
4. Include direct relationships (order 1) and higher-order relationships (order 2-3).
5. The "src_id" and "tgt_id" must exactly match entity names from the extracted entities.
6. IMPORTANT: Only use relationship types from the provided 'relationship_types' list.

Examples:
- If relation_type is "INHIBITS": Drug X INHIBITS Enzyme Y by competitive binding
- If relation_type is "CAUSES": Mutation A CAUSES Loss of function in Protein B
- If relation_type is "PART_OF": Protein C PART_OF Pathway D as a rate-limiting enzyme

TEXT:
{input_text}

Extract all entities and relationships. Return JSON:
{{
  "entities": [
    {{"entity_name": "...", "entity_type": "...", "description": "...", "importance_score": 0.0-1.0}}
  ],
  "relationships": [
    {{"src_id": "...", "tgt_id": "...", "relation_type": "...", "description": "...", "weight": 0.0-1.0, "order": 1-3}}
  ]
}}"""

    def _build_critique_prompt(self, input_text: str, entities: List[Entity], relationships: List[TypedRelationship]) -> str:
        """Build prompt for critiquing extraction"""
        entities_json = json.dumps([e.to_dict() for e in entities], indent=2)
        relationships_json = json.dumps([r.to_dict() for r in relationships], indent=2)
        
        return f"""Critique domain-typed extraction for completeness and accuracy.

Critique Guidelines:
1. Verify all entities use valid types from entity_types.
2. Check that all relationships use valid types from relationship_types.
3. Assess if relationship types are chosen accurately (not generic).
4. Evaluate completeness: Are there missed entities or relationships?
5. Check for Type accuracy: Are entities and relationships correctly typed?
6. Identify any mistyped or incorrectly classified items.

TEXT:
{input_text}

CURRENT ENTITIES:
{entities_json}

CURRENT RELATIONSHIPS:
{relationships_json}

VALID ENTITY TYPES: {', '.join(self.entity_types)}
VALID RELATIONSHIP TYPES: {', '.join(self.relationship_types)}

Provide detailed critique. Return JSON:
{{
  "entity_critique": "Detailed critique of entities: completeness, type accuracy, and descriptions.",
  "relationship_critique": "Detailed critique of relationships: completeness, type accuracy, and descriptions."
}}"""

    def _build_refine_prompt(self, input_text: str, entities: List[Entity], relationships: List[TypedRelationship], critique: dict) -> str:
        """Build prompt for refining extraction"""
        entities_json = json.dumps([e.to_dict() for e in entities], indent=2)
        relationships_json = json.dumps([r.to_dict() for r in relationships], indent=2)
        
        return f"""Refine domain-typed extraction based on critique.

Refinement Guidelines:
1. Address all points in the critiques.
2. Fix any incorrectly typed entities or relationships.
3. Add missing entities and relationships.
4. Ensure all types are from the valid lists.
5. Improve descriptions as suggested.
6. Maintain consistency between entities and relationships.

TEXT:
{input_text}

CURRENT ENTITIES:
{entities_json}

CURRENT RELATIONSHIPS:
{relationships_json}

CRITIQUE:
Entity Critique: {critique.get('entity_critique', '')}
Relationship Critique: {critique.get('relationship_critique', '')}

VALID ENTITY TYPES: {', '.join(self.entity_types)}
VALID RELATIONSHIP TYPES: {', '.join(self.relationship_types)}

Return refined extraction as JSON:
{{
  "entities": [
    {{"entity_name": "...", "entity_type": "...", "description": "...", "importance_score": 0.0-1.0}}
  ],
  "relationships": [
    {{"src_id": "...", "tgt_id": "...", "relation_type": "...", "description": "...", "weight": 0.0-1.0, "order": 1-3}}
  ]
}}"""

    def _normalize_type(self, type_value: str, valid_types: list) -> str:
        """
        Normalize a type value to match schema, handling case differences.
        Returns the normalized type if found, otherwise returns original.
        """
        if type_value in valid_types:
            return type_value

        # Try case-insensitive match
        type_upper = type_value.upper()
        for valid_type in valid_types:
            if type_upper == valid_type.upper():
                return valid_type

        return type_value  # Return original if no match

    def _parse_json_response(self, response: str) -> dict:
        """Parse JSON from LLM response using robust parser"""
        # Use the robust JSON parser from _utils that handles malformed JSON
        result = convert_response_to_json(response)

        # convert_response_to_json returns None or empty dict on failure
        if result is None or not result:
            # Debug: Print why parsing failed
            print(f"\n⚠ JSON parsing failed. Response preview: {response[:200]}...")
            # Return empty structure to avoid downstream errors
            return {"entities": [], "relationships": []}

        # Validate that entities and relationships are lists of dicts
        entities = result.get("entities", [])
        relationships = result.get("relationships", [])

        # Count before filtering
        entities_before = len(entities) if isinstance(entities, list) else 0
        relationships_before = len(relationships) if isinstance(relationships, list) else 0

        # Filter out non-dict items and normalize types
        if isinstance(entities, list):
            normalized_entities = []
            for e in entities:
                if isinstance(e, dict):
                    # Normalize entity_type to match schema
                    if 'entity_type' in e:
                        e['entity_type'] = self._normalize_type(e['entity_type'], self.entity_types)
                    normalized_entities.append(e)
            entities = normalized_entities
        else:
            entities = []

        if isinstance(relationships, list):
            normalized_relationships = []
            for r in relationships:
                if isinstance(r, dict):
                    # Normalize relation_type to match schema
                    if 'relation_type' in r:
                        r['relation_type'] = self._normalize_type(r['relation_type'], self.relationship_types)
                    normalized_relationships.append(r)
            relationships = normalized_relationships
        else:
            relationships = []

        # Debug: Report if filtering removed items
        entities_after = len(entities)
        relationships_after = len(relationships)

        if entities_before > entities_after:
            print(f"\n⚠ Filtered out {entities_before - entities_after} non-dict entities")
        if relationships_before > relationships_after:
            print(f"\n⚠ Filtered out {relationships_before - relationships_after} non-dict relationships")

        return {"entities": entities, "relationships": relationships}


def create_domain_extractor_from_schema(schema, llm_func: Callable, num_refine_turns=1, self_refine=True):
    """
    Factory function to create a DomainTypedEntityRelationshipExtractor from a domain schema.

    Args:
        schema: DomainSchema object from schema_loader
        llm_func: LLM function to call (can be async or sync)
        num_refine_turns: Number of refinement iterations
        self_refine: Whether to use self-refinement

    Returns:
        DomainTypedEntityRelationshipExtractor configured for the domain
    """
    from domain_schemas.schema_loader import SchemaLoader

    loader = SchemaLoader()

    # Get entity types
    entity_types = loader.get_entity_type_names(schema)

    # Get relationship types
    relationship_types = loader.get_relationship_type_names(schema)

    # Format descriptions
    entity_type_descriptions = loader.format_entity_types_for_prompt(schema)
    relationship_type_descriptions = loader.format_relationship_types_for_prompt(schema)

    return DomainTypedEntityRelationshipExtractor(
        entity_types=entity_types,
        relationship_types=relationship_types,
        entity_type_descriptions=entity_type_descriptions,
        relationship_type_descriptions=relationship_type_descriptions,
        llm_func=llm_func,
        num_refine_turns=num_refine_turns,
        self_refine=self_refine
    )
