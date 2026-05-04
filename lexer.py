"""
lexer.py  —  Regex + DFA-based Lexer
============================================================
Supports:
  integers, floats (positive & negative), identifiers,
  keywords, if/else/elif, for/while loops, operators,
  strings, booleans, comments, and full error reporting.

Architecture
------------
  1. REGEX RULES  — ordered patterns scan the source and
     yield raw (type, value) pairs.
  2. MINI DFA     — hand-coded Deterministic Finite Automaton
     re-validates each matched value, disambiguates
     sign vs operator, and classifies the final token type.
  3. LEXER CLASS  — drives the scan, tracks line/col,
     collects Tokens and LexErrors.

Usage
-----
  python lexer.py <source_file>          # pretty report
  python lexer.py <source_file> --json   # JSON output
"""

import re
import sys
import json
from dataclasses import dataclass, asdict
from typing import List, Optional, Tuple


# ─────────────────────────────────────────────────────────────
#  TOKEN TYPES
# ─────────────────────────────────────────────────────────────
class TT:
    KEYWORD    = "KEYWORD"
    IDENTIFIER = "IDENTIFIER"
    INTEGER    = "INTEGER"
    FLOAT      = "FLOAT"
    STRING     = "STRING"
    BOOLEAN    = "BOOLEAN"
    OPERATOR   = "OPERATOR"
    LPAREN     = "LPAREN"
    RPAREN     = "RPAREN"
    LBRACE     = "LBRACE"
    RBRACE     = "RBRACE"
    LBRACKET   = "LBRACKET"
    RBRACKET   = "RBRACKET"
    COLON      = "COLON"
    COMMA      = "COMMA"
    DOT        = "DOT"
    SEMICOLON  = "SEMICOLON"
    NEWLINE    = "NEWLINE"
    COMMENT    = "COMMENT"
    EOF        = "EOF"
    ERROR      = "ERROR"


KEYWORDS = {
    "if", "else", "elif", "in", "not", "and", "or",
    "def", "return", "import", "from", "as", "pass",
    "break", "continue", "lambda", "yield", "with", "try", "except",
    "finally", "raise", "del", "global", "nonlocal", "assert",
    "print", "range", "len", "int", "float", "str", "bool", "list",
    "dict", "set", "tuple", "input", "type", "isinstance",
    "None", "True", "False",
}

BOOLEANS = {"True", "False", "None"}


# ─────────────────────────────────────────────────────────────
#  DATA CLASSES
# ─────────────────────────────────────────────────────────────
@dataclass
class Token:
    type:  str
    value: str
    line:  int
    col:   int

    def __repr__(self):
        return f"Token({self.type}, {self.value!r}, ln={self.line}, col={self.col})"

    def to_dict(self):
        return asdict(self)


@dataclass
class LexError:
    message: str
    char:    str
    line:    int
    col:     int

    def __str__(self):
        return (f"[LexError] Line {self.line}, Col {self.col}: "
                f"Unexpected character {self.char!r} — not part of the language")

    def to_dict(self):
        return asdict(self)


