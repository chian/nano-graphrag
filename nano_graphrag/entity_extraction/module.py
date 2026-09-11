import dspy
from pydantic import BaseModel, Field
from typing import Any, Dict
from nano_graphrag._utils import clean_str
from nano_graphrag._utils import logger


"""
Obtained from:
https://github.com/SciPhi-AI/R2R/blob/6e958d1e451c1cb10b6fc868572659785d1091cb/r2r/providers/prompts/defaults.jsonl
"""
ENTITY_TYPES = [
    "PERSON",
    "ORGANIZATION",
    "LOCATION",
    "DATE",
    "TIME",
    "MONEY",
    "PERCENTAGE",
    "PRODUCT",
    "EVENT",
    "LANGUAGE",
    "NATIONALITY",
    "RELIGION",
    "TITLE",
    "PROFESSION",
    "ANIMAL",
    "PLANT",
    "DISEASE",
    "MEDICATION",
    "CHEMICAL",
    "MATERIAL",
    "COLOR",
    "SHAPE",
    "MEASUREMENT",
    "WEATHER",
    "NATURAL_DISASTER",
    "AWARD",
    "LAW",
    "CRIME",
    "TECHNOLOGY",
    "SOFTWARE",
    "HARDWARE",
    "VEHICLE",
    "FOOD",
    "DRINK",
    "SPORT",
    "MUSIC_GENRE",
    "INSTRUMENT",
    "ARTWORK",
    "BOOK",
    "MOVIE",
    "TV_SHOW",
    "ACADEMIC_SUBJECT",
    "SCIENTIFIC_THEORY",
    "POLITICAL_PARTY",
    "CURRENCY",
    "STOCK_SYMBOL",
    "FILE_TYPE",
    "PROGRAMMING_LANGUAGE",
    "MEDICAL_PROCEDURE",
    "CELESTIAL_BODY",
]


class Entity(BaseModel):
    entity_name: str = Field(..., description="The name of the entity.")
    entity_type: str = Field(..., description="The type of the entity.")
    description: str = Field(
        ..., description="The description of the entity, in details and comprehensive."
    )
    importance_score: float = Field(
        ...,
        ge=0,
        le=1,
        description="Importance score of the entity. Should be between 0 and 1 with 1 being the most important.",
    )
    attributes: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Source-reported structured attributes such as value, unit, interval, "
            "route, population, place, time, and analytical method."
        ),
    )
    observation_quote: str = Field(
        default="",
        description=(
            "One exact verbatim, structurally atomic source phrase that states "
            "this observation."
        ),
    )
    attribute_evidence: Dict[str, Dict[str, str]] = Field(
        default_factory=dict,
        description=(
            "Field-indexed exact source evidence. Each quote is a unique exact "
            "subphrase of the entity's observation_quote, and each nested "
            "observation_quote equals the entity anchor."
        ),
    )

    def to_dict(self):
        return {
            "entity_name": clean_str(self.entity_name.upper()),
            "entity_type": clean_str(self.entity_type.upper()),
            "description": clean_str(self.description),
            "importance_score": float(self.importance_score),
            "attributes": dict(self.attributes),
            "observation_quote": self.observation_quote,
            "attribute_evidence": {
                str(field_name): dict(binding)
                for field_name, binding in self.attribute_evidence.items()
            },
        }


class Relationship(BaseModel):
    src_id: str = Field(..., description="The name of the source entity.")
    tgt_id: str = Field(..., description="The name of the target entity.")
    description: str = Field(
        ...,
        description="The description of the relationship between the source and target entity, in details and comprehensive.",
    )
    weight: float = Field(
        ...,
        ge=0,
        le=1,
        description="The weight of the relationship. Should be between 0 and 1 with 1 being the strongest relationship.",
    )
    order: int = Field(
        ...,
        ge=1,
        le=3,
        description="The order of the relationship. 1 for direct relationships, 2 for second-order, 3 for third-order.",
    )

    def to_dict(self):
        return {
            "src_id": clean_str(self.src_id.upper()),
            "tgt_id": clean_str(self.tgt_id.upper()),
            "description": clean_str(self.description),
            "weight": float(self.weight),
            "order": int(self.order),
        }


