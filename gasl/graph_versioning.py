"""
Graph versioning system for GASL operations.

Provides automatic versioning of NetworkX graphs with disk persistence,
rollback capabilities, and human debugging interfaces.
"""

from datetime import datetime
import networkx as nx
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import pickle
import hashlib


class VersionedGraph:
    """Manages versioned NetworkX graphs with automatic versioning and disk persistence."""
    
    def __init__(self, base_graph: nx.Graph, working_dir: str):
        self.working_dir = Path(working_dir)
        self.versions_dir = self.working_dir / "graph_versions"
        self.versions_dir.mkdir(exist_ok=True)
        
        # In-memory metadata (fast access)
        self.lineage = {}  # version_id -> parent_version_id
        self.metadata = {}  # version_id -> {description, timestamp, command, hash}
        self.current_version = None
        
        # Initialize with base version
        self._initialize_base_version(base_graph)
        
        # Load existing versions if they exist
        self._load_metadata_from_disk()
    
    def _initialize_base_version(self, base_graph: nx.Graph):
        """Initialize with base graph version."""
        base_id = "v0_base"
        self.current_version = base_id
        
        # Save to disk immediately
        self._save_graph_to_disk(base_id, base_graph)
        
        # Store metadata
        self.metadata[base_id] = {
            "description": "Base graph loaded from GraphML",
            "timestamp": datetime.now().isoformat(),
            "command": "LOAD_BASE",
            "parent": None,
            "hash": self._compute_graph_hash(base_graph)
        }
        self._save_metadata_to_disk()
    
    @property
    def versions(self) -> Dict[str, Dict]:
        """Get all version metadata."""
        return self.metadata
    
    def create_version_after_command(self, command_type: str, description: str, 
                                   modified_graph: nx.Graph, command_details: dict = None) -> str:
        """Automatically create version after successful command execution."""
        version_num = len(self.versions) + 1
        version_id = f"v{version_num}_{command_type.lower()}"
        
        # Save graph to disk
        self._save_graph_to_disk(version_id, modified_graph)
        
        # Store metadata
        self.metadata[version_id] = {
            "description": description,
            "timestamp": datetime.now().isoformat(),
            "command": command_type,
            "parent": self.current_version,
            "hash": self._compute_graph_hash(modified_graph),
            "details": command_details or {}
        }
        
        # Update lineage
        self.lineage[version_id] = self.current_version
        self.current_version = version_id
        
        # Persist metadata
        self._save_metadata_to_disk()
        
        print(f"📝 Created version {version_id}: {description}")
        return version_id
    
    def get_current_graph(self) -> nx.Graph:
        """Get current graph (transparent to command handlers)."""
        return self._load_graph_from_disk(self.current_version)
    
    def rollback_to(self, version_id: str) -> nx.Graph:
        """Human interface: rollback to specific version."""
        if version_id not in self.metadata:
            available = list(self.metadata.keys())
            raise ValueError(f"Version {version_id} not found. Available: {available}")
        
        self.current_version = version_id
        self._save_metadata_to_disk()  # Persist the current version change
        graph = self._load_graph_from_disk(version_id)
        
        print(f"🔄 Rolled back to {version_id}: {self.metadata[version_id]['description']}")
        return graph
    
    def list_versions(self) -> List[Dict]:
        """Human interface: list all versions with details."""
        versions = []
        for version_id in sorted(self.metadata.keys(), key=lambda x: int(x.split('_')[0][1:]) if x.startswith('v') else 0):
            meta = self.metadata[version_id]
            is_current = "👉 " if version_id == self.current_version else "   "
            versions.append({
                "id": version_id,
                "description": meta["description"],
                "timestamp": meta["timestamp"],
                "command": meta["command"],
                "parent": meta["parent"],
                "is_current": version_id == self.current_version,
                "display": f"{is_current}{version_id}: {meta['description']} ({meta['command']})"
            })
        return versions
    
    def show_lineage(self) -> str:
        """Human interface: show version lineage tree."""
        def build_tree(version_id, indent=0):
            if version_id not in self.metadata:
                return ""
            
            meta = self.metadata[version_id]
            current_marker = " 👉" if version_id == self.current_version else ""
            tree = "  " * indent + f"├── {version_id}: {meta['description']}{current_marker}\n"
            
            # Find children
            children = [v for v, parent in self.lineage.items() if parent == version_id]
            for child in sorted(children, key=lambda x: int(x.split('_')[0][1:]) if x.startswith('v') else 0):
                tree += build_tree(child, indent + 1)
            return tree
        
        return "Graph Version Lineage:\n" + build_tree("v0_base")
    
    def diff_versions(self, version1: str, version2: str) -> Dict:
        """Human interface: compare two versions."""
        if version1 not in self.metadata:
            raise ValueError(f"Version {version1} not found")
        if version2 not in self.metadata:
            raise ValueError(f"Version {version2} not found")
        
        graph1 = self._load_graph_from_disk(version1)
        graph2 = self._load_graph_from_disk(version2)
        
        # Compare nodes and their attributes
        nodes1 = set(graph1.nodes())
        nodes2 = set(graph2.nodes())
        
        added_nodes = nodes2 - nodes1
        removed_nodes = nodes1 - nodes2
        common_nodes = nodes1 & nodes2
        
        modified_nodes = []
        for node in common_nodes:
            attrs1 = dict(graph1.nodes[node])
            attrs2 = dict(graph2.nodes[node])
            if attrs1 != attrs2:
                # Find what changed
                added_attrs = {k: v for k, v in attrs2.items() if k not in attrs1}
                removed_attrs = {k: v for k, v in attrs1.items() if k not in attrs2}
                modified_attrs = {k: (attrs1[k], attrs2[k]) for k in attrs1 
                                if k in attrs2 and attrs1[k] != attrs2[k]}
                
                modified_nodes.append({
                    "node": node,
                    "added_attrs": added_attrs,
                    "removed_attrs": removed_attrs,
                    "modified_attrs": modified_attrs
                })
        
        return {
            "version1": version1,
            "version2": version2,
            "added_nodes": list(added_nodes),
            "removed_nodes": list(removed_nodes),
            "modified_nodes": modified_nodes,
            "summary": f"{len(added_nodes)} added, {len(removed_nodes)} removed, {len(modified_nodes)} modified nodes"
        }
    
    def get_version_stats(self) -> Dict:
        """Get statistics about all versions."""
        stats = {
            "total_versions": len(self.metadata),
            "current_version": self.current_version,
            "disk_usage": self._calculate_disk_usage(),
            "version_history": []
        }
        
        for version_id in sorted(self.metadata.keys(), key=lambda x: int(x.split('_')[0][1:]) if x.startswith('v') else 0):
            meta = self.metadata[version_id]
            try:
                graph = self._load_graph_from_disk(version_id)
                stats["version_history"].append({
                    "id": version_id,
                    "command": meta["command"],
                    "nodes": graph.number_of_nodes(),
                    "edges": graph.number_of_edges(),
                    "timestamp": meta["timestamp"]
                })
            except Exception as e:
                stats["version_history"].append({
                    "id": version_id,
                    "command": meta["command"],
                    "nodes": "error",
                    "edges": "error",
                    "timestamp": meta["timestamp"],
                    "error": str(e)
                })
        
        return stats
    
    # Private methods for disk operations
    def _save_graph_to_disk(self, version_id: str, graph: nx.Graph):
        """Save graph to disk as pickle (faster than GraphML for versioning)."""
        filepath = self.versions_dir / f"{version_id}.pkl"
        with open(filepath, 'wb') as f:
            pickle.dump(graph, f)
    
    def _load_graph_from_disk(self, version_id: str) -> nx.Graph:
        """Load graph from disk."""
        filepath = self.versions_dir / f"{version_id}.pkl"
        if not filepath.exists():
            raise FileNotFoundError(f"Version {version_id} not found on disk at {filepath}")
        
        with open(filepath, 'rb') as f:
            return pickle.load(f)
    
    def _save_metadata_to_disk(self):
        """Persist metadata to JSON."""
        metadata_file = self.versions_dir / "versions_metadata.json"
        data = {
            "current_version": self.current_version,
            "lineage": self.lineage,
            "metadata": self.metadata
        }
        with open(metadata_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def _load_metadata_from_disk(self):
        """Load metadata from disk if exists."""
        metadata_file = self.versions_dir / "versions_metadata.json"
        if metadata_file.exists():
            try:
                with open(metadata_file, 'r') as f:
                    data = json.load(f)
                self.current_version = data.get("current_version", self.current_version)
                self.lineage = data.get("lineage", {})
                # Merge existing metadata with loaded metadata
                loaded_metadata = data.get("metadata", {})
                self.metadata.update(loaded_metadata)
            except Exception as e:
                print(f"Warning: Could not load metadata from disk: {e}")
    
    def _compute_graph_hash(self, graph: nx.Graph) -> str:
        """Compute hash of graph for integrity checking."""
        try:
            # Simple hash based on nodes, edges, and attributes
            content = {
                "nodes": sorted([(n, sorted(attrs.items())) for n, attrs in graph.nodes(data=True)]),
                "edges": sorted([(u, v, sorted(attrs.items())) for u, v, attrs in graph.edges(data=True)])
            }
            content_str = str(content)
            return hashlib.md5(content_str.encode()).hexdigest()[:8]
        except Exception:
            # Fallback hash if there are issues with sorting
            return hashlib.md5(f"{graph.number_of_nodes()}_{graph.number_of_edges()}".encode()).hexdigest()[:8]
    
    def _calculate_disk_usage(self) -> str:
        """Calculate total disk usage of all versions."""
        total_bytes = 0
        try:
            for file_path in self.versions_dir.glob("*.pkl"):
                total_bytes += file_path.stat().st_size
            
            # Add metadata file
            metadata_file = self.versions_dir / "versions_metadata.json"
            if metadata_file.exists():
                total_bytes += metadata_file.stat().st_size
            
            # Convert to human readable format
            if total_bytes < 1024:
                return f"{total_bytes} B"
            elif total_bytes < 1024 * 1024:
                return f"{total_bytes / 1024:.1f} KB"
            else:
                return f"{total_bytes / (1024 * 1024):.1f} MB"
        except Exception:
            return "unknown"


class GraphVersionDebugger:
    """Human interface for debugging graph versions."""
    
    def __init__(self, versioned_graph: VersionedGraph):
        self.vg = versioned_graph
    
    def show_versions(self):
        """Pretty print all versions."""
        print("\n📚 Available Graph Versions:")
        print("=" * 80)
        for version in self.vg.list_versions():
            print(version["display"])
        print()
    
    def show_lineage(self):
        """Show version tree."""
        print(self.vg.show_lineage())
    
    def show_stats(self):
        """Show version statistics."""
        stats = self.vg.get_version_stats()
        print(f"\n📊 Graph Version Statistics:")
        print(f"Total versions: {stats['total_versions']}")
        print(f"Current version: {stats['current_version']}")
        print(f"Disk usage: {stats['disk_usage']}")
        print("\nVersion History:")
        for version in stats["version_history"]:
            if "error" not in version:
                print(f"  {version['id']}: {version['nodes']} nodes, {version['edges']} edges ({version['command']})")
            else:
                print(f"  {version['id']}: ERROR - {version['error']}")
        print()
    
    def rollback(self, version_id: str):
        """Rollback to version."""
        try:
            self.vg.rollback_to(version_id)
        except ValueError as e:
            print(f"❌ {e}")
            self.show_versions()
    
    def diff(self, v1: str, v2: str):
        """Show diff between versions."""
        try:
            diff = self.vg.diff_versions(v1, v2)
            print(f"\n🔍 Diff {v1} → {v2}:")
            print(f"Summary: {diff['summary']}")
            
            if diff['added_nodes']:
                print(f"\n➕ Added nodes ({len(diff['added_nodes'])}):")
                for node in diff['added_nodes'][:5]:  # Show first 5
                    print(f"  • {node}")
                if len(diff['added_nodes']) > 5:
                    print(f"  ... and {len(diff['added_nodes']) - 5} more")
            
            if diff['removed_nodes']:
                print(f"\n➖ Removed nodes ({len(diff['removed_nodes'])}):")
                for node in diff['removed_nodes'][:5]:  # Show first 5
                    print(f"  • {node}")
                if len(diff['removed_nodes']) > 5:
                    print(f"  ... and {len(diff['removed_nodes']) - 5} more")
            
            if diff['modified_nodes']:
                print(f"\n✏️  Modified nodes ({len(diff['modified_nodes'])}):")
                for mod in diff['modified_nodes'][:5]:  # Show first 5
                    node_id = mod['node']
                    changes = []
                    if mod['added_attrs']:
                        changes.append(f"{len(mod['added_attrs'])} new attrs")
                    if mod['removed_attrs']:
                        changes.append(f"{len(mod['removed_attrs'])} removed attrs")
                    if mod['modified_attrs']:
                        changes.append(f"{len(mod['modified_attrs'])} changed attrs")
                    
                    print(f"  • {node_id}: {', '.join(changes)}")
                    
                    # Show specific attribute changes
                    if mod['added_attrs']:
                        for attr, value in list(mod['added_attrs'].items())[:2]:
                            print(f"    + {attr}: {value}")
                    if mod['modified_attrs']:
                        for attr, (old_val, new_val) in list(mod['modified_attrs'].items())[:2]:
                            print(f"    ~ {attr}: {old_val} → {new_val}")
                
                if len(diff['modified_nodes']) > 5:
                    print(f"  ... and {len(diff['modified_nodes']) - 5} more")
            
            print()
        except ValueError as e:
            print(f"❌ {e}")
            self.show_versions()
    
    def inspect_version(self, version_id: str):
        """Inspect a specific version in detail."""
        try:
            if version_id not in self.vg.metadata:
                print(f"❌ Version {version_id} not found")
                self.show_versions()
                return
            
            meta = self.vg.metadata[version_id]
            graph = self.vg._load_graph_from_disk(version_id)
            
            print(f"\n🔍 Inspecting Version {version_id}:")
            print("=" * 60)
            print(f"Description: {meta['description']}")
            print(f"Command: {meta['command']}")
            print(f"Timestamp: {meta['timestamp']}")
            print(f"Parent: {meta['parent']}")
            print(f"Hash: {meta['hash']}")
            print(f"Nodes: {graph.number_of_nodes()}")
            print(f"Edges: {graph.number_of_edges()}")
            
            if meta.get('details'):
                print("Command Details:")
                for key, value in meta['details'].items():
                    print(f"  {key}: {value}")
            
            # Show sample nodes
            print("\nSample Nodes:")
            for i, (node_id, attrs) in enumerate(graph.nodes(data=True)):
                if i >= 3:  # Show first 3 nodes
                    break
                print(f"  {node_id}: {len(attrs)} attributes")
                for attr_key, attr_val in list(attrs.items())[:3]:  # Show first 3 attrs
                    val_str = str(attr_val)[:50] + "..." if len(str(attr_val)) > 50 else str(attr_val)
                    print(f"    {attr_key}: {val_str}")
            
            print()
        except Exception as e:
            print(f"❌ Error inspecting version: {e}")
    
    # Private methods for disk operations
    def _save_graph_to_disk(self, version_id: str, graph: nx.Graph):
        """Save graph to disk as pickle (faster than GraphML for versioning)."""
        filepath = self.versions_dir / f"{version_id}.pkl"
        try:
            with open(filepath, 'wb') as f:
                pickle.dump(graph, f)
        except Exception as e:
            raise RuntimeError(f"Failed to save version {version_id} to disk: {e}")
    
    def _load_graph_from_disk(self, version_id: str) -> nx.Graph:
        """Load graph from disk."""
        filepath = self.versions_dir / f"{version_id}.pkl"
        if not filepath.exists():
            raise FileNotFoundError(f"Version {version_id} not found on disk at {filepath}")
        
        try:
            with open(filepath, 'rb') as f:
                return pickle.load(f)
        except Exception as e:
            raise RuntimeError(f"Failed to load version {version_id} from disk: {e}")
    
    def _save_metadata_to_disk(self):
        """Persist metadata to JSON."""
        metadata_file = self.versions_dir / "versions_metadata.json"
        data = {
            "current_version": self.current_version,
            "lineage": self.lineage,
            "metadata": self.metadata
        }
        try:
            with open(metadata_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save metadata to disk: {e}")
    
    def _load_metadata_from_disk(self):
        """Load metadata from disk if exists."""
        metadata_file = self.versions_dir / "versions_metadata.json"
        if metadata_file.exists():
            try:
                with open(metadata_file, 'r') as f:
                    data = json.load(f)
                self.current_version = data.get("current_version", self.current_version)
                self.lineage = data.get("lineage", {})
                # Merge existing metadata with loaded metadata
                loaded_metadata = data.get("metadata", {})
                self.metadata.update(loaded_metadata)
            except Exception as e:
                print(f"Warning: Could not load metadata from disk: {e}")
    
    def _compute_graph_hash(self, graph: nx.Graph) -> str:
        """Compute hash of graph for integrity checking."""
        try:
            # Simple hash based on nodes, edges, and attributes
            content = {
                "nodes": sorted([(n, sorted(attrs.items())) for n, attrs in graph.nodes(data=True)]),
                "edges": sorted([(u, v, sorted(attrs.items())) for u, v, attrs in graph.edges(data=True)])
            }
            content_str = str(content)
            return hashlib.md5(content_str.encode()).hexdigest()[:8]
        except Exception:
            # Fallback hash if there are issues with sorting
            return hashlib.md5(f"{graph.number_of_nodes()}_{graph.number_of_edges()}".encode()).hexdigest()[:8]
    
    def _calculate_disk_usage(self) -> str:
        """Calculate total disk usage of all versions."""
        total_bytes = 0
        try:
            for file_path in self.versions_dir.glob("*.pkl"):
                total_bytes += file_path.stat().st_size
            
            # Add metadata file
            metadata_file = self.versions_dir / "versions_metadata.json"
            if metadata_file.exists():
                total_bytes += metadata_file.stat().st_size
            
            # Convert to human readable format
            if total_bytes < 1024:
                return f"{total_bytes} B"
            elif total_bytes < 1024 * 1024:
                return f"{total_bytes / 1024:.1f} KB"
            else:
                return f"{total_bytes / (1024 * 1024):.1f} MB"
        except Exception:
            return "unknown"
