#!/usr/bin/env python
"""
Inspect the knowledge graph directly to see what data is actually stored.
"""

import asyncio
import os
import sys
from pathlib import Path

# Add the current directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

from nano_graphrag import GraphRAG
# Import the Argo Bridge functions directly
import importlib.util
spec = importlib.util.spec_from_file_location("argo_bridge", "examples/using_custom_argo_bridge_api.py")
argo_bridge_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(argo_bridge_module)
argo_bridge_llm = argo_bridge_module.argo_bridge_llm
argo_bridge_embedding = argo_bridge_module.argo_bridge_embedding


async def inspect_graph(working_dir: str):
    """Inspect the knowledge graph to see what data is actually stored."""
    
    print("INSPECTING KNOWLEDGE GRAPH")
    print("=" * 50)
    print(f"Working Directory: {working_dir}")
    print()
    
    try:
        # Initialize GraphRAG
        print("Loading GraphRAG...")
        rag = GraphRAG(working_dir=working_dir)
        
        # Get the graph storage instance
        graph_storage = rag.chunk_entity_relation_graph
        print(f"Graph storage type: {type(graph_storage).__name__}")
        
        if hasattr(graph_storage, '_graph'):
            graph = graph_storage._graph
            print(f"Graph has {graph.number_of_nodes()} nodes and {graph.number_of_edges()} edges")
            print()
            
            # Inspect node types
            print("NODE TYPES FOUND:")
            print("-" * 30)
            node_types = {}
            for node, data in graph.nodes(data=True):
                entity_type = data.get('entity_type', 'unknown')
                if entity_type not in node_types:
                    node_types[entity_type] = []
                node_types[entity_type].append(node)
            
            for entity_type, nodes in node_types.items():
                print(f"{entity_type}: {len(nodes)} nodes")
                if len(nodes) <= 10:  # Show all if 10 or fewer
                    for node in nodes[:10]:
                        print(f"  - {node}")
                else:  # Show first 10 if more
                    for node in nodes[:10]:
                        print(f"  - {node}")
                    print(f"  ... and {len(nodes) - 10} more")
                print()
            
            # Inspect relationship types
            print("RELATIONSHIP TYPES FOUND:")
            print("-" * 30)
            rel_types = {}
            for source, target, data in graph.edges(data=True):
                rel_type = data.get('relationship_name', 'unknown')
                if rel_type not in rel_types:
                    rel_types[rel_type] = []
                rel_types[rel_type].append((source, target))
            
            for rel_type, edges in rel_types.items():
                print(f"{rel_type}: {len(edges)} relationships")
                if len(edges) <= 5:  # Show all if 5 or fewer
                    for source, target in edges[:5]:
                        print(f"  - {source} -> {target}")
                else:  # Show first 5 if more
                    for source, target in edges[:5]:
                        print(f"  - {source} -> {target}")
                    print(f"  ... and {len(edges) - 5} more")
                print()
            
            # Look for specific patterns
            print("LOOKING FOR SPECIFIC PATTERNS:")
            print("-" * 30)
            
            # Look for protein-like entities
            protein_keywords = ['protein', 'IL-', 'TNF', 'Tollip', 'cytokine', 'interleukin', 'receptor']
            protein_nodes = []
            for node, data in graph.nodes(data=True):
                node_str = str(node).lower()
                desc = data.get('description', '').lower()
                if any(keyword.lower() in node_str or keyword.lower() in desc for keyword in protein_keywords):
                    protein_nodes.append((node, data))
            
            print(f"Potential protein-related nodes: {len(protein_nodes)}")
            for node, data in protein_nodes[:10]:
                print(f"  - {node} ({data.get('entity_type', 'unknown')})")
                if data.get('description'):
                    print(f"    Description: {data['description'][:100]}...")
            print()
            
            # Look for author-like entities
            author_keywords = ['author', 'researcher', 'professor', 'dr.', 'phd', 'affiliated']
            author_nodes = []
            for node, data in graph.nodes(data=True):
                node_str = str(node).lower()
                desc = data.get('description', '').lower()
                if any(keyword.lower() in node_str or keyword.lower() in desc for keyword in author_keywords):
                    author_nodes.append((node, data))
            
            print(f"Potential author-related nodes: {len(author_nodes)}")
            for node, data in author_nodes[:10]:
                print(f"  - {node} ({data.get('entity_type', 'unknown')})")
                if data.get('description'):
                    print(f"    Description: {data['description'][:100]}...")
            print()
            
            # Show some sample nodes with full data
            print("SAMPLE NODES WITH FULL DATA:")
            print("-" * 30)
            sample_count = 0
            for node, data in graph.nodes(data=True):
                if sample_count >= 5:
                    break
                print(f"Node: {node}")
                for key, value in data.items():
                    if isinstance(value, str) and len(value) > 100:
                        print(f"  {key}: {value[:100]}...")
                    else:
                        print(f"  {key}: {value}")
                print()
                sample_count += 1
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


async def main():
    """Main function."""
    working_dir = "/Users/chia/Documents/ANL_Grants/ARPA-Connie/graphrag/dustmites_example"
    await inspect_graph(working_dir)


if __name__ == "__main__":
    asyncio.run(main())
