"""
Command handlers for GASL system.
"""

from .base import CommandHandler
from .declare import DeclareHandler
from .find import FindHandler
from .process import ProcessHandler
from .classify import ClassifyHandler
from .update import UpdateHandler
from .count import CountHandler
from .debug import DebugHandler
from .analyze import AnalyzeHandler
from .select import SelectHandler
from .set import SetHandler
from .require import RequireHandler
from .assert_handler import AssertHandler
from .on import OnHandler
from .try_catch import TryCatchHandler
from .cancel import CancelHandler

# New command categories
from .graph_nav import GraphNavHandler
from .multi_var import MultiVarHandler
from .data_transform import DataTransformHandler
from .field_calc import FieldCalcHandler
from .object_create import ObjectCreateHandler
from .pattern_analysis import PatternAnalysisHandler

__all__ = [
    "CommandHandler",
    "DeclareHandler",
    "FindHandler", 
    "ProcessHandler",
    "ClassifyHandler",
    "UpdateHandler",
    "CountHandler",
    "DebugHandler",
    "AnalyzeHandler",
    "SelectHandler",
    "SetHandler",
    "RequireHandler",
    "AssertHandler",
    "OnHandler",
    "TryCatchHandler",
    "CancelHandler",
    # New command handlers
    "GraphNavHandler",
    "MultiVarHandler",
    "DataTransformHandler",
    "FieldCalcHandler",
    "ObjectCreateHandler",
    "PatternAnalysisHandler"
]