# ─────────────────────────────────────────────────────────────
#  REGEX TOKEN RULES  (order matters — longest/specific first)
# ─────────────────────────────────────────────────────────────
TOKEN_REGEX: List[Tuple[str, re.Pattern]] = [
    (TT.COMMENT,   re.compile(r'#[^\n]*')),
    (TT.NEWLINE,   re.compile(r'\n')),
    ("WHITESPACE", re.compile(r'[ \t\r]+')),

    # Floats before integers so "3.14" isn't split as 3 + .14
    (TT.FLOAT,     re.compile(r'[+-]?(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?')),
    (TT.INTEGER,   re.compile(r'[+-]?\d+')),

    # Strings — triple-quote first, then single-line
    (TT.STRING,    re.compile(
        r'""".*?"""|\'\'\'.*?\'\'\'|"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'',
        re.DOTALL
    )),

    # Operators — compound before single character
    (TT.OPERATOR,  re.compile(
        r'<<=|>>=|[+\-*/%&|^]=|==|!=|<=|>=|<<|>>|//|\*\*|->'
        r'|[+\-*/%<>=!&|^~]'
    )),

    (TT.LPAREN,    re.compile(r'\(')),
    (TT.RPAREN,    re.compile(r'\)')),
    (TT.LBRACE,    re.compile(r'\{')),
    (TT.RBRACE,    re.compile(r'\}')),
    (TT.LBRACKET,  re.compile(r'\[')),
    (TT.RBRACKET,  re.compile(r'\]')),
    (TT.COLON,     re.compile(r':')),
    (TT.COMMA,     re.compile(r',')),
    (TT.DOT,       re.compile(r'\.')),
    (TT.SEMICOLON, re.compile(r';')),

    # Identifier / keyword last (after operators, so "-=" etc. win)
    (TT.IDENTIFIER, re.compile(r'[a-zA-Z_][a-zA-Z0-9_]*')),
]


# ─────────────────────────────────────────────────────────────
#  HAND-CODED DFA
#  Deterministic Finite Automaton that re-validates every matched
#  token value and returns the canonical TT.* type.
#
#  State diagram (simplified):
#
#   START
#     ├─ digit → INTEGER ──┬─ '.' → FLOAT_DOT → FLOAT_FRAC
#     │                    └─ 'e/E' → EXP_START → EXP_DIGITS
#     ├─ '.' digit → FLOAT_FRAC
#     ├─ alpha/_ → IDENT  ──→  KEYWORD | BOOLEAN | IDENTIFIER
#     ├─ '"'|'\'' → STR_*  ──→  STRING
#     ├─ sign only → OPERATOR
#     └─ known operator/punct → corresponding TT.*
# ─────────────────────────────────────────────────────────────
class DFAState:
    START      = "START"
    INTEGER    = "INTEGER"
    FLOAT_DOT  = "FLOAT_DOT"
    FLOAT_FRAC = "FLOAT_FRAC"
    EXP_START  = "EXP_START"
    EXP_SIGN   = "EXP_SIGN"
    EXP_DIGITS = "EXP_DIGITS"
    STR_BODY   = "STR_BODY"
    STR_ESC    = "STR_ESC"
    IDENT      = "IDENT"
    DONE       = "DONE"
    ERROR      = "ERROR"


OPERATORS = {
    '+', '-', '*', '/', '%', '<', '>', '=', '!', '&', '|', '^', '~',
    '**', '//', '==', '!=', '<=', '>=', '<<', '>>', '->',
    '+=', '-=', '*=', '/=', '%=', '&=', '|=', '^=', '<<=', '>>=',
}

PUNCT_MAP = {
    '(': TT.LPAREN,   ')': TT.RPAREN,
    '{': TT.LBRACE,   '}': TT.RBRACE,
    '[': TT.LBRACKET, ']': TT.RBRACKET,
    ':': TT.COLON,    ',': TT.COMMA,
    '.': TT.DOT,      ';': TT.SEMICOLON,
}


