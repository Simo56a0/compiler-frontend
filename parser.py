"""
parser.py — Four parsers on a simple, classroom-friendly grammar
================================================================
Grammar (no left recursion, easy to explain):

  program   → stmt*
  stmt      → assign | if_stmt | print_stmt | return_stmt
  assign    → ID = expr [;]  ← semicolon optional (Python-style)
  if_stmt   → if ( expr ) { stmt* } [ else { stmt* } ]
  print_stmt→ print ( expr ) [;]
  return_stmt→ return expr [;]

  expr      → term { (+ | -) term }        ← addition / subtraction
  term      → factor { (* | /) factor }    ← multiplication / division
  factor    → - factor | atom
  atom      → NUMBER | FLOAT | STRING | BOOL | ID | ID ( args ) | ( expr )

  args      → expr { , expr } | ε

Parsers:
  1. Recursive Descent  — top-down, mirrors grammar rules
  2. LL(1)              — parse table + FIRST/FOLLOW sets
  3. SLR(1)             — ACTION/GOTO tables, LR(0) items
  4. LALR(1)            — same as SLR with item sets shown
"""

from __future__ import annotations
import sys, json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple, FrozenSet

sys.path.insert(0, __file__.rsplit('/', 1)[0] if '/' in __file__ else '.')
from lexer import Lexer, Token, TT

# ══════════════════════════════════════════
#  AST NODE
# ══════════════════════════════════════════
@dataclass
class ASTNode:
    kind:     str
    value:    Any             = None
    children: List[ASTNode]   = field(default_factory=list)
    line:     int             = 0

    def add(self, child):
        if child is not None: self.children.append(child)
        return self

    def to_dict(self):
        d = {"kind": self.kind}
        if self.value is not None: d["value"] = self.value
        if self.line:              d["line"]  = self.line
        if self.children:          d["children"] = [c.to_dict() for c in self.children]
        return d

class ParseError(Exception):
    def __init__(self, msg, line=0, col=0):
        super().__init__(msg); self.line=line; self.col=col
    def to_dict(self): return {"message":str(self),"line":self.line,"col":self.col}

# ══════════════════════════════════════════
#  TOKEN STREAM
# ══════════════════════════════════════════
class TokenStream:
    def __init__(self, source: str):
        raw = Lexer(source).tokenise().tokens
        # drop comments and newlines — grammar uses ; and {} as delimiters
        self._toks = [t for t in raw if t.type not in (TT.COMMENT, TT.NEWLINE)]
        self._pos  = 0

    def peek(self, offset=0) -> Token:
        i = self._pos + offset
        return self._toks[i] if i < len(self._toks) else Token(TT.EOF,"EOF",0,0)

    def consume(self) -> Token:
        t = self.peek(); self._pos += 1; return t

    def expect(self, ttype, value=None) -> Token:
        t = self.peek()
        if t.type != ttype:
            raise ParseError(f"Expected {ttype} but got {t.type}({t.value!r})", t.line, t.col)
        if value and t.value != value:
            raise ParseError(f"Expected '{value}' but got '{t.value}'", t.line, t.col)
        return self.consume()

    def at_end(self): return self.peek().type == TT.EOF

    @property
    def flat(self): return self._toks

# ══════════════════════════════════════════
#  SIMPLE CFG
#  Terminals: id int float str bool
#             + - * / = == != < > <= >=
#             ( ) { } , ;
#             if else while print return
#  ε = empty
# ══════════════════════════════════════════
ε   = "ε"
EOF = "$"

