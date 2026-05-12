"""
semantic_analyzer.py — Semantic Analysis Phase
================================================

Performs semantic analysis on the AST produced by the parser:
  1. Type Checking — validates type compatibility
  2. Scope Management — tracks variable/function scopes
  3. Symbol Table — records identifiers and their properties
  4. Validation — checks for undefined variables, redeclarations, etc.

Output:
  - Decorated AST with type information
  - Symbol table with all declarations
  - Semantic errors and warnings
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set, Tuple
import json
import sys


# ══════════════════════════════════════════
#  TYPES
# ══════════════════════════════════════════
class VarType:
    """Basic type system for our language"""
    INT = "int"
    FLOAT = "float"
    STRING = "string"
    BOOL = "bool"
    UNKNOWN = "unknown"
    VOID = "void"


# ══════════════════════════════════════════
#  SYMBOL TABLE
# ══════════════════════════════════════════
@dataclass
class Symbol:
    """Represents a variable or function symbol"""
    name: str
    type: str
    kind: str  # 'var' or 'function'
    line: int
    scope_level: int
    value: Any = None
    is_initialized: bool = False
    
    def to_dict(self):
        return asdict(self)


@dataclass
class Scope:
    """Represents a scope level in the program"""
    level: int
    parent: Optional[Scope] = None
    symbols: Dict[str, Symbol] = field(default_factory=dict)
    
    def define(self, symbol: Symbol) -> bool:
        """Define a symbol in this scope. Returns False if already defined."""
        if symbol.name in self.symbols:
            return False
        self.symbols[symbol.name] = symbol
        return True
    
    def lookup(self, name: str) -> Optional[Symbol]:
        """Look up a symbol in this scope and parent scopes."""
        if name in self.symbols:
            return self.symbols[name]
        if self.parent:
            return self.parent.lookup(name)
        return None
    
    def lookup_local(self, name: str) -> Optional[Symbol]:
        """Look up symbol only in this scope (not parent)."""
        return self.symbols.get(name)


# ══════════════════════════════════════════
#  SEMANTIC ERROR / WARNING
# ══════════════════════════════════════════
@dataclass
class SemanticError:
    message: str
    line: int
    col: int = 0
    error_type: str = "error"  # 'error' or 'warning'
    
    def to_dict(self):
        return asdict(self)


# ══════════════════════════════════════════
#  SEMANTIC ANALYZER
# ══════════════════════════════════════════
class SemanticAnalyzer:
    """Performs semantic analysis on an AST"""
    
    def __init__(self, ast: Any = None):
        self.ast = ast
        self.global_scope = Scope(level=0)
        self.current_scope = self.global_scope
        self.errors: List[SemanticError] = []
        self.warnings: List[SemanticError] = []
        self.symbol_table: Dict[int, Dict[str, Symbol]] = {}  # scope_level -> symbols
        self.decorated_ast = None
        self.type_map: Dict[str, str] = {}  # node_id -> type
        
        # Initialize with built-in functions
        self._init_builtins()
    
    def _init_builtins(self):
        """Initialize built-in functions and types"""
        builtins = [
            Symbol("print", "function", "function", 0, 0),
            Symbol("len", "function", "function", 0, 0),
            Symbol("range", "function", "function", 0, 0),
            Symbol("int", "type", "function", 0, 0),
            Symbol("float", "type", "function", 0, 0),
            Symbol("str", "type", "function", 0, 0),
            Symbol("bool", "type", "function", 0, 0),
        ]
        for builtin in builtins:
            self.global_scope.define(builtin)

    def _infer_type(self, node: Any) -> str:
        """Infer the type of an AST node"""
        if not node or not isinstance(node, dict):
            return VarType.UNKNOWN

        kind = node.get("kind", "")

        # Literal types
        if kind == "Int":
            return VarType.INT
        elif kind == "Float":
            return VarType.FLOAT
        elif kind == "Str":
            return VarType.STRING
        elif kind == "Bool":
            return VarType.BOOL

        # Variable: look up its type
        elif kind == "Var":
            var_name = node.get("value")
            if var_name:
                sym = self.current_scope.lookup(var_name)
                if sym:
                    return sym.type
            return VarType.UNKNOWN

        # Binary operations: type checking
        elif kind == "BinOp":
            op = node.get("value", "")
            children = node.get("children", [])
            if len(children) >= 2:
                left_type = self._infer_type(children[0])
                right_type = self._infer_type(children[1])

                # Numeric ops (+, -, *, /) require numeric types
                if op in ("+", "-", "*", "/"):
                    if left_type in (VarType.INT, VarType.FLOAT) and right_type in (VarType.INT, VarType.FLOAT):
                        # Mixed int/float → float; int+int → int
                        return VarType.FLOAT if left_type == VarType.FLOAT or right_type == VarType.FLOAT else VarType.INT
                    else:
                        return VarType.UNKNOWN

                # String + string = string
                if op == "+" and left_type == VarType.STRING and right_type == VarType.STRING:
                    return VarType.STRING

            return VarType.UNKNOWN

        # Unary operations
        elif kind == "UnaryOp":
            op = node.get("value", "")
            children = node.get("children", [])
            if op == "-" and children:
                operand_type = self._infer_type(children[0])
                if operand_type in (VarType.INT, VarType.FLOAT):
                    return operand_type
            return VarType.UNKNOWN

        # Function calls
        elif kind == "Call":
            func_name = node.get("value")
            if func_name == "len":
                return VarType.INT
            elif func_name == "int":
                return VarType.INT
            elif func_name == "float":
                return VarType.FLOAT
            elif func_name == "str":
                return VarType.STRING
            return VarType.UNKNOWN

        return VarType.UNKNOWN
    
    def _infer_type(self, node: Any) -> str:
        """Infer the type of an AST node"""
        if not node or not isinstance(node, dict):
            return VarType.UNKNOWN
        
        kind = node.get("kind", "")
        
        # Literal types
        if kind == "Int":
            return VarType.INT
        elif kind == "Float":
            return VarType.FLOAT
        elif kind == "Str":
            return VarType.STRING
        elif kind == "Bool":
            return VarType.BOOL
        
        # Variable: look up its type
        elif kind == "Var":
            var_name = node.get("value")
            if var_name:
                sym = self.current_scope.lookup(var_name)
                if sym:
                    return sym.type
            return VarType.UNKNOWN
        
        # Binary operations: type checking
        elif kind == "BinOp":
            op = node.get("value", "")
            children = node.get("children", [])
            if len(children) >= 2:
                left_type = self._infer_type(children[0])
                right_type = self._infer_type(children[1])
                
                # Numeric ops (+, -, *, /) require numeric types
                if op in ("+", "-", "*", "/"):
                    if left_type in (VarType.INT, VarType.FLOAT) and right_type in (VarType.INT, VarType.FLOAT):
                        # Mixed int/float → float; int+int → int
                        return VarType.FLOAT if left_type == VarType.FLOAT or right_type == VarType.FLOAT else VarType.INT
                    else:
                        return VarType.UNKNOWN
                
                # String + string = string
                if op == "+" and left_type == VarType.STRING and right_type == VarType.STRING:
                    return VarType.STRING
            
            return VarType.UNKNOWN
        
        # Unary operations
        elif kind == "UnaryOp":
            op = node.get("value", "")
            children = node.get("children", [])
            if op == "-" and children:
                operand_type = self._infer_type(children[0])
                if operand_type in (VarType.INT, VarType.FLOAT):
                    return operand_type
            return VarType.UNKNOWN
        
        # Function calls
        elif kind == "Call":
            func_name = node.get("value")
            if func_name == "len":
                return VarType.INT
            elif func_name == "int":
                return VarType.INT
            elif func_name == "float":
                return VarType.FLOAT
            elif func_name == "str":
                return VarType.STRING
            return VarType.UNKNOWN
        
        return VarType.UNKNOWN
    
    def analyze(self, ast: Any) -> Dict[str, Any]:
        """Run semantic analysis on AST"""
        with open('debug_semantic.log', 'a') as f:
            f.write(f"analyze() called with ast={ast is not None}\n")
        
        self.ast = ast
        self.errors = []
        self.warnings = []
        
        if not ast:
            return self._make_result()
        
        # Walk the AST
        self.decorated_ast = self._analyze_node(ast)
        
        # Collect symbol table info
        self._collect_symbols()
        
        return self._make_result()
    
    def _analyze_node(self, node: Any) -> Any:
        """Recursively analyze AST nodes"""
        if not node or not isinstance(node, dict):
            return node
        
        kind = node.get("kind", "")
        with open('debug_semantic.log', 'a') as f:
            f.write(f"_analyze_node kind={kind}\n")
        
        # Route to specific analyzer based on node kind
        if kind == "Program":
            return self._analyze_program(node)
        elif kind == "Assign":
            return self._analyze_assign(node)
        elif kind == "If":
            return self._analyze_if(node)
        elif kind == "Print":
            return self._analyze_print(node)
        elif kind == "Return":
            return self._analyze_return(node)
        elif kind == "Call":
            return self._analyze_call(node)
        elif kind == "BinOp":
            return self._analyze_binop(node)
        elif kind == "Var":
            return self._analyze_var(node)
        else:
            # Generic node traversal
            return self._analyze_generic(node)
    
    def _analyze_program(self, node: Any) -> Any:
        """Analyze program node (list of statements)"""
        if "children" in node:
            node["children"] = [self._analyze_node(child) for child in node.get("children", [])]
        return node
    
    def _analyze_assign(self, node: Any) -> Any:
        """Analyze assignment: var = expr"""
        with open('debug_semantic.log', 'a') as f:
            f.write("_analyze_assign called\n")
        children = node.get("children", [])
        
        # First child should be a Var node
        if len(children) > 0:
            var_node = children[0]
            if var_node.get("kind") == "Var":
                var_name = var_node.get("value")
                current_line = node.get("line", 0)

                # Analyze RHS first to get its type
                rhs_node = children[1] if len(children) > 1 else None
                if rhs_node:
                    self._analyze_node(rhs_node)
                    rhs_type = self._infer_type(rhs_node)
                else:
                    rhs_type = VarType.UNKNOWN

                # Check if variable already declared in current scope
                existing = self.current_scope.lookup_local(var_name)
                if existing is None:
                    # First declaration — infer type from RHS
                    sym = Symbol(
                        name=var_name,
                        type=rhs_type,
                        kind="var",
                        line=current_line,
                        scope_level=self.current_scope.level,
                        is_initialized=True
                    )
                    self.current_scope.define(sym)
                    try:
                        sys.stderr.write(f"Added symbol: {var_name}\n")
                    except Exception:
                        pass
                else:
                    # Same-scope redeclaration is not allowed.
                    self.errors.append(SemanticError(
                        message=(
                            f"Redeclaration of variable: '{var_name}' in the same scope"
                            + (f" (previously declared on line {existing.line})" if existing.line else "")
                        ),
                        line=current_line,
                        error_type="error"
                    ))

                    # Type mismatch on redeclaration
                    if rhs_type != VarType.UNKNOWN and existing.type != VarType.UNKNOWN:
                        if existing.type != rhs_type:
                            self.errors.append(SemanticError(
                                message=(
                                    f"Type mismatch on redeclaration: '{var_name}' is {existing.type}, "
                                    f"but RHS is {rhs_type}"
                                ),
                                line=current_line,
                                error_type="error"
                            ))

                    # Keep the first declaration, but still walk the RHS.
                    # If you want reassignment to be allowed later, this is the
                    # single place to relax.
        
        node["children"] = children
        return node
    
    def _analyze_if(self, node: Any) -> Any:
        """Analyze if statement with new scope"""
        # Enter new scope
        new_scope = Scope(level=self.current_scope.level + 1, parent=self.current_scope)
        old_scope = self.current_scope
        self.current_scope = new_scope
        
        # Analyze condition and body
        if "children" in node:
            node["children"] = [self._analyze_node(child) for child in node.get("children", [])]
        
        # Exit scope
        self.current_scope = old_scope
        return node
    
    def _analyze_print(self, node: Any) -> Any:
        """Analyze print statement"""
        if "children" in node:
            node["children"] = [self._analyze_node(child) for child in node.get("children", [])]
        return node
    
    def _analyze_return(self, node: Any) -> Any:
        """Analyze return statement"""
        if "children" in node:
            node["children"] = [self._analyze_node(child) for child in node.get("children", [])]
        return node
    
    def _analyze_expr(self, node: Any) -> Any:
        """Analyze expression node"""
        if "children" in node:
            node["children"] = [self._analyze_node(child) for child in node.get("children", [])]
        return node
    
    def _analyze_var(self, node: Any) -> Any:
        """Check if variable is defined"""
        var_name = node.get("value")
        if var_name:
            sym = self.current_scope.lookup(var_name)
            if sym is None:
                self.errors.append(SemanticError(
                    message=f"Undefined variable: '{var_name}'",
                    line=node.get("line", 0),
                    error_type="error"
                ))
            else:
                # Mark type in node
                node["_type"] = sym.type
        return node
    
    def _analyze_binop(self, node: Any) -> Any:
        """Analyze binary operation for type compatibility"""
        children = node.get("children", [])
        if len(children) >= 2:
            # Analyze operands
            children[0] = self._analyze_node(children[0])
            children[1] = self._analyze_node(children[1])
            op = node.get("value", "")
            left_type = self._infer_type(children[0])
            right_type = self._infer_type(children[1])

            # Type checking for numeric operations
            if op in ("+", "-", "*", "/"):
                if left_type not in (VarType.INT, VarType.FLOAT, VarType.UNKNOWN):
                    self.errors.append(SemanticError(
                        message=f"Operator '{op}' requires numeric left operand, got {left_type}",
                        line=node.get("line", 0),
                        error_type="error"
                    ))
                if right_type not in (VarType.INT, VarType.FLOAT, VarType.UNKNOWN):
                    self.errors.append(SemanticError(
                        message=f"Operator '{op}' requires numeric right operand, got {right_type}",
                        line=node.get("line", 0),
                        error_type="error"
                    ))

            # Infer and attach result type if known
            result_type = self._infer_type(node)
            if result_type != VarType.UNKNOWN:
                node["_type"] = result_type

            node["children"] = children
        return node
    
    def _analyze_call(self, node: Any) -> Any:
        """Check function call validity"""
        func_name = node.get("value")
        if func_name:
            sym = self.current_scope.lookup(func_name)
            if sym is None:
                self.errors.append(SemanticError(
                    message=f"Undefined function: '{func_name}'",
                    line=node.get("line", 0),
                    error_type="error"
                ))
            elif sym.kind != "function":
                self.errors.append(SemanticError(
                    message=f"'{func_name}' is not a function",
                    line=node.get("line", 0),
                    error_type="error"
                ))
        
        # Analyze arguments
        if "children" in node:
            node["children"] = [self._analyze_node(child) for child in node.get("children", [])]
        
        return node
    
    def _analyze_generic(self, node: Any) -> Any:
        """Generic node analysis"""
        if isinstance(node, dict):
            if "children" in node:
                node["children"] = [self._analyze_node(child) for child in node.get("children", [])]
        return node
    
    def _collect_symbols(self):
        """Collect all symbols into a flat structure"""
        self.symbol_table[0] = self.global_scope.symbols
    
    def _make_result(self) -> Dict[str, Any]:
        """Create result dictionary"""
        return {
            "success": len(self.errors) == 0,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
            "symbol_table": {
                str(k): {name: sym.to_dict() for name, sym in v.items()}
                for k, v in self.symbol_table.items()
            },
            "ast": self.decorated_ast,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings)
        }


def analyze_ast(ast: Any) -> Dict[str, Any]:
    """Convenience function to run semantic analysis"""
    analyzer = SemanticAnalyzer()
    return analyzer.analyze(ast)
