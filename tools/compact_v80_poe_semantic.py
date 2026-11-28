"""Whitespace-only compact POE payload, with exact AST identity as release gate.

No identifier renaming, constant compression, eval/exec, or runtime loader.
The readable audited source remains available and the formal POE header is kept.
"""
from pathlib import Path
import argparse
import ast
import hashlib
import io
import json
import token
import tokenize

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'tools/v80_vgit_release_candidate.py'
OUT=ROOT/'tools/v80_vgit_compact_candidate.py'
EXPECTED='ee980b865c8abf34867f01bbd7592249a0867eec51dc4ab351dbf654db71a8f5'
HEADER='# poe: name=Strategy-Signal-V80\n# poe: privacy_shield=half\n'


def tree(text): return ast.dump(ast.parse(text,feature_version=(3,11),type_comments=True),include_attributes=False)


def safe_gap(a,b):
    """Conservative lexical gaps. AST identity is a separate mandatory check."""
    x,y=a.string,b.string
    if not x or not y: return False
    if a.type in (tokenize.NAME,tokenize.NUMBER) and (b.type in (tokenize.NAME,tokenize.NUMBER,tokenize.STRING) or b.type==getattr(token,'FSTRING_START',-1)):
        return False
    if a.type in (tokenize.STRING,getattr(token,'FSTRING_END',-1)) and b.type in (tokenize.NAME,tokenize.NUMBER,tokenize.STRING): return False
    if a.type==tokenize.NUMBER and y.startswith('.'): return False
    if x.endswith('.') and b.type==tokenize.NUMBER: return False
    if a.type==tokenize.OP and b.type==tokenize.OP:
        if x[-1]+y[0] in {'**','//','<<','>>','==','!=','<=','>=',':=','->','+=','-=','*=','/=','%=','&=','|=','^=','@=','..'}: return False
    # Avoid changing the literal text of f-strings (including debug expressions)
    # by retaining source whitespace around f-string literal tokens.
    if a.type==getattr(token,'FSTRING_MIDDLE',-1) or b.type==getattr(token,'FSTRING_MIDDLE',-1): return False
    return True


SIMPLE=(ast.Expr,ast.Assign,ast.AnnAssign,ast.AugAssign,ast.Return,ast.Delete,ast.Raise,ast.Assert,
        ast.Import,ast.ImportFrom,ast.Global,ast.Nonlocal,ast.Pass,ast.Break,ast.Continue)


def pack_simple_statements(text):
    """Join only statements already adjacent in the same AST suite."""
    root=ast.parse(text,feature_version=(3,11)); lines=text.splitlines(keepends=True); offsets=[0]
    for line in lines: offsets.append(offsets[-1]+len(line))
    def pos(row,col):
        return offsets[row-1]+len(lines[row-1].encode('utf8')[:col].decode('utf8'))
    gaps=set()
    for node in ast.walk(root):
        for _,items in ast.iter_fields(node):
            if not isinstance(items,list) or len(items)<2: continue
            for a,b in zip(items,items[1:]):
                if not isinstance(a,SIMPLE) or not isinstance(b,SIMPLE) or a.end_lineno>=b.lineno: continue
                left,right=pos(a.end_lineno,a.end_col_offset),pos(b.lineno,b.col_offset)
                if text[left:right].strip()=='' and '\n' in text[left:right]: gaps.add((left,right))
    parts=[];prev=0
    for left,right in sorted(gaps):
        if left<prev: raise RuntimeError('overlapping simple statement gaps')
        parts.extend((text[prev:left],';'));prev=right
    parts.append(text[prev:]);result=''.join(parts)
    if tree(result)!=tree(text): raise RuntimeError('Simple-statement packing altered AST')
    return result