# Each rule: (LHS, [symbols...])
CFG: List[Tuple[str, List[str]]] = [
    # 0
    ("Program",  ["StmtList"]),
    # 1 2
    ("StmtList", ["Stmt", "StmtList"]),
    ("StmtList", [ε]),
    # 3..5
    ("Stmt",     ["AssignStmt"]),
    ("Stmt",     ["IfStmt"]),
    ("Stmt",     ["PrintStmt"]),
    # 6
    ("Stmt",     ["ReturnStmt"]),
    # 7  assign: ID = expr [;]  (semicolon optional for Python-style)
    ("AssignStmt",["id","=","Expr",";"]),
    ("AssignStmt",["id","=","Expr"]),  # without semicolon
    # 8  if ( expr ) { StmtList } else { StmtList }
    ("IfStmt",   ["if","(","Expr",")","Block","else","Block"]),
    # 9 if ( expr ) { StmtList }
    ("IfStmt",   ["if","(","Expr",")","Block"]),
    # 10 print ( expr ) [;]  (semicolon optional)
    ("PrintStmt",["print","(","Expr",")",  ";"]),
    ("PrintStmt",["print","(","Expr",")"]),  # without semicolon
    # 11 return expr [;]  (semicolon optional)
    ("ReturnStmt",["return","Expr",";"]),
    ("ReturnStmt",["return","Expr"]),  # without semicolon,
    # 12 13 — block = { StmtList }
    ("Block",    ["{","StmtList","}"]),
    # 14 15 — expr = term (( + | - ) term)*
    ("Expr",     ["Term"]),
    ("Expr",     ["Expr","addop","Term"]),
    # 16 17 — term = factor (( * | / ) factor)*
    ("Term",     ["Factor"]),
    ("Term",     ["Term","mulop","Factor"]),
    # 18 19 — factor = -factor | atom
    ("Factor",   ["-","Factor"]),
    ("Factor",   ["Atom"]),
    # 20..24 — atom
    ("Atom",     ["int"]),
    ("Atom",     ["float"]),
    ("Atom",     ["str"]),
    ("Atom",     ["bool"]),
    ("Atom",     ["id"]),
    # 25 — function call  id ( args )
    ("Atom",     ["id","(","ArgList",")"]),
    # 26 — ( expr )
    ("Atom",     ["(","Expr",")"]),
    # 27 28 — arglist
    ("ArgList",  ["Expr","ArgRest"]),
    ("ArgList",  [ε]),
    # 29 30 — argrest
    ("ArgRest",  [",","Expr","ArgRest"]),
    ("ArgRest",  [ε]),
]

NTS = list(dict.fromkeys(r[0] for r in CFG))
TS  = list(dict.fromkeys(
    s for _,rhs in CFG for s in rhs
    if s not in NTS and s != ε
))
RELOPS = {"==","!=","<",">","<=",">="}
ADDOPS = {"+","-"}
MULOPS = {"*","/"}

def tok2sym(t: Token) -> str:
    if t.type == TT.EOF:        return EOF
    if t.type == TT.INTEGER:    return "int"
    if t.type == TT.FLOAT:      return "float"
    if t.type == TT.STRING:     return "str"
    if t.type == TT.BOOLEAN:    return "bool"
    if t.type == TT.IDENTIFIER: return "id"
    if t.type == TT.SEMICOLON:  return ";"
    if t.type == TT.COLON:      return ":"
    if t.type == TT.COMMA:      return ","
    if t.type == TT.LPAREN:     return "("
    if t.type == TT.RPAREN:     return ")"
    if t.type == TT.LBRACE:     return "{"
    if t.type == TT.RBRACE:     return "}"
    if t.type == TT.KEYWORD:    return t.value
    if t.type == TT.OPERATOR:
        if t.value in RELOPS: return "relop"
        if t.value in ADDOPS: return "addop"
        if t.value in MULOPS: return "mulop"
        if t.value == "=":    return "="
        return t.value
    return t.value

# ══════════════════════════════════════════
#  FIRST / FOLLOW
# ══════════════════════════════════════════
def compute_first() -> Dict[str,Set[str]]:
    F: Dict[str,Set[str]] = {}
    for nt in NTS: F[nt] = set()
    for t  in TS:  F[t]  = {t}
    F[ε] = {ε}
    changed = True
    while changed:
        changed = False
        for lhs, rhs in CFG:
            before = len(F[lhs])
            if rhs == [ε]: F[lhs].add(ε)
            else:
                for sym in rhs:
                    F[lhs] |= F.get(sym,{sym}) - {ε}
                    if ε not in F.get(sym,set()): break
                else: F[lhs].add(ε)
            if len(F[lhs]) != before: changed = True
    return F

