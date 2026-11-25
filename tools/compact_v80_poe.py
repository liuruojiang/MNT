"""Build a smaller, AST-identical Poe upload copy without touching the source.

This is formatting-only compaction: no compressed executable payload, dynamic
exec, strategy changes, or removal of code. The original remains the test
candidate. Keep the Poe metadata header and verify Python 3.11 compatibility.
"""
from pathlib import Path
import argparse
import ast
import io
import tokenize


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / 'mnt_bot V 8.0 plus.py'
DEFAULT_OUTPUT = ROOT / 'outputs/V80_Poe_compact.py'


def compact(source: str) -> str:
    tree = ast.parse(source, feature_version=(3, 11))
    header = '\n'.join(line for line in source.splitlines()[:10] if line.startswith('# poe:'))
    canonical = (header + '\n' if header else '') + ast.unparse(tree) + '\n'
    lines = canonical.splitlines(keepends=True)
    edits = {}
    previous = None
    seen_lines = set()
    skip = {tokenize.INDENT, tokenize.DEDENT, tokenize.NEWLINE, tokenize.NL, tokenize.ENDMARKER, tokenize.ENCODING}
    for token in tokenize.generate_tokens(io.StringIO(canonical).readline):
        if token.type in skip:
            if token.type in (tokenize.NEWLINE, tokenize.NL):
                previous = None
            continue
        row, col = token.start
        if row not in seen_lines:
            seen_lines.add(row)
            prefix = lines[row - 1][:col]
            if col and prefix == ' ' * col and col % 4 == 0:
                edits.setdefault(row, []).append((0, col, ' ' * (col // 4)))
        if previous is not None and previous.end[0] == row:
            start = previous.end[1]
            if start < col and lines[row - 1][start:col].isspace():
                # Only remove gaps next to an operator, not between words or
                # two operators that could become a different lexical token.
                a, b = previous.type == tokenize.OP, token.type == tokenize.OP
                number_dot = ((previous.type == tokenize.NUMBER and token.string == '.') or
                              (previous.string == '.' and token.type == tokenize.NUMBER))
                if a != b and not number_dot:
                    edits.setdefault(row, []).append((start, col, ''))
        previous = token
    for row, changes in edits.items():
        line = lines[row - 1]
        for start, end, replacement in sorted(changes, reverse=True):
            line = line[:start] + replacement + line[end:]
        lines[row - 1] = line
    candidate = ''.join(lines)
    if ast.dump(ast.parse(candidate, feature_version=(3, 11)), include_attributes=False) != ast.dump(tree, include_attributes=False):
        raise ValueError('Poe compaction changed the AST; refusing to create upload copy')
    compile(candidate, '<Poe upload>', 'exec')
    return candidate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    if source == output:
        raise SystemExit('Source and upload copy must be different files')
    text = source.read_text(encoding='utf-8')
    result = compact(text)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result, encoding='utf-8', newline='\n')
    print(f'{source.name}: {source.stat().st_size:,} bytes -> {output.stat().st_size:,} bytes, AST identical; {output}')


if __name__ == '__main__':
    main()
