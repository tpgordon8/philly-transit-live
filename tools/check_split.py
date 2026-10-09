#!/usr/bin/env python3
"""Check that the js/*.js split of index.html is a pure move (ARCHITECTURE.md section 14).

    python3 tools/check_split.py                 # compare against the last commit before the split (cc22b7e)
    python3 tools/check_split.py --base <rev>    # compare against another revision of index.html

Python 3 standard library only. The base revision's inline application script and the concatenation of the js files
named by the current index.html (in load order) are tokenised, comments dropped. Lines that carry the marker
/*@split*/ are wrapper lines (IIFE open and close, 'use strict', namespace imports and exports, forward-call shims,
the halt flag) and are removed from the js files first; the original's own IIFE wrapper lines are removed too. What is
left must be the same code, only rearranged:

  1. the sorted list of top-level function names is identical (duplicates included);
  2. the sorted list of top-level var names is identical;
  3. the code, cut into top-level chunks (a chunk ends where the bracket depth is 0 and the next token starts a new
     line), is the same multiset of non-whitespace token streams, so every function body is token-identical.

It also fails when a js file is over 600 lines, when the inline script left in index.html is 60 lines or more, when
a js file assigns a window property other than SEPTA or __SEPTA_TEST__, or when index.html lists a js file that does
not exist. Exit status 0 means all checks passed.
"""
import argparse
import collections
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_BASE = "cc22b7e"
MARK = "@split"
MAX_JS_LINES = 600
MAX_INLINE_LINES = 60
REGEX_PREV_WORDS = {"return", "typeof", "case", "in", "of", "delete", "void", "throw", "new", "else", "do", "instanceof"}
PUNCT3 = {"===", "!==", "**=", "<<=", ">>=", ">>>", "...", "&&=", "||=", "??="}
PUNCT2 = {"=>", "==", "!=", "<=", ">=", "&&", "||", "??", "?.", "++", "--", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<", ">>", "**"}


def tokenize(src):
    """Return [(text, start_line)] for every token, comments dropped. Regex literals are one token."""
    toks, i, n, line = [], 0, len(src), 1
    prev = None  # previous significant token text

    def regex_allowed():
        if prev is None:
            return True
        if prev in REGEX_PREV_WORDS:
            return True
        if prev[0].isalnum() or prev[0] in "_$" or prev[0] in "'\"":
            return False
        return prev not in (")", "]")

    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
            i += 1
        elif c in " \t\r":
            i += 1
        elif src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            if j < 0:
                raise SystemExit("unterminated comment at line %d" % line)
            line += src.count("\n", i, j)
            i = j + 2
        elif c in "'\"":
            j = i + 1
            while j < n and src[j] != c:
                if src[j] == "\\":
                    j += 1
                if src[j] == "\n":
                    raise SystemExit("unterminated string at line %d" % line)
                j += 1
            toks.append((src[i:j + 1], line))
            prev = src[i:j + 1]
            i = j + 1
        elif c == "`":
            j = i + 1
            while j < n and src[j] != "`":
                j += 2 if src[j] == "\\" else 1
            toks.append((src[i:j + 1], line))
            line += src.count("\n", i, j)
            prev = "'"
            i = j + 1
        elif c == "/" and regex_allowed():
            j, in_class = i + 1, False
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == "[":
                    in_class = True
                elif src[j] == "]":
                    in_class = False
                elif src[j] == "/" and not in_class:
                    break
                elif src[j] == "\n":
                    raise SystemExit("unterminated regex at line %d" % line)
                j += 1
            j += 1
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            toks.append((src[i:j], line))
            prev = "'"
            i = j
        elif c.isalpha() or c in "_$":
            j = i + 1
            while j < n and (src[j].isalnum() or src[j] in "_$"):
                j += 1
            toks.append((src[i:j], line))
            prev = src[i:j]
            i = j
        elif c.isdigit() or (c == "." and i + 1 < n and src[i + 1].isdigit()):
            j = i + 1
            while j < n and (src[j].isalnum() or src[j] == "." or (src[j] in "+-" and src[j - 1] in "eE" and not src[i:j].lower().startswith("0x"))):
                j += 1
            toks.append((src[i:j], line))
            prev = src[i:j]
            i = j
        else:
            for k in (3, 2, 1):
                if src[i:i + k] in PUNCT3 | PUNCT2 or k == 1:
                    toks.append((src[i:i + k], line))
                    prev = src[i:i + k]
                    i += k
                    break
    return toks


def chunks(toks):
    """Cut tokens into top-level chunks. Returns [[tokens...]]."""
    out, cur, depth = [], [], 0
    for idx, (t, ln) in enumerate(toks):
        if cur and depth == 0 and ln != cur[-1][1] and cur[-1][1] != ln:
            out.append(cur)
            cur = []
        cur.append((t, ln))
        if t in "([{":
            depth += 1
        elif t in ")]}":
            depth -= 1
    if cur:
        out.append(cur)
    if depth != 0:
        raise SystemExit("unbalanced brackets (depth %d at end)" % depth)
    return out


def top_names(chunk_list):
    funcs, vars_ = [], []
    for ch in chunk_list:
        texts = [t for t, _ in ch]
        depth = 0
        want_var = False
        for k, t in enumerate(texts):
            if t in "([{":
                depth += 1
            elif t in ")]}":
                depth -= 1
            elif depth == 0 and t == "function" and k + 1 < len(texts) and re.match(r"[A-Za-z_$][\w$]*$", texts[k + 1]) and (k == 0 or texts[k - 1] in (";", "}")):
                funcs.append(texts[k + 1])
            elif depth == 0 and t in ("var", "let", "const") and (k == 0 or texts[k - 1] in (";", "}")):
                want_var = True
                vars_.append(texts[k + 1])
            elif depth == 0 and want_var and t == ",":
                vars_.append(texts[k + 1])
            elif depth == 0 and t == ";":
                want_var = False
    return sorted(funcs), sorted(vars_)


def base_script(rev):
    try:
        html = subprocess.run(["git", "show", "%s:index.html" % rev], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    except subprocess.CalledProcessError as e:
        raise SystemExit("cannot read index.html at %s: %s" % (rev, e.stderr.strip()))
    a = html.index("<script>\n(function(){")
    b = html.index("</script>", a)
    lines = html[a + len("<script>\n"):b].split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    if lines[0] != "(function(){" or lines[1] != "'use strict';" or lines[-1] != "})();":
        raise SystemExit("base script does not have the expected IIFE wrapper lines")
    return "\n".join(lines[2:-1])


def current_js():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    files = re.findall(r'<script src="(js/[^"]+)"', html)
    inline = [m for m in re.findall(r"<script>\n(.*?)</script>", html, flags=re.S)]
    return html, files, inline


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=DEFAULT_BASE, help="revision holding the unsplit index.html (default %(default)s)")
    args = ap.parse_args()
    problems = []
    html, files, inline = current_js()
    if not files:
        raise SystemExit("index.html loads no js/*.js files")

    base = base_script(args.base)
    new_parts, wrapper_lines = [], 0
    for f in files:
        p = ROOT / f
        if not p.exists():
            problems.append("index.html lists %s but the file does not exist" % f)
            continue
        text = p.read_text(encoding="utf-8")
        nlines = text.count("\n")
        if nlines > MAX_JS_LINES:
            problems.append("%s has %d lines (limit %d)" % (f, nlines, MAX_JS_LINES))
        kept = []
        for ln in text.split("\n"):
            if MARK in ln:
                wrapper_lines += 1
            else:
                kept.append(ln)
        code = "\n".join(kept)
        new_parts.append(code)
        for m in re.finditer(r"\bwindow\.([A-Za-z_$][\w$]*)\s*=(?!=)", code):
            if m.group(1) not in ("__SEPTA_TEST__",):
                problems.append("%s assigns window.%s" % (f, m.group(1)))
        for ln in text.split("\n"):
            if MARK in ln and re.search(r"\bwindow\.(?!SEPTA\b)[A-Za-z_$]", ln):
                problems.append("%s wrapper line touches window other than SEPTA: %s" % (f, ln.strip()[:80]))
    new_all = "\n".join(new_parts)

    inline_lines = sum(s.count("\n") + 1 for s in inline)
    if inline_lines >= MAX_INLINE_LINES:
        problems.append("index.html keeps %d inline script lines (limit %d)" % (inline_lines, MAX_INLINE_LINES - 1))

    b_toks, n_toks = tokenize(base), tokenize(new_all)
    b_chunks, n_chunks = chunks(b_toks), chunks(n_toks)
    bf, bv = top_names(b_chunks)
    nf, nv = top_names(n_chunks)
    if bf != nf:
        problems.append("top-level function names differ: only before %s, only after %s" % (
            sorted((collections.Counter(bf) - collections.Counter(nf)).elements()),
            sorted((collections.Counter(nf) - collections.Counter(bf)).elements())))
    if bv != nv:
        problems.append("top-level var names differ: only before %s, only after %s" % (
            sorted((collections.Counter(bv) - collections.Counter(nv)).elements()),
            sorted((collections.Counter(nv) - collections.Counter(bv)).elements())))
    bc = collections.Counter(" ".join(t for t, _ in ch) for ch in b_chunks)
    nc = collections.Counter(" ".join(t for t, _ in ch) for ch in n_chunks)
    if bc != nc:
        for label, diff in (("only before", bc - nc), ("only after", nc - bc)):
            for chunk_text, cnt in list(diff.items())[:5]:
                problems.append("code chunk %s (x%d): %s ..." % (label, cnt, chunk_text[:140]))
        problems.append("code differs: %d chunk(s) only before, %d only after" % (sum((bc - nc).values()), sum((nc - bc).values())))

    print("base %s: %d functions, %d vars, %d chunks, %d tokens" % (args.base, len(bf), len(bv), len(b_chunks), len(b_toks)))
    print("now  %s: %d functions, %d vars, %d chunks, %d tokens (%d wrapper lines ignored)" % (
        ", ".join(f.split("/")[-1] for f in files), len(nf), len(nv), len(n_chunks), len(n_toks), wrapper_lines))
    print("inline script lines left in index.html: %d" % inline_lines)
    if problems:
        print("FAIL")
        for p in problems:
            print(" -", p)
        return 1
    print("OK: pure move (same functions, same vars, same token streams)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