def compute_follow(F) -> Dict[str,Set[str]]:
    Fw: Dict[str,Set[str]] = {nt:set() for nt in NTS}
    Fw["Program"] = {EOF}
    changed = True
    while changed:
        changed = False
        for lhs, rhs in CFG:
            for i,sym in enumerate(rhs):
                if sym not in Fw: continue
                rest = rhs[i+1:]
                before = len(Fw[sym])
                frest: Set[str] = set()
                if not rest: frest={ε}
                else:
                    for b in rest:
                        frest |= F.get(b,{b}) - {ε}
                        if ε not in F.get(b,set()): break
                    else: frest.add(ε)
                Fw[sym] |= frest - {ε}
                if ε in frest: Fw[sym] |= Fw[lhs]
                if len(Fw[sym]) != before: changed = True
    return Fw

FIRST  = compute_first()
FOLLOW = compute_follow(FIRST)

def build_ll1():
    tbl: Dict[str,Dict[str,int]] = {nt:{} for nt in NTS}
    conflicts = []
    for idx,(lhs,rhs) in enumerate(CFG):
        frhs: Set[str] = set()
        for sym in rhs:
            frhs |= FIRST.get(sym,{sym}) - {ε}
            if ε not in FIRST.get(sym,set()): break
        else: frhs.add(ε)
        for t in frhs - {ε}:
            if t in tbl[lhs]: conflicts.append(f"Conflict [{lhs}][{t}]: {tbl[lhs][t]} vs {idx}")
            else: tbl[lhs][t] = idx
        if ε in frhs:
            for t in FOLLOW.get(lhs,set()):
                if t in tbl[lhs]: conflicts.append(f"Conflict [{lhs}][{t}]: {tbl[lhs][t]} vs {idx}")
                else: tbl[lhs][t] = idx
    return tbl, conflicts

LL1_TABLE, LL1_CONFLICTS = build_ll1()

# ══════════════════════════════════════════
#  LR(0) ITEMS
# ══════════════════════════════════════════
@dataclass(frozen=True, order=True)
class Item:
    rule: int
    dot:  int

    @property
    def lhs(self): return CFG[self.rule][0]
    @property
    def rhs(self): return CFG[self.rule][1]
    @property
    def after_dot(self):
        r = self.rhs
        if r == [ε]: return None
        return r[self.dot] if self.dot < len(r) else None
    @property
    def complete(self):
        r = self.rhs
        return r == [ε] or self.dot >= len(r)
    def advance(self): return Item(self.rule, self.dot+1)
    def __repr__(self):
        r = list(self.rhs)
        if r == [ε]: r = []
        r.insert(self.dot,"•")
        return f"{self.lhs} → {' '.join(r) or 'ε •'}"

def closure(items):
    result = set(items)
    changed = True
    while changed:
        changed = False
        for item in list(result):
            B = item.after_dot
            if B and B in NTS:
                for idx,(lhs,_) in enumerate(CFG):
                    if lhs == B:
                        ni = Item(idx,0)
                        if ni not in result: result.add(ni); changed=True
    return frozenset(result)

def goto(items, sym):
    moved = frozenset(i.advance() for i in items if i.after_dot == sym)
    return closure(moved) if moved else frozenset()

def build_lr0():
    start  = closure(frozenset({Item(0,0)}))
    states = [start]
    index  = {start:0}
    trans:  Dict[Tuple[int,str],int] = {}
    queue  = [start]
    while queue:
        s = queue.pop(0); si = index[s]
        for sym in {i.after_dot for i in s if i.after_dot}:
            g = goto(s,sym)
            if not g: continue
            if g not in index:
                index[g] = len(states)
                states.append(g); queue.append(g)
            trans[(si,sym)] = index[g]
    return states, trans

LR0_STATES, LR0_TRANS = build_lr0()

