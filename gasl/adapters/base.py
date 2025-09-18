"""
Base graph adapter.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from ..types import AdapterCapabilities


class GraphAdapter(ABC):
    """Base class for graph adapters."""
    
    def __init__(self, graph_instance: Any):
        self.graph = graph_instance
        self.capabilities = self._get_capabilities()
    
    @abstractmethod
    def _get_capabilities(self) -> AdapterCapabilities:
        """Get adapter capabilities."""
        pass
    
    @abstractmethod
    def find_nodes(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Find nodes matching filters."""
        pass
    
    @abstractmethod
    def find_edges(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Find edges matching filters."""
        pass
    
    @abstractmethod
    def find_paths(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Find paths matching filters."""
        pass
    
    def get_schema(self) -> Dict[str, Any]:
        """Get graph schema information."""
        return {
            "node_labels": self._get_node_labels(),
            "edge_types": self._get_edge_types(),
            "node_properties": self._get_node_properties(),
            "edge_properties": self._get_edge_properties()
        }
    
    @abstractmethod
    def _get_node_labels(self) -> List[str]:
        """Get available node labels."""
        pass
    
    @abstractmethod
    def _get_edge_types(self) -> List[str]:
        """Get available edge types."""
        pass
    
    @abstractmethod
    def _get_node_properties(self) -> List[str]:
        """Get available node properties."""
        pass
    
    @abstractmethod
    def _get_edge_properties(self) -> List[str]:
        """Get available edge properties."""
        pass