class CombinedExtraction(dspy.Signature):
    """
    Given a text document that is potentially relevant to this activity and a list of entity types,
    identify all entities of those types from the text and all relationships among the identified entities.

    Entity Guidelines:
    1. Each entity name should be an actual atomic word from the input text.
    2. Avoid duplicates and generic terms.
    3. Make sure descriptions are detailed and comprehensive. Use multiple complete sentences for each point below:
        a). The entity's role or significance in the context
        b). Key attributes or characteristics
        c). Relationships to other entities (if applicable)
        d). Historical or cultural relevance (if applicable)
        e). Any notable actions or events associated with the entity
    4. All entity types from the text must be included.
    5. IMPORTANT: Only use entity types from the provided 'entity_types' list. Do not introduce new entity types.
    6. When extracting structured attributes, provide one exact verbatim
       observation_quote that states exactly one observation. For every
       attribute, provide attribute_evidence[field] with a quote that is one
       unique exact subphrase containing that field's literal value, plus an
       observation_quote exactly equal to the entity anchor. Do not combine
       lists, table rows, parallel claims, or multiple sentences. If a valid
       compound name or range contains "and", "or", or a numeric comma, keep
       that entire delimited phrase in one scalar attribute literal. When an
       entity type declares association fields, every field quote must contain
       each association-field literal exactly once as well as the field's own
       literal, and must not cross any other numeric claim or measure name.
       Use an explicit conventional dose or reproduction measure name; a
       reported_value association must contain a numeric literal or range.
       A schema-declared reported scalar may instead be one short qualitative
       value such as "low" or "high". Preserve exact source notation, including
       R-subscript forms, rather than normalizing it. A relation term must be a
       short literal asserted outcome, not a study aim, bare mention, or
       surrounding explanation. Include its full negation, significance,
       polarity, and modality; if no controlled full predicate is present,
       leave the analysis candidate-only. Use "and" or
       "but" between tuple sides only when that type declares the matching
       binary connector policy; never use the exception for an enumeration.
       Follow the schema-declared association constraints: narrow scopes,
       context factors, and relation terms are independently literal subphrases,
       never the full observation clause. Qualitative analysis types use their
       declared tuple and do not require an invented numeric value.

    Relationship Guidelines:
    1. Make sure relationship descriptions are detailed and comprehensive. Use multiple complete sentences for each point below:
        a). The nature of the relationship (e.g., familial, professional, causal)
        b). The impact or significance of the relationship on both entities
        c). Any historical or contextual information relevant to the relationship
        d). How the relationship evolved over time (if applicable)
        e). Any notable events or actions that resulted from this relationship
    2. Include direct relationships (order 1) as well as higher-order relationships (order 2 and 3):
        a). Direct relationships: Immediate connections between entities.
        b). Second-order relationships: Indirect effects or connections that result from direct relationships.
        c). Third-order relationships: Further indirect effects that result from second-order relationships.
    3. The "src_id" and "tgt_id" fields must exactly match entity names from the extracted entities list.
    """

    input_text: str = dspy.InputField(
        desc="The text to extract entities and relationships from."
    )
    entity_types: list[str] = dspy.InputField(
        desc="List of entity types used for extraction."
    )
    entities: list[Entity] = dspy.OutputField(
        desc="List of entities extracted from the text and the entity types."
    )
    relationships: list[Relationship] = dspy.OutputField(
        desc="List of relationships extracted from the text and the entity types."
    )


class CritiqueCombinedExtraction(dspy.Signature):
    """
    Critique the current extraction of entities and relationships from a given text.
    Focus on completeness, accuracy, and adherence to the provided entity types and extraction guidelines.

    Critique Guidelines:
    1. Evaluate if all relevant entities from the input text are captured and correctly typed.
    2. Check if entity descriptions are comprehensive and follow the provided guidelines.
    3. Assess the completeness of relationship extractions, including higher-order relationships.
    4. Verify that relationship descriptions are detailed and follow the provided guidelines.
    5. Identify any inconsistencies, errors, or missed opportunities in the current extraction.
    6. Suggest specific improvements or additions to enhance the quality of the extraction.
    """

    input_text: str = dspy.InputField(
        desc="The original text from which entities and relationships were extracted."
    )
    entity_types: list[str] = dspy.InputField(
        desc="List of valid entity types for this extraction task."
    )
    current_entities: list[Entity] = dspy.InputField(
        desc="List of currently extracted entities to be critiqued."
    )
    current_relationships: list[Relationship] = dspy.InputField(
        desc="List of currently extracted relationships to be critiqued."
    )
    entity_critique: str = dspy.OutputField(
        desc="Detailed critique of the current entities, highlighting areas for improvement for completeness and accuracy.."
    )
    relationship_critique: str = dspy.OutputField(
        desc="Detailed critique of the current relationships, highlighting areas for improvement for completeness and accuracy.."
    )