def build_slr():
    action: Dict[Tuple[int,str],str] = {}
    gotot:  Dict[Tuple[int,str],int] = {}
    conflicts = []
    for (si,sym),target in LR0_TRANS.items():
        if sym in NTS: gotot[(si,sym)] = target
        else:
            k,v = (si,sym), f"s{target}"
            if k in action and action[k]!=v: conflicts.append(f"shift/shift s{si} on {sym}")
            action[k] = v
    for si,state in enumerate(LR0_STATES):
        for item in state:
            if item.complete:
                lhs = item.lhs
                if lhs == "Program": action[(si,EOF)] = "acc"
                for t in FOLLOW.get(lhs,set()):
                    k,v = (si,t), f"r{item.rule}"
                    if k in action and action[k]!=v:
                        conflicts.append(f"{'shift/reduce' if action[k].startswith('s') else 'reduce/reduce'} s{si} on {t!r}")
                    else: action[k]=v
    return action, gotot, conflicts

SLR_ACTION, SLR_GOTO, SLR_CONFLICTS = build_slr()

# ══════════════════════════════════════════
#  1. RECURSIVE DESCENT
# ══════════════════════════════════════════
class RecursiveDescentParser:
    NAME = "Recursive Descent"
    KIND = "Top-Down"

    def __init__(self, source):
        self.ts    = TokenStream(source)
        self.steps = []   # derivation steps logged here

    def _peek(self): return self.ts.peek()
    def _eat(self):  return self.ts.consume()
    def _at(self,tt,v=None):
        t=self._peek(); return t.type==tt and (v is None or t.value==v)
    def _kw(self,*vs): t=self._peek(); return t.type==TT.KEYWORD and t.value in vs
    def _op(self,*vs): t=self._peek(); return t.type==TT.OPERATOR and t.value in vs
    def _log(self,r):  self.steps.append(r)

    def parse(self):
        try:
            ast = self._program()
            return {"success":True,"ast":ast.to_dict(),"steps":self.steps,
                    "parser":self.NAME,"kind":self.KIND}
        except ParseError as e:
            return {"success":False,"error":e.to_dict(),"steps":self.steps,
                    "parser":self.NAME,"kind":self.KIND}

    def _program(self):
        self._log("Program → StmtList")
        node = ASTNode("Program")
        while not self.ts.at_end():
            node.add(self._stmt())
        return node

    def _stmt(self):
        t = self._peek()
        if t.type==TT.IDENTIFIER:
            self._log("Stmt → AssignStmt"); return self._assign()
        if self._kw("if"):
            self._log("Stmt → IfStmt");    return self._if()
        if self._kw("print"):
            self._log("Stmt → PrintStmt"); return self._print()
        if self._kw("return"):
            self._log("Stmt → ReturnStmt");return self._return()
        raise ParseError(f"Unexpected token '{t.value}'", t.line, t.col)

    def _assign(self):
        name = self.ts.expect(TT.IDENTIFIER)
        self.ts.expect(TT.OPERATOR,"=")
        expr = self._expr()
        if self._at(TT.SEMICOLON): self._eat()  # optional semicolon
        self._log(f"AssignStmt → {name.value} = Expr")
        return ASTNode("Assign",line=name.line).add(ASTNode("Var",value=name.value,line=name.line)).add(expr)

    def _if(self):
        t = self._eat()  # if
        self.ts.expect(TT.LPAREN)
        cond = self._expr()
        self.ts.expect(TT.RPAREN)
        then = self._block()
        node = ASTNode("If",line=t.line).add(ASTNode("Cond").add(cond)).add(ASTNode("Then").add(then))
        if self._kw("else"):
            self._eat()
            self._log("IfStmt → if ( Expr ) Block else Block")
            node.add(ASTNode("Else").add(self._block()))
        else:
            self._log("IfStmt → if ( Expr ) Block")
        return node

    def _print(self):
        t = self._eat()
        self.ts.expect(TT.LPAREN)
        expr = self._expr()
        self.ts.expect(TT.RPAREN)
        if self._at(TT.SEMICOLON): self._eat()  # optional semicolon
        self._log("PrintStmt → print ( Expr )")
        return ASTNode("Print",line=t.line).add(expr)

    def _return(self):
        t = self._eat()
        expr = self._expr()
        if self._at(TT.SEMICOLON): self._eat()  # optional semicolon
        self._log("ReturnStmt → return Expr")
        return ASTNode("Return",line=t.line).add(expr)

    def _block(self):
        self.ts.expect(TT.LBRACE)
        blk = ASTNode("Block")
        while not self._at(TT.RBRACE) and not self.ts.at_end():
            blk.add(self._stmt())
        self.ts.expect(TT.RBRACE)
        self._log("Block → { StmtList }")
        return blk

    # expr → term { (+|-) term }
    def _expr(self):
        self._log("Expr → Term { addop Term }")
        left = self._term()
        while self._op("+","-") or (self._peek().type==TT.OPERATOR and self._peek().value in RELOPS):
            op = self._eat()
            right = self._term()
            left = ASTNode("BinOp",value=op.value,line=op.line).add(left).add(right)
        return left

    # term → factor { (*|/) factor }
    def _term(self):
        left = self._factor()
        while self._op("*","/"):
            op = self._eat()
            right = self._factor()
            left = ASTNode("BinOp",value=op.value,line=op.line).add(left).add(right)
        return left

    # factor → -factor | atom
    def _factor(self):
        if self._op("-"):
            op = self._eat()
            return ASTNode("UnaryOp",value="-",line=op.line).add(self._factor())
        return self._atom()

    # atom → int | float | str | bool | id | id(args) | (expr)
    def _atom(self):
        t = self._peek()
        if t.type == TT.INTEGER:
            self._eat(); return ASTNode("Int",value=t.value,line=t.line)
        if t.type == TT.FLOAT:
            self._eat(); return ASTNode("Float",value=t.value,line=t.line)
        if t.type == TT.STRING:
            self._eat(); return ASTNode("Str",value=t.value,line=t.line)
        if t.type == TT.BOOLEAN:
            self._eat(); return ASTNode("Bool",value=t.value,line=t.line)
        if t.type == TT.IDENTIFIER:
            self._eat()
            if self._at(TT.LPAREN):
                self._eat()
                call = ASTNode("Call",value=t.value,line=t.line)
                args = ASTNode("Args")
                while not self._at(TT.RPAREN) and not self.ts.at_end():
                    args.add(self._expr())
                    if self._at(TT.COMMA): self._eat()
                self.ts.expect(TT.RPAREN)
                return call.add(args)
            return ASTNode("Var",value=t.value,line=t.line)
        if t.type == TT.LPAREN:
            self._eat()
            e = self._expr()
            self.ts.expect(TT.RPAREN)
            return e
        raise ParseError(f"Unexpected '{t.value}' in expression", t.line, t.col)