def collapse_trivial_suites(text):
    """Inline a suite of simple statements only when its entire body is one line."""
    root=ast.parse(text,feature_version=(3,11)); lines=text.splitlines(keepends=True); offsets=[0]
    for line in lines: offsets.append(offsets[-1]+len(line))
    gaps=set()
    for node in ast.walk(root):
        for name,body in ast.iter_fields(node):
            if name not in ('body','orelse','finalbody') or not isinstance(body,list) or not body:continue
            if not all(isinstance(x,SIMPLE) for x in body):continue
            first=body[0]; last=body[-1]
            if first.lineno<2 or first.lineno!=last.end_lineno:continue
            header=lines[first.lineno-2].rstrip()
            if not header.endswith(':'):continue
            left=offsets[first.lineno-2]+len(header)
            right=offsets[first.lineno-1]+len(lines[first.lineno-1].encode('utf8')[:first.col_offset].decode('utf8'))
            if text[left:right].strip()=='' and '\n' in text[left:right]:gaps.add((left,right))
    parts=[];prev=0
    for left,right in sorted(gaps):
        if left<prev:raise RuntimeError('overlapping suite gaps')
        parts.append(text[prev:left]);prev=right
    parts.append(text[prev:]);result=''.join(parts)
    if tree(result)!=tree(text):raise RuntimeError('Simple suite packing altered AST')
    return result


def compact(text):
    before=tree(text)
    tokens=list(tokenize.generate_tokens(io.StringIO(text).readline))
    level=0; pairs=[]
    for t in tokens:
        if t.type==tokenize.COMMENT: continue
        if t.type==tokenize.INDENT:
            level+=1; pairs.append((t.type,' '*level))
        elif t.type==tokenize.DEDENT:
            level-=1; pairs.append((t.type,t.string))
        else: pairs.append((t.type,t.string))
    normalized=tokenize.untokenize(pairs)
    if tree(normalized)!=before: raise RuntimeError('Indent/comment normalization altered AST')
    toks=list(tokenize.generate_tokens(io.StringIO(normalized).readline))
    lines=normalized.splitlines(keepends=True); offsets=[0]
    for line in lines: offsets.append(offsets[-1]+len(line))
    def pos(p):
        row,col=p
        return offsets[row-1]+col if row-1<len(offsets) else len(normalized)
    ignored={tokenize.INDENT,tokenize.DEDENT,tokenize.NL,tokenize.NEWLINE,tokenize.ENDMARKER,tokenize.ENCODING}
    gaps=[]
    for a,b in zip(toks,toks[1:]):
        if a.type in ignored or b.type in ignored or a.end[0]!=b.start[0]:continue
        left,right=pos(a.end),pos(b.start)
        if right>left and normalized[left:right].strip()=='' and safe_gap(a,b):gaps.append((left,right))
    pieces=[]; prev=0
    for left,right in gaps:
        if left<prev: raise RuntimeError('overlapping token gaps')
        pieces.append(normalized[prev:left]);prev=right
    pieces.append(normalized[prev:]); result=HEADER+''.join(pieces).lstrip('\n')
    if tree(result)!=before: raise RuntimeError('Token whitespace minimization altered AST')
    result=pack_simple_statements(result)
    result=collapse_trivial_suites(result)
    if tree(result)!=before: raise RuntimeError('Final compact source altered AST')
    return result


def main(source=SOURCE,out=OUT):
    if source==SOURCE and not source.exists():
        source=ROOT/'research/data_quality/20261128_v80_vgit_release/readable_source.py'
    raw=source.read_bytes(); assert hashlib.sha256(raw).hexdigest()==EXPECTED
    text=raw.decode('utf8'); result=compact(text); out.write_text(result,encoding='utf8',newline='\n')
    report=dict(source_sha256=EXPECTED,compact_sha256=hashlib.sha256(out.read_bytes()).hexdigest(),source_bytes=len(raw),compact_bytes=out.stat().st_size,compact_json_utf8=len(json.dumps(result,ensure_ascii=False).encode()),compact_json_ascii=len(json.dumps(result,ensure_ascii=True).encode()),ast_equal=True,python_311_parse=True)
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--source',type=Path,default=SOURCE);p.add_argument('--out',type=Path,default=OUT);a=p.parse_args();main(a.source,a.out)