def dfa_classify(value: str) -> str:
    """
    Run the DFA over `value` and return the recognised TT.* type,
    or TT.ERROR if unrecognised.
    """
    if not value:
        return TT.ERROR

    i = 0
    n = len(value)

    # ── optional leading sign ─────────────────────────────────────────
    if value[0] in ('+', '-'):
        if n == 1:
            return TT.OPERATOR   # bare '+' or '-'
        i = 1

    # ── numeric path ──────────────────────────────────────────────────
    if i < n and value[i].isdigit():
        state = DFAState.INTEGER
        i += 1
        while i < n and value[i].isdigit():
            i += 1

        # optional fractional part
        if i < n and value[i] == '.':
            state = DFAState.FLOAT_DOT
            i += 1
            if i < n and value[i].isdigit():
                state = DFAState.FLOAT_FRAC
                i += 1
                while i < n and value[i].isdigit():
                    i += 1

        # optional exponent
        if i < n and value[i] in ('e', 'E'):
            state = DFAState.EXP_START
            i += 1
            if i < n and value[i] in ('+', '-'):
                state = DFAState.EXP_SIGN
                i += 1
            if i < n and value[i].isdigit():
                state = DFAState.EXP_DIGITS
                i += 1
                while i < n and value[i].isdigit():
                    i += 1
            else:
                return TT.ERROR  # exponent with no digits

        if i != n:
            return TT.ERROR

        if state == DFAState.INTEGER:
            return TT.INTEGER
        if state in (DFAState.FLOAT_DOT, DFAState.FLOAT_FRAC, DFAState.EXP_DIGITS):
            return TT.FLOAT
        return TT.ERROR

    # ── float starting with '.' ───────────────────────────────────────
    if i < n and value[i] == '.':
        i += 1
        if i < n and value[i].isdigit():
            i += 1
            while i < n and value[i].isdigit():
                i += 1
            return TT.FLOAT if i == n else TT.ERROR
        return TT.ERROR

    # ── identifier / keyword / boolean ────────────────────────────────
    if i < n and (value[i].isalpha() or value[i] == '_'):
        state = DFAState.IDENT
        i += 1
        while i < n and (value[i].isalnum() or value[i] == '_'):
            i += 1
        if i == n:
            if value in BOOLEANS:  return TT.BOOLEAN
            if value in KEYWORDS:  return TT.KEYWORD
            return TT.IDENTIFIER
        return TT.ERROR

    # ── string literal ────────────────────────────────────────────────
    if i < n and value[i] in ('"', "'"):
        q = value[i]
        # triple-quoted
        if value[i:i+3] == q * 3:
            close = value.find(q * 3, i + 3)
            return TT.STRING if (close != -1 and close + 3 == n) else TT.ERROR
        # single-quoted
        i += 1
        state = DFAState.STR_BODY
        while i < n:
            c = value[i]
            if state == DFAState.STR_ESC:
                state = DFAState.STR_BODY
            elif c == '\\':
                state = DFAState.STR_ESC
            elif c == q:
                i += 1
                return TT.STRING if i == n else TT.ERROR
            i += 1
        return TT.ERROR   # unclosed string

    # ── operators ─────────────────────────────────────────────────────
    if value in OPERATORS:
        return TT.OPERATOR

    # ── punctuation ───────────────────────────────────────────────────
    if value in PUNCT_MAP:
        return PUNCT_MAP[value]

    return TT.ERROR


