"""
Paper Suitability Assessment
Determines if a paper is suitable for contrastive reasoning questions in each domain
"""

import argparse
import json
import asyncio
from pathlib import Path
from typing import Dict, List, Tuple
import sys

sys.path.insert(0, str(Path(__file__).parent.absolute()))

from domain_schemas.schema_loader import SchemaLoader, DomainSchema
from gasl.llm import ArgoBridgeLLM

async def load_paper_text(paper_path: str) -> str:
    """Load paper text from file"""
    with open(paper_path, 'r', encoding='utf-8') as f:
        return f.read()

async def assess_domain_suitability(
    paper_text: str,
    schema: DomainSchema,
    llm: ArgoBridgeLLM,
    sample_size: int = 3000
) -> Dict:
    """
    Assess if paper is suitable for a specific domain schema.

    Returns:
        {
            'suitable': bool,
            'score': float (0-1),
            'reasoning': str,
            'entity_types_found': List[str],
            'relationship_types_found': List[str],
            'estimated_entity_count': int,
            'estimated_relationship_count': int
        }
    """

    # Take a sample of the paper (beginning + middle) to avoid token limits
    text_sample = paper_text[:sample_size] + "\n...\n" + paper_text[len(paper_text)//2:len(paper_text)//2 + sample_size]

    # Build assessment prompt
    prompt = f"""You are assessing whether a scientific paper is suitable for knowledge graph construction and question generation in the domain of {schema.domain_name}.

DOMAIN: {schema.domain_name}
DESCRIPTION: {schema.domain_description}

ENTITY TYPES for this domain:
{_format_entity_types(schema)}

RELATIONSHIP TYPES for this domain:
{_format_relationship_types(schema)}

SUITABILITY CRITERIA:
- Minimum {schema.suitability_criteria.get('min_entities', 5)} entities expected
- Minimum {schema.suitability_criteria.get('min_entity_types', 3)} different entity types
- Minimum {schema.suitability_criteria.get('min_relationships', 4)} relationships
- Required entity types: {', '.join(schema.suitability_criteria.get('required_entity_types', []))}

POSITIVE KEYWORDS: {', '.join(schema.suitability_criteria.get('keywords', {}).get('positive', []))}
NEGATIVE KEYWORDS: {', '.join(schema.suitability_criteria.get('keywords', {}).get('negative', []))}

PAPER TEXT (sample):
{text_sample}

TASK:
1. Analyze if this paper matches the {schema.domain_name} domain
2. Identify which entity types are present in the paper
3. Identify which relationship types are present
4. Estimate how many entities and relationships could be extracted
5. Check if the paper contains enough content for meaningful graph construction

Output your assessment as JSON:
{{
    "suitable": true/false,
    "confidence": 0.0-1.0,
    "reasoning": "Brief explanation of why suitable or not suitable",
    "entity_types_found": ["TYPE1", "TYPE2", ...],
    "relationship_types_found": ["REL1", "REL2", ...],
    "estimated_entity_count": number,
    "estimated_relationship_count": number,
    "positive_indicators": ["indicator1", "indicator2", ...],
    "negative_indicators": ["indicator1", "indicator2", ...],
    "contrastive_potential": "Description of contrastive mechanisms if present"
}}

IMPORTANT:
- suitable=true means the paper has sufficient entities, relationships, and domain relevance
- The paper does NOT need to contain multiple contrasting mechanisms itself
- It just needs to fit the entity/relationship types meaningfully
- Estimate conservatively but realistically
"""

    response = await llm.call_async(prompt)

    # Parse response
    try:
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0].strip()
        elif "```" in response:
            json_str = response.split("```")[1].split("```")[0].strip()
        else:
            # Find JSON object
            start = response.find("{")
            end = response.rfind("}")
            if start != -1 and end != -1:
                json_str = response[start:end+1]
            else:
                json_str = response

        assessment = json.loads(json_str)

        # Add schema name
        assessment['domain'] = schema.domain_name

        return assessment

    except Exception as e:
        print(f"Warning: Failed to parse assessment for {schema.domain_name}: {e}")
        print(f"Response: {response[:500]}")
        return {
            'suitable': False,
            'confidence': 0.0,
            'reasoning': f'Failed to parse assessment: {e}',
            'entity_types_found': [],
            'relationship_types_found': [],
            'estimated_entity_count': 0,
            'estimated_relationship_count': 0,
            'domain': schema.domain_name
        }

def _format_entity_types(schema: DomainSchema) -> str:
    """Format entity types for prompt"""
    lines = []
    for name, etype in schema.entity_types.items():
        lines.append(f"  {name}: {etype.description}")
    return "\n".join(lines)

def _format_relationship_types(schema: DomainSchema) -> str:
    """Format relationship types for prompt"""
    lines = []
    for name, rtype in schema.relationship_types.items():
        lines.append(f"  {name}: {rtype.description}")
    return "\n".join(lines)