class RefineCombinedExtraction(dspy.Signature):
    """
    Refine the current extraction of entities and relationships based on the provided critique.
    Improve completeness, accuracy, and adherence to the extraction guidelines.

    Refinement Guidelines:
    1. Address all points raised in the entity and relationship critiques.
    2. Add missing entities and relationships identified in the critique.
    3. Improve entity and relationship descriptions as suggested.
    4. Ensure all refinements still adhere to the original extraction guidelines.
    5. Maintain consistency between entities and relationships during refinement.
    6. Focus on enhancing the overall quality and comprehensiveness of the extraction.
    """

    input_text: str = dspy.InputField(
        desc="The original text from which entities and relationships were extracted."
    )
    entity_types: list[str] = dspy.InputField(
        desc="List of valid entity types for this extraction task."
    )
    current_entities: list[Entity] = dspy.InputField(
        desc="List of currently extracted entities to be refined."
    )
    current_relationships: list[Relationship] = dspy.InputField(
        desc="List of currently extracted relationships to be refined."
    )
    entity_critique: str = dspy.InputField(
        desc="Detailed critique of the current entities to guide refinement."
    )
    relationship_critique: str = dspy.InputField(
        desc="Detailed critique of the current relationships to guide refinement."
    )
    refined_entities: list[Entity] = dspy.OutputField(
        desc="List of refined entities, addressing the entity critique and improving upon the current entities."
    )
    refined_relationships: list[Relationship] = dspy.OutputField(
        desc="List of refined relationships, addressing the relationship critique and improving upon the current relationships."
    )


class TypedEntityRelationshipExtractorException(dspy.Module):
    def __init__(
        self,
        predictor: dspy.Module,
        exception_types: tuple[type[Exception]] = (Exception,),
    ):
        super().__init__()
        self.predictor = predictor
        self.exception_types = exception_types

    def copy(self):
        return TypedEntityRelationshipExtractorException(self.predictor)

    def forward(self, **kwargs):
        try:
            prediction = self.predictor(**kwargs)
            return prediction

        except Exception as e:
            if isinstance(e, self.exception_types):
                return dspy.Prediction(entities=[], relationships=[])

            raise e


class TypedEntityRelationshipExtractor(dspy.Module):
    def __init__(
        self,
        lm: dspy.LM = None,
        max_retries: int = 3,
        entity_types: list[str] = ENTITY_TYPES,
        self_refine: bool = False,
        num_refine_turns: int = 1,
    ):
        super().__init__()
        self.lm = lm
        self.entity_types = entity_types
        self.self_refine = self_refine
        self.num_refine_turns = num_refine_turns

        self.extractor = dspy.ChainOfThought(
            signature=CombinedExtraction, max_retries=max_retries
        )
        self.extractor = TypedEntityRelationshipExtractorException(
            self.extractor, exception_types=(ValueError,)
        )

        if self.self_refine:
            self.critique = dspy.ChainOfThought(
                signature=CritiqueCombinedExtraction, max_retries=max_retries
            )
            self.refine = dspy.ChainOfThought(
                signature=RefineCombinedExtraction, max_retries=max_retries
            )

    def forward(self, input_text: str) -> dspy.Prediction:
        with dspy.context(lm=self.lm if self.lm is not None else dspy.settings.lm):
            extraction_result = self.extractor(
                input_text=input_text, entity_types=self.entity_types
            )

            current_entities: list[Entity] = extraction_result.entities
            current_relationships: list[Relationship] = extraction_result.relationships

            if self.self_refine:
                for _ in range(self.num_refine_turns):
                    critique_result = self.critique(
                        input_text=input_text,
                        entity_types=self.entity_types,
                        current_entities=current_entities,
                        current_relationships=current_relationships,
                    )
                    refined_result = self.refine(
                        input_text=input_text,
                        entity_types=self.entity_types,
                        current_entities=current_entities,
                        current_relationships=current_relationships,
                        entity_critique=critique_result.entity_critique,
                        relationship_critique=critique_result.relationship_critique,
                    )
                    logger.debug(
                        f"entities: {len(current_entities)} | refined_entities: {len(refined_result.refined_entities)}"
                    )
                    logger.debug(
                        f"relationships: {len(current_relationships)} | refined_relationships: {len(refined_result.refined_relationships)}"
                    )
                    current_entities = refined_result.refined_entities
                    current_relationships = refined_result.refined_relationships

        entities = [entity.to_dict() for entity in current_entities]
        relationships = [
            relationship.to_dict() for relationship in current_relationships
        ]

        return dspy.Prediction(entities=entities, relationships=relationships)