# ─────────────────────────────────────────────────────────────
#  LEXER
# ─────────────────────────────────────────────────────────────
class Lexer:
    def __init__(self, source: str):
        self.source = source
        self.pos    = 0
        self.line   = 1
        self.col    = 1
        self.tokens: List[Token]    = []
        self.errors: List[LexError] = []

    # ── context: is '+'/'-' a sign or an operator? ────────────────────
    def _prev_significant(self) -> Optional[Token]:
        for t in reversed(self.tokens):
            if t.type not in (TT.COMMENT, TT.NEWLINE):
                return t
        return None

    def _sign_is_operator(self) -> bool:
        prev = self._prev_significant()
        if prev is None:
            return False
        return prev.type in (
            TT.INTEGER, TT.FLOAT, TT.IDENTIFIER, TT.BOOLEAN,
            TT.RPAREN, TT.RBRACKET,
        )

    # ── advance position counter ──────────────────────────────────────
    def _advance(self, value: str):
        for ch in value:
            if ch == '\n':
                self.line += 1
                self.col   = 1
            else:
                self.col += 1
        self.pos += len(value)

    # ── main scan ─────────────────────────────────────────────────────
    def tokenise(self) -> "Lexer":
        src = self.source
        n   = len(src)

        while self.pos < n:
            chunk    = src[self.pos:]
            start_ln = self.line
            start_cl = self.col
            matched  = False

            for tok_type, pattern in TOKEN_REGEX:
                m = pattern.match(chunk)
                if not m:
                    continue

                raw = m.group(0)

                # whitespace — consume silently
                if tok_type == "WHITESPACE":
                    self._advance(raw)
                    matched = True
                    break

                # newline — emit then advance
                if tok_type == TT.NEWLINE:
                    self.tokens.append(Token(TT.NEWLINE, "\\n", start_ln, start_cl))
                    self._advance(raw)
                    matched = True
                    break

                # sign disambiguation for integers and floats
                if tok_type in (TT.FLOAT, TT.INTEGER) and raw[0] in ('+', '-'):
                    if self._sign_is_operator():
                        sign = raw[0]
                        self.tokens.append(Token(TT.OPERATOR, sign, start_ln, start_cl))
                        self._advance(sign)
                        # re-match remainder as unsigned number
                        chunk2 = src[self.pos:]
                        m2 = pattern.match(chunk2)
                        if m2:
                            raw = m2.group(0)
                        else:
                            matched = True
                            break

                # DFA validation
                dfa_type = dfa_classify(raw)

                # refine IDENTIFIER
                final_type = tok_type
                if tok_type == TT.IDENTIFIER:
                    if raw in BOOLEANS: final_type = TT.BOOLEAN
                    elif raw in KEYWORDS: final_type = TT.KEYWORD

                # if DFA disagrees, flag error
                if dfa_type == TT.ERROR:
                    self.errors.append(
                        LexError(f"DFA rejected token: {raw!r}", raw, start_ln, start_cl)
                    )
                    self.tokens.append(Token(TT.ERROR, raw, start_ln, start_cl))
                else:
                    self.tokens.append(Token(final_type, raw, start_ln, start_cl))

                self._advance(raw)
                matched = True
                break

            if not matched:
                bad = src[self.pos]
                self.errors.append(
                    LexError(
                        f"Unexpected character {bad!r} — not part of the language",
                        bad, start_ln, start_cl
                    )
                )
                self.tokens.append(Token(TT.ERROR, bad, start_ln, start_cl))
                self._advance(bad)

        self.tokens.append(Token(TT.EOF, "EOF", self.line, self.col))
        return self

    # ── public helpers ────────────────────────────────────────────────
    def visible_tokens(self) -> List[Token]:
        """Tokens excluding NEWLINE and EOF."""
        return [t for t in self.tokens if t.type not in (TT.NEWLINE, TT.EOF)]

    def report(self) -> str:
        lines = []
        lines.append(f"{'TYPE':<14} {'VALUE':<24} {'LINE':>5} {'COL':>5}")
        lines.append("─" * 54)
        for t in self.visible_tokens():
            lines.append(
                f"{t.type:<14} {repr(t.value):<24} {t.line:>5} {t.col:>5}"
            )
        if self.errors:
            lines.append("\n── ERRORS " + "─" * 44)
            for e in self.errors:
                lines.append(str(e))
        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps({
            "tokens": [t.to_dict() for t in self.visible_tokens()],
            "errors": [e.to_dict() for e in self.errors],
        }, indent=2)


# ─────────────────────────────────────────────────────────────
#  PUBLIC API  (used by server.py and importers)
# ─────────────────────────────────────────────────────────────
def lex_source(source: str, fmt: str = "report") -> str:
    lx = Lexer(source).tokenise()
    return lx.to_json() if fmt == "json" else lx.report()


# ─────────────────────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python lexer.py <source_file>  [--json]")
        sys.exit(1)

    path = sys.argv[1]
    fmt  = "json" if "--json" in sys.argv else "report"

    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    print(lex_source(src, fmt))