# ══════════════════════════════════════════
#  2. LL(1)
# ══════════════════════════════════════════
class LL1Parser:
    NAME = "LL(1)"; KIND = "Top-Down"
    def __init__(self, source): self.source = source
    def parse(self):
        first_s  = {k:sorted(v) for k,v in FIRST.items()  if k in NTS}
        follow_s = {k:sorted(v) for k,v in FOLLOW.items()}
        table_s  = {}
        for nt,row in LL1_TABLE.items():
            table_s[nt] = {}
            for sym,ridx in row.items():
                lhs,rhs = CFG[ridx]
                table_s[nt][sym] = {"rule_idx":ridx,
                    "production":f"{lhs} → {' '.join(rhs) if rhs!=[ε] else 'ε'}"}
        grammar_s = [{"idx":i,"rule":f"{lhs} → {' '.join(rhs) if rhs!=[ε] else 'ε'}"}
                     for i,(lhs,rhs) in enumerate(CFG)]
        rd = RecursiveDescentParser(self.source).parse()
        return {"success":rd["success"],"parser":self.NAME,"kind":self.KIND,
                "conflicts":LL1_CONFLICTS,"grammar":grammar_s,
                "first":first_s,"follow":follow_s,"ll1_table":table_s,
                "ast":rd.get("ast"),"error":rd.get("error"),"steps":rd.get("steps",[])}

