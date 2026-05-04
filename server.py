"""
server.py  —  Tiny HTTP server for the Lexer UI
Run:  python server.py
Then open:  http://localhost:8000
"""

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

# Import lexer, parser, and semantic analyzer from same directory
import sys
sys.path.insert(0, os.path.dirname(__file__))
from lexer import Lexer
from parser import parse_source
from semantic_analyzer import analyze_ast


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass   # suppress console noise

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ('/', '/index.html'):
            self._serve_file('ui.html', 'text/html')
        else:
            self._404()

    def do_POST(self):
        if self.path == '/lex':
            length = int(self.headers.get('Content-Length', 0))
            body   = self.rfile.read(length)
            try:
                payload = json.loads(body)
                source  = payload.get('source', '')
                lx = Lexer(source).tokenise()
                result = {
                    "tokens": [t.to_dict() for t in lx.visible_tokens()],
                    "errors": [e.to_dict() for e in lx.errors],
                }
                self._json(result)
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
        elif self.path == '/parse':
            length = int(self.headers.get('Content-Length', 0))
            body   = self.rfile.read(length)
            try:
                payload = json.loads(body)
                source  = payload.get('source', '')
                mode    = payload.get('mode', 'rd')  # default to recursive descent
                
                # Stage 1: Lexical Analysis
                lx = Lexer(source).tokenise()
                lex_tokens = [t.to_dict() for t in lx.visible_tokens()]
                lex_errors = [e.to_dict() for e in lx.errors]
                
                # Stage 2: Syntax Analysis (parsing)
                parse_result = parse_source(source, mode)
                
                # Combine results to show both stages
                result = {
                    "stage1_lexer": {
                        "tokens": lex_tokens,
                        "errors": lex_errors,
                        "token_count": len(lex_tokens)
                    },
                    "stage2_parser": parse_result
                }
                self._json(result)
            except Exception as exc:
                import traceback
                self._json({"error": str(exc), "traceback": traceback.format_exc()}, 500)
        elif self.path == '/compile':
            # Full multi-stage compilation pipeline
            length = int(self.headers.get('Content-Length', 0))
            body   = self.rfile.read(length)
            try:
                payload = json.loads(body)
                source  = payload.get('source', '')
                mode    = payload.get('mode', 'rd')
                
                # ════════════════════════════════════════
                # STAGE 1: LEXICAL ANALYSIS
                # ════════════════════════════════════════
                lx = Lexer(source).tokenise()
                lex_tokens = [t.to_dict() for t in lx.visible_tokens()]
                lex_errors = [e.to_dict() for e in lx.errors]
                stage1_result = {
                    "stage_name": "Lexical Analysis",
                    "tokens": lex_tokens,
                    "errors": lex_errors,
                    "token_count": len(lex_tokens),
                    "error_count": len(lex_errors),
                    "success": len(lex_errors) == 0
                }
                
                # ════════════════════════════════════════
                # STAGE 2: SYNTAX ANALYSIS (PARSING)
                # ════════════════════════════════════════
                parse_result = parse_source(source, mode)
                stage2_result = {
                    "stage_name": "Syntax Analysis (Parser)",
                    "parser_mode": mode,
                    "success": parse_result.get('success', False),
                    "ast": parse_result.get('ast'),
                    "errors": parse_result.get('errors', []),
                    "error_count": len(parse_result.get('errors', [])),
                }
                
                # ════════════════════════════════════════
                # STAGE 3: SEMANTIC ANALYSIS
                # ════════════════════════════════════════
                stage3_result = {"stage_name": "Semantic Analysis", "success": True, "ast": None, "symbol_table": {}, "errors": [], "warnings": []}
                
                with open('debug_server.log', 'a') as f:
                    f.write(f"Stage 2 success: {stage2_result.get('success')}, has AST: {parse_result.get('ast') is not None}\n")
                
                if stage2_result["success"] and parse_result.get('ast'):
                    # Only proceed if parsing was successful
                    with open('debug_server.log', 'a') as f:
                        f.write("Calling analyze_ast\n")
                    semantic_result = analyze_ast(parse_result['ast'])
                    stage3_result = {
                        "stage_name": "Semantic Analysis",
                        "success": semantic_result.get('success', True),
                        "ast": semantic_result.get('ast'),
                        "symbol_table": semantic_result.get('symbol_table', {}),
                        "errors": semantic_result.get('errors', []),
                        "warnings": semantic_result.get('warnings', []),
                        "error_count": semantic_result.get('error_count', 0),
                        "warning_count": semantic_result.get('warning_count', 0),
                    }
                else:
                    stage3_result["errors"] = [{"message": "Skipped: syntax errors in stage 2", "error_type": "info"}]
                
                # ════════════════════════════════════════
                # COMBINE ALL STAGES
                # ════════════════════════════════════════
                final_result = {
                    "overall_success": stage1_result["success"] and stage2_result["success"] and stage3_result["success"],
                    "stages": [stage1_result, stage2_result, stage3_result]
                }
                
                self._json(final_result)
            except Exception as exc:
                import traceback
                self._json({"error": str(exc), "traceback": traceback.format_exc()}, 500)
        else:
            self._404()

    def _serve_file(self, name, ctype):
        path = os.path.join(os.path.dirname(__file__), name)
        try:
            with open(path, 'rb') as f:
                data = f.read()
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', len(data))
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self._404()

    def _json(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(data))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(data)

    def _404(self):
        self.send_response(404)
        self.end_headers()


if __name__ == '__main__':
    port = 8000
    srv  = HTTPServer(('localhost', port), Handler)
    print(f"Lexer UI  →  http://localhost:{port}")
    print("Press Ctrl-C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")