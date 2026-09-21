"""Compute the full move manifest for lifting script code into src/.

Closes over FOUR dependency classes to a fixed point -- the lesson of the
first attempt, where a call-graph-only closure cost three corrections:
  1. call edges            2. def-time free variables
  3. default-arg values    4. cross-script imports (recursed into the source script)
Names imported from obed_edom.* are src->src and fine; names imported from a
sibling SCRIPT are pulled across and moved too, else src would import scripts/.
Over-inclusion is safe (moves an extra constant); under-inclusion is the bug.

usage: manifest_closure.py <git-rev> [<seed-test-file>] [--script NAME] [--extra A,B] [--stop A,B]

--stop names a DRIVER boundary: those names stay in the script and the closure
does not traverse through them. Use it for browser/CDP/async entry points and
injected-JS strings, which must never be moved into src.

The seed is what the test reads off the script module PLUS any --extra names in
scope by plan decision rather than test usage (e.g. _score_visible_movie_motion,
moved for the empty-crop fix though no pre-move test calls it).
"""
from __future__ import annotations
import ast, re, subprocess, sys
from collections import defaultdict

def git_show(rev, path):
    r = subprocess.run(["git", "show", f"{rev}:{path}"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None

class Mod:
    def __init__(self, rev, name):
        self.name = name
        self.src = git_show(rev, f"scripts/{name}.py")
        self.defs, self.imports = {}, {}
        if self.src is None:
            return
        for n in ast.parse(self.src).body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.defs[n.name] = n
            elif isinstance(n, (ast.Assign, ast.AnnAssign)):
                tgts = n.targets if isinstance(n, ast.Assign) else [n.target]
                for t in tgts:
                    for x in ast.walk(t):
                        if isinstance(x, ast.Name):
                            self.defs[x.id] = n
            elif isinstance(n, ast.ImportFrom) and n.module:
                for a in n.names:
                    self.imports[a.asname or a.name] = (n.module, a.name)

def loads(node):
    return {x.id for x in ast.walk(node) if isinstance(x, ast.Name)}

def closure(rev, root, seed, stop=frozenset()):
    mods, move, external = {}, defaultdict(set), defaultdict(set)
    def mod(n):
        if n not in mods:
            mods[n] = Mod(rev, n)
        return mods[n]
    todo = [(root, s) for s in seed]
    seen = set()
    while todo:
        m_name, name = todo.pop()
        if (m_name, name) in seen or name in stop:
            continue
        seen.add((m_name, name))
        m = mod(m_name)
        if name in m.defs:
            move[m_name].add(name)
            for dep in loads(m.defs[name]):
                if dep in m.defs or dep in m.imports:
                    todo.append((m_name, dep))
        elif name in m.imports:
            src_mod, src_name = m.imports[name]
            if src_mod.startswith("obed_edom") or src_mod.split(".")[0] in sys.stdlib_module_names:
                external[src_mod].add(src_name)
            elif mod(src_mod).src is not None:
                todo.append((src_mod, src_name))
            else:
                external[src_mod].add(src_name)
    return move, external, mods

def main():
    flagvals = {sys.argv[i + 1] for i, a in enumerate(sys.argv) if a in ("--script", "--extra", "--stop") and i + 1 < len(sys.argv)}
    args = [a for a in sys.argv[1:] if not a.startswith("--") and a not in flagvals]
    rev = args[0]
    test = args[1] if len(args) > 1 else "tests/test_p2_adversarial.py"
    root = "p2_recovery_html_adversarial"
    if "--script" in sys.argv:
        root = sys.argv[sys.argv.index("--script") + 1]
    ttxt = git_show(rev, test) or ""
    seed = set(re.findall(r"\bp2\.([A-Za-z_]\w*)", ttxt))
    if "--extra" in sys.argv:
        seed |= set(sys.argv[sys.argv.index("--extra") + 1].split(","))
    seed = sorted(seed)
    stop = frozenset(sys.argv[sys.argv.index("--stop") + 1].split(",")) if "--stop" in sys.argv else frozenset()
    seed = [s for s in seed if s not in stop]
    move, external, mods = closure(rev, root, seed, stop)
    if stop:
        print(f"driver boundary (--stop, left in script): {sorted(stop)}")
    print(f"rev={rev}  seed={len(seed)} names from {test}")
    total = 0
    for m_name in sorted(move, key=lambda k: (k != root, k)):
        names = sorted(move[m_name])
        fns = [n for n in names if isinstance(mods[m_name].defs[n], (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
        cst = [n for n in names if n not in fns]
        lines = sum(mods[m_name].defs[n].end_lineno - mods[m_name].defs[n].lineno + 1 for n in names)
        total += lines
        tag = "ROOT" if m_name == root else "CROSS-SCRIPT"
        print(f"\n[{tag}] scripts/{m_name}.py  -> {len(fns)} defs, {len(cst)} constants, {lines} lines")
        print("  defs:", ", ".join(fns))
        print("  consts:", ", ".join(cst))
    print(f"\nTOTAL to move: {total} lines")
    print("\nstays external (src->src or stdlib, fine):")
    for k in sorted(external):
        print(f"  {k}: {', '.join(sorted(external[k]))}")
    unresolved = [s for s in seed if s not in move.get(root, set()) and s not in mods[root].imports]
    if unresolved:
        print("\nWARNING seed names not found in root script:", unresolved)

if __name__ == "__main__":
    main()