async def assess_single_domain(
    paper_path: str,
    domain_name: str,
    llm: ArgoBridgeLLM,
    threshold: float = 0.6
) -> Dict:
    """
    Assess paper suitability for a single specified domain.

    Returns:
        {
            'paper_path': str,
            'domain': str,
            'suitable': bool,
            'assessment': assessment_dict
        }
    """

    print(f"\n{'='*60}")
    print(f"Assessing paper: {Path(paper_path).name}")
    print(f"Domain: {domain_name}")
    print(f"{'='*60}\n")

    # Load paper
    paper_text = await load_paper_text(paper_path)
    print(f"Paper length: {len(paper_text)} characters\n")

    # Load the specified schema
    loader = SchemaLoader()
    try:
        schema = loader.load_schema(domain_name)
    except Exception as e:
        print(f"✗ ERROR: Failed to load domain schema '{domain_name}': {e}")
        sys.exit(1)

    print(f"Assessing suitability for {schema.domain_name}...\n")

    # Assess the domain
    assessment = await assess_domain_suitability(paper_text, schema, llm)

    suitable = assessment['suitable'] and assessment.get('confidence', 0) >= threshold
    confidence = assessment.get('confidence', 0)

    print(f"{'='*60}")
    if suitable:
        print(f"✓ SUITABLE (confidence: {confidence:.2f})")
    else:
        print(f"✗ NOT SUITABLE (confidence: {confidence:.2f})")
    print(f"{'='*60}")
    print(f"Reasoning: {assessment.get('reasoning', 'N/A')}")
    print(f"Entity types found: {', '.join(assessment.get('entity_types_found', []))}")
    print(f"Relationship types found: {', '.join(assessment.get('relationship_types_found', []))}")
    print(f"Estimated entities: {assessment.get('estimated_entity_count', 0)}")
    print(f"Estimated relationships: {assessment.get('estimated_relationship_count', 0)}")
    print(f"{'='*60}\n")

    result = {
        'paper_path': paper_path,
        'domain': domain_name,
        'suitable': suitable,
        'assessment': assessment
    }

    return result


async def assess_all_domains(
    paper_path: str,
    llm: ArgoBridgeLLM,
    threshold: float = 0.6
) -> Dict[str, Dict]:
    """
    Assess paper suitability for all available domains.

    NOTE: This function is kept for backward compatibility and exploratory use.
    The pipeline uses assess_single_domain() instead.

    Returns:
        {
            'paper_path': str,
            'suitable_domains': List[str],
            'assessments': {domain_name: assessment_dict}
        }
    """

    print(f"\n{'='*60}")
    print(f"Assessing paper: {Path(paper_path).name}")
    print(f"{'='*60}\n")

    # Load paper
    paper_text = await load_paper_text(paper_path)
    print(f"Paper length: {len(paper_text)} characters\n")

    # Load all schemas
    loader = SchemaLoader()
    schemas = loader.get_all_schemas()

    print(f"Testing against {len(schemas)} domain schemas...\n")

    # Assess each domain
    assessments = {}
    for schema_name, schema in schemas.items():
        print(f"  Assessing: {schema.domain_name}...", end=" ")

        assessment = await assess_domain_suitability(paper_text, schema, llm)
        assessments[schema_name] = assessment

        suitable = assessment['suitable'] and assessment.get('confidence', 0) >= threshold
        status = "✓ SUITABLE" if suitable else "✗ Not suitable"
        confidence = assessment.get('confidence', 0)

        print(f"{status} (confidence: {confidence:.2f})")
        print(f"    Reasoning: {assessment.get('reasoning', 'N/A')[:100]}...")
        print(f"    Entities: {assessment.get('estimated_entity_count', 0)}, Relationships: {assessment.get('estimated_relationship_count', 0)}")
        print()

    # Determine suitable domains
    suitable_domains = [
        schema_name
        for schema_name, assessment in assessments.items()
        if assessment['suitable'] and assessment.get('confidence', 0) >= threshold
    ]

    result = {
        'paper_path': paper_path,
        'suitable_domains': suitable_domains,
        'assessments': assessments
    }

    print(f"{'='*60}")
    print(f"SUMMARY: {len(suitable_domains)} suitable domain(s)")
    if suitable_domains:
        print(f"Suitable domains: {', '.join(suitable_domains)}")
    else:
        print("No suitable domains found. Paper may not fit contrastive reasoning approach.")
    print(f"{'='*60}\n")

    return result

async def main(args):
    """Main assessment function"""

    llm = ArgoBridgeLLM()

    if args.domain:
        # Single domain assessment (pipeline mode)
        result = await assess_single_domain(args.paper_path, args.domain, llm, args.threshold)

        # Save results
        output_path = Path(args.output) if args.output else Path(args.paper_path).parent / f"suitability_{args.domain}.json"

        with open(output_path, 'w') as f:
            json.dump(result, f, indent=2)

        print(f"Assessment saved to: {output_path}")

        # Exit with appropriate code
        if result['suitable']:
            print(f"\n✓ Paper is suitable for {args.domain}. Proceeding to graph construction is recommended.")
            sys.exit(0)
        else:
            print(f"\n✗ Paper is not suitable for {args.domain}. Exiting.")
            sys.exit(1)

    else:
        # Multi-domain assessment (exploratory mode)
        result = await assess_all_domains(args.paper_path, llm, args.threshold)

        # Save results
        output_path = Path(args.output) if args.output else Path(args.paper_path).parent / "suitability_assessment.json"

        with open(output_path, 'w') as f:
            json.dump(result, f, indent=2)

        print(f"Assessment saved to: {output_path}")

        # Exit with appropriate code
        if result['suitable_domains']:
            print(f"\n✓ Paper is suitable for {len(result['suitable_domains'])} domain(s). Proceeding to graph construction is recommended.")
            sys.exit(0)
        else:
            print(f"\n✗ Paper is not suitable for contrastive reasoning in any domain. Exiting.")
            sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Assess if a paper is suitable for contrastive reasoning question generation"
    )
    parser.add_argument(
        "paper_path",
        type=str,
        help="Path to the paper file (text or PDF)"
    )
    parser.add_argument(
        "--domain",
        type=str,
        help="Domain to assess (e.g., molecular_biology). If not specified, tests all domains."
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Path to save assessment results (default: paper_dir/suitability_[domain].json)"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.6,
        help="Confidence threshold for suitability (0-1, default: 0.6)"
    )

    args = parser.parse_args()
    asyncio.run(main(args))