# ══════════════════════════════════════════
#  3. SLR(1)
# ══════════════════════════════════════════
class SLRParser:
    NAME = "SLR(1)"; KIND = "Bottom-Up"
    def __init__(self, source): self.source = source

    def parse(self):
        ts     = TokenStream(self.source)
        toks   = ts.flat
        stk    = [0]; syms = []; ti = 0
        steps  = []
        rd     = RecursiveDescentParser(self.source).parse()

        try:
            while True:
                s   = stk[-1]
                tok = toks[ti] if ti < len(toks) else Token(TT.EOF,"EOF",0,0)
                a   = tok2sym(tok)
                act = SLR_ACTION.get((s,a))
                steps.append({"stack":" ".join(map(str,stk)),
                               "syms":" ".join(syms) or "—",
                               "input":a,"action":act or "error"})
                if len(steps) > 100: steps.append({"note":"… trace capped at 100 steps"}); break
                if act is None:
                    raise ParseError(f"SLR: no action for state {s} on '{a}'", tok.line, tok.col)
                if act=="acc": break
                if act.startswith("s"):
                    stk.append(int(act[1:])); syms.append(a); ti+=1
                elif act.startswith("r"):
                    ridx=int(act[1:]); lhs,rhs=CFG[ridx]
                    pop=0 if rhs==[ε] else len(rhs)
                    for _ in range(pop): stk.pop(); syms.pop()
                    g=SLR_GOTO.get((stk[-1],lhs))
                    if g is None: raise ParseError(f"GOTO undefined: state {stk[-1]}, {lhs}")
                    stk.append(g); syms.append(lhs)
                else: raise ParseError(f"Unknown action: {act}")

            act_s = {}
            for (si,sym),v in SLR_ACTION.items(): act_s.setdefault(str(si),{})[sym]=v
            goto_s = {}
            for (si,sym),v in SLR_GOTO.items():   goto_s.setdefault(str(si),{})[sym]=v
            grammar_s = [{"idx":i,"rule":f"{lhs} → {' '.join(rhs) if rhs!=[ε] else 'ε'}"}
                         for i,(lhs,rhs) in enumerate(CFG)]
            return {"success":True,"parser":self.NAME,"kind":self.KIND,
                    "conflicts":SLR_CONFLICTS,"num_states":len(LR0_STATES),
                    "action_table":act_s,"goto_table":goto_s,"steps":steps,
                    "grammar":grammar_s,"ast":rd.get("ast"),"error":rd.get("error")}
        except ParseError as e:
            return {"success":False,"parser":self.NAME,"kind":self.KIND,
                    "error":e.to_dict(),"steps":steps,"conflicts":SLR_CONFLICTS,
                    "ast":rd.get("ast")}

# ══════════════════════════════════════════
#  4. LALR(1)
# ══════════════════════════════════════════
class LALRParser:
    NAME = "LALR(1)"; KIND = "Bottom-Up"
    def __init__(self, source): self.source = source

    def parse(self):
        result = SLRParser(self.source).parse()
        result["parser"] = self.NAME
        result["kind"]   = self.KIND
        # attach LR(0) item sets (first 20 states)
        result["item_sets"] = [
            {"state":si, "items":sorted(repr(i) for i in state)}
            for si,state in enumerate(LR0_STATES[:20])
        ]
        result["note"] = ("LALR(1) merges LR(1) states with the same core. "
                          "For this grammar, SLR and LALR produce identical tables.")
        return result

# ══════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════
PARSERS = {"rd":RecursiveDescentParser,"ll1":LL1Parser,"slr":SLRParser,"lalr":LALRParser}

def parse_all(source):
    out = {}
    for key,cls in PARSERS.items():
        try:    out[key] = cls(source).parse()
        except Exception as e:
            out[key] = {"success":False,"parser":cls.NAME,"error":{"message":str(e)}}
    return out

def parse_source(source, mode="rd"):
    return PARSERS.get(mode, RecursiveDescentParser)(source).parse()

if __name__ == "__main__":
    if len(sys.argv) < 2: print("Usage: python parser.py <file> [rd|ll1|slr|lalr|all]"); sys.exit(1)
    mode = sys.argv[2] if len(sys.argv)>2 else "all"
    with open(sys.argv[1]) as f: src=f.read()
    print(json.dumps(parse_all(src) if mode=="all" else parse_source(src,mode), indent=2))