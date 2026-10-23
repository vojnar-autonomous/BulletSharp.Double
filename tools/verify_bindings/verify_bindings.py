#!/usr/bin/env python3
"""
Cross-checks type signatures across the three layers of the BulletSharp.Double
binding:

    bullet3 (native engine)  <-->  libbulletc (C ABI adapter)  <-->  C# P/Invoke

For every exported libbulletc wrap function, this resolves the actual bullet3
method/field it calls (by reading the call site in the wrap .cpp, not by
guessing from the function's name) and compares canonical (macro/typedef
resolved) types on both boundaries:

  1. wrap signature vs. the real bullet3 declaration it invokes
     -> catches ABI mismatches like the btSoftBodySolver float/btScalar bug.
  2. wrap .h declared signature vs. the matching UnsafeNativeMethods.cs
     P/Invoke declaration (matched 1:1 by exported symbol name)
     -> catches drift between the native export and the managed import.

Only primitive/scalar types (float, double, int, bool, enums, ...) are
compared strictly, since those are the class of bug we are hunting (silent
widening/narrowing or outright ABI corruption). Pointers, references, structs
and templates are expected to change shape across the boundary by design
(object* -> IntPtr, btVector3 -> Vector3, ...) so they are recorded for the
map but not flagged as mismatches.

Usage:
    python3 verify_bindings.py [--out report.csv] [--full]

Requires: pip install --break-system-packages 'clang==18.1.8' (must match the
major version of the system libclang; adjust LIBCLANG_PATH below if needed).
"""
import argparse
import csv
import glob
import os
import re
import sys

import clang.cindex as ci

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LIBCLANG_PATH = "/usr/lib/x86_64-linux-gnu/libclang-18.so.18"

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LIBBULLETC_SRC = os.path.join(REPO_ROOT, "libbulletc", "src")
CSHARP_FILE = os.path.join(REPO_ROOT, "BulletSharp", "UnsafeNativeMethods.cs")

# bullet3 is checked out as a sibling repo (../bullet3 relative to this fork),
# same layout libbulletc's own CMakeLists.txt expects.
BULLET3_ROOT = os.path.abspath(os.path.join(REPO_ROOT, "..", "bullet3"))

CLANG_ARGS = [
    "-x", "c++", "-std=c++14", "-DBT_USE_DOUBLE_PRECISION",
    f"-I{LIBBULLETC_SRC}",
    f"-I{os.path.join(BULLET3_ROOT, 'src')}",
    f"-I{os.path.join(BULLET3_ROOT, 'Extras', 'Serialize')}",
    f"-I{os.path.join(BULLET3_ROOT, 'Extras', 'Serialize', 'BulletFileLoader')}",
    f"-I{os.path.join(BULLET3_ROOT, 'Extras', 'Serialize', 'BulletWorldImporter')}",
    f"-I{os.path.join(BULLET3_ROOT, 'Extras', 'Serialize', 'BulletXmlWorldImporter')}",
    f"-I{os.path.join(BULLET3_ROOT, 'Extras', 'HACD')}",
]

# ---------------------------------------------------------------------------
# Type classification / normalization
# ---------------------------------------------------------------------------

# Canonical C/C++ scalar spellings -> normalized scalar name.
CPP_SCALAR_MAP = {
    "float": "float",
    "double": "double",
    "bool": "bool",
    "int": "int32",
    "unsigned int": "uint32",
    "short": "int16",
    "unsigned short": "uint16",
    "long": "int64",       # bullet3/libbulletc don't rely on LP64 vs LLP64 edge cases here
    "unsigned long": "uint64",
    "long long": "int64",
    "unsigned long long": "uint64",
    "char": "int8",
    "signed char": "int8",
    "unsigned char": "uint8",
    "void": "void",
}

# C# spellings -> normalized scalar name (same target namespace as above).
CS_SCALAR_MAP = {
    "float": "float",
    "double": "double",
    "bool": "bool",
    "int": "int32",
    "uint": "uint32",
    "short": "int16",
    "ushort": "uint16",
    "long": "int64",
    "ulong": "uint64",
    "byte": "uint8",
    "sbyte": "int8",
    "char": "int16",
    "void": "void",
}


def classify_cpp_type(canonical_spelling):
    """Returns (category, normalized_name) for a clang canonical type spelling."""
    s = canonical_spelling.strip()
    s = re.sub(r"\bconst\b", "", s).strip()
    is_ptr_or_ref = s.endswith("*") or s.endswith("&")
    base = s.rstrip("*&").strip()
    base = re.sub(r"\bconst\b", "", base).strip()

    if base in CPP_SCALAR_MAP and not is_ptr_or_ref:
        return "scalar", CPP_SCALAR_MAP[base]
    if base.startswith("enum "):
        return "enum", base[len("enum "):].strip()
    if is_ptr_or_ref:
        return "handle", base
    if "<" in base:
        return "template", base
    return "other", base


def classify_cs_type(cs_spelling):
    s = cs_spelling.strip()
    s = re.sub(r"^(ref|out|in)\s+", "", s)
    if s == "IntPtr":
        return "handle", "IntPtr"
    if s in CS_SCALAR_MAP:
        return "scalar", CS_SCALAR_MAP[s]
    if s.endswith("[]"):
        return "array", s[:-2]
    return "other", s


# ---------------------------------------------------------------------------
# C# UnsafeNativeMethods.cs extraction
# ---------------------------------------------------------------------------

PINVOKE_RE = re.compile(
    r"public\s+static\s+extern\s+([\w.]+(?:\s*\[\])?)\s+(\w+)\s*\(([^)]*)\)\s*;",
    re.MULTILINE,
)
# Strip C#-attribute decorations like [In, Out] before splitting a param list,
# so the comma *inside* the attribute doesn't get mistaken for a param separator.
ATTR_RE = re.compile(r"\[[^\]]*\]")
PARAM_RE = re.compile(r"\s*(?:ref\s+|out\s+|in\s+)?([\w.]+(?:\s*\[\])?)\s+(\w+)\s*$")


def split_params(params_str):
    """Split a C# parameter list on top-level commas, ignoring commas inside
    [Attribute, List] decorations."""
    cleaned = ATTR_RE.sub("", params_str)
    return [p for p in cleaned.split(",")]


def extract_csharp_pinvoke(path):
    """Returns name -> list of overloads (each {return, params}), since
    BulletSharp P/Invoke declarations are frequently overloaded by name
    (e.g. double[] vs Vector3[] variants of the same native entry point)."""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    result = {}
    for m in PINVOKE_RE.finditer(text):
        ret_type, name, params_str = m.groups()
        params = []
        if params_str.strip():
            for p in split_params(params_str):
                if not p.strip():
                    continue
                pm = PARAM_RE.match(p)
                if pm:
                    ptype, pname = pm.groups()
                    params.append((pname, ptype.strip()))
                else:
                    params.append((None, p.strip()))
        result.setdefault(name, []).append({"return": ret_type.strip(), "params": params})
    return result


# ---------------------------------------------------------------------------
# libbulletc wrap .h extraction (declared EXPORT signatures)
# ---------------------------------------------------------------------------

def extract_header_exports(tu, h_filename):
    result = {}
    for node in tu.cursor.get_children():
        if node.kind != ci.CursorKind.FUNCTION_DECL:
            continue
        if not node.location.file or os.path.basename(node.location.file.name) != h_filename:
            continue
        params = [(p.spelling, p.type.get_canonical().spelling) for p in node.get_arguments()]
        result[node.spelling] = {
            "return": node.result_type.get_canonical().spelling,
            "params": params,
        }
    return result


# ---------------------------------------------------------------------------
# libbulletc wrap .cpp extraction + call-site resolution
# ---------------------------------------------------------------------------

def _is_plain_assignment(binop_node):
    """True if a BINARY_OPERATOR cursor is a plain '=' (not '==', '+=', ...)."""
    toks = list(binop_node.get_tokens())
    # find the first top-level '=' token that isn't part of '==', '!=', '<=', '>=', etc.
    for i, t in enumerate(toks):
        if t.spelling == "=":
            prev = toks[i - 1].spelling if i > 0 else ""
            nxt = toks[i + 1].spelling if i + 1 < len(toks) else ""
            if prev not in ("!", "<", ">", "=") and nxt != "=":
                return True
    return False


def find_resolved_refs(node, acc, role="other"):
    """Collects every CALL_EXPR / MEMBER_REF_EXPR inside a function body whose
    declaration resolves outside libbulletc (i.e. into bullet3 itself).

    `role` tags *why* the comparison should use the wrap's return type
    ('getter': this value flows out as the function's return value) vs. its
    parameter/value type ('setter': this value is being written into a
    bullet3 field) vs. 'other' (discard the result, only params matter;
    e.g. a bare `obj->predictMotion(x);` call statement).
    """
    if node.kind == ci.CursorKind.RETURN_STMT:
        for c in node.get_children():
            find_resolved_refs(c, acc, role="getter")
        return

    if node.kind == ci.CursorKind.BINARY_OPERATOR and _is_plain_assignment(node):
        children = list(node.get_children())
        if len(children) == 2:
            lhs, rhs = children
            rhs_type = rhs.type.get_canonical().spelling
            # LHS: does it resolve to a bullet3 field?
            lhs_target = lhs
            # unwrap implicit casts / parens on the LHS
            while lhs_target.kind in (ci.CursorKind.UNEXPOSED_EXPR,):
                inner = list(lhs_target.get_children())
                if not inner:
                    break
                lhs_target = inner[0]
            if lhs_target.kind == ci.CursorKind.MEMBER_REF_EXPR:
                ref = lhs_target.referenced
                if ref is not None and ref.location.file is not None and "libbulletc" not in ref.location.file.name:
                    acc.append(("setter", ref, rhs_type))
            for c in children:
                find_resolved_refs(c, acc, role="other")
            return

    if node.kind in (ci.CursorKind.CALL_EXPR, ci.CursorKind.MEMBER_REF_EXPR):
        ref = node.referenced
        if ref is not None and ref.location.file is not None:
            fname = ref.location.file.name
            if "libbulletc" not in fname:
                tag = "getter" if role == "getter" else ("call" if node.kind == ci.CursorKind.CALL_EXPR else "field_read")
                acc.append((tag, ref, None))
    for c in node.get_children():
        find_resolved_refs(c, acc, role=role if node.kind != ci.CursorKind.CALL_EXPR else "other")


def extract_wrap_cpp(idx, cpp_path):
    """Returns dict: wrap_function_name -> {
         return, params:[(name,canon)], calls:[{kind, name, class, return, params}]
    }"""
    fname = os.path.basename(cpp_path)
    tu = idx.parse(cpp_path, args=CLANG_ARGS)
    errors = [d for d in tu.diagnostics if d.severity >= ci.Diagnostic.Error]

    out = {}
    for node in tu.cursor.get_children():
        if node.kind != ci.CursorKind.FUNCTION_DECL or not node.is_definition():
            continue
        if not node.location.file or os.path.basename(node.location.file.name) != fname:
            continue

        params = [(p.spelling, p.type.get_canonical().spelling) for p in node.get_arguments()]
        refs_raw = []
        find_resolved_refs(node, refs_raw)

        calls = []
        seen = set()
        for tag, ref, extra in refs_raw:
            key = (tag, ref.spelling, ref.location.file.name if ref.location.file else None, ref.location.line)
            if key in seen:
                continue
            seen.add(key)
            semparent = ref.semantic_parent
            cls = semparent.spelling if semparent is not None else None
            if tag in ("getter", "call"):
                rparams = [(p.spelling, p.type.get_canonical().spelling) for p in ref.get_arguments()] \
                    if ref.kind == ci.CursorKind.CXX_METHOD or ref.kind == ci.CursorKind.FUNCTION_DECL else []
                rret = ref.result_type.get_canonical().spelling if hasattr(ref, "result_type") and ref.kind in (
                    ci.CursorKind.CXX_METHOD, ci.CursorKind.FUNCTION_DECL) else ref.type.get_canonical().spelling
                # getter via plain field read (not a call): use field type as both
                if ref.kind == ci.CursorKind.FIELD_DECL:
                    rret = ref.type.get_canonical().spelling
                    if ref.is_bitfield() and ref.get_bitfield_width() == 1:
                        rret = "bool"  # a 1-bit bitfield IS a bool, regardless of its storage type
                    rparams = []
            elif tag == "field_read":
                rparams = []
                rret = ref.type.get_canonical().spelling
                if ref.kind == ci.CursorKind.FIELD_DECL and ref.is_bitfield() and ref.get_bitfield_width() == 1:
                    rret = "bool"  # a 1-bit bitfield IS a bool, regardless of its storage type
            elif tag == "setter":
                rparams = []
                rret = ref.type.get_canonical().spelling  # the field's own declared type
                if ref.kind == ci.CursorKind.FIELD_DECL and ref.is_bitfield() and ref.get_bitfield_width() == 1:
                    rret = "bool"
            else:
                rparams = []
                rret = ""
            calls.append({
                "exprkind": tag,
                "name": ref.spelling,
                "class": cls,
                "return": rret,
                "value_type": extra,  # only set for 'setter': RHS expression's canonical type
                "params": rparams,
            })

        out[node.spelling] = {
            "return": node.result_type.get_canonical().spelling,
            "params": params,
            "calls": calls,
            "file": fname,
        }
    return out, [d.spelling for d in errors]


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def scalar_compare(cpp_canon, cs_type):
    """Returns 'MATCH' / 'MISMATCH' / 'SKIP' (not both scalar -> no strict verdict)."""
    cpp_cat, cpp_norm = classify_cpp_type(cpp_canon)
    cs_cat, cs_norm = classify_cs_type(cs_type)
    if cpp_cat != "scalar" or cs_cat != "scalar":
        return "SKIP", cpp_norm, cs_norm
    return ("MATCH" if cpp_norm == cs_norm else "MISMATCH"), cpp_norm, cs_norm


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "binding_report.csv"))
    args = ap.parse_args()

    ci.Config.set_library_file(LIBCLANG_PATH)
    idx = ci.Index.create()

    csharp = extract_csharp_pinvoke(CSHARP_FILE)

    rows = []
    parse_errors = []

    cpp_files = sorted(glob.glob(os.path.join(LIBBULLETC_SRC, "*_wrap.cpp")))
    for cpp_path in cpp_files:
        h_path = cpp_path[:-4] + ".h"
        wrap_funcs, errs = extract_wrap_cpp(idx, cpp_path)
        if errs:
            parse_errors.append((os.path.basename(cpp_path), errs[0]))
            continue

        header_exports = {}
        if os.path.exists(h_path):
            tu_h = idx.parse(h_path, args=CLANG_ARGS)
            header_exports = extract_header_exports(tu_h, os.path.basename(h_path))

        for fn_name, wrap in wrap_funcs.items():
            cs = csharp.get(fn_name)
            hdr = header_exports.get(fn_name)

            # --- native wrap vs bullet3 (via resolved call site) ---
            native_status = "UNRESOLVED"
            bullet3_class = bullet3_method = ""
            bullet3_return = ""
            native_mismatches = []

            calls = wrap["calls"]
            # Prefer a call whose arity matches the wrap function's arity - 1 (minus obj)
            primary = None
            if len(calls) == 1:
                primary = calls[0]
            elif len(calls) > 1:
                # heuristic: pick the one whose param count matches best
                wrap_param_count = len(wrap["params"])
                primary = min(
                    calls,
                    key=lambda c: abs(len(c["params"]) - (wrap_param_count - 1)),
                )

            if primary is not None:
                bullet3_class = primary["class"] or ""
                bullet3_method = primary["name"]
                bullet3_return = primary["return"]
                native_status = "RESOLVED" if len(calls) == 1 else "RESOLVED_AMBIGUOUS"

                if primary["exprkind"] == "setter":
                    # field's declared type vs. the type of the expression written into it
                    # (almost always the wrap function's own incoming parameter) -- NOT the
                    # wrap function's return type, which is void for a setter.
                    cat_w, norm_w = classify_cpp_type(primary["value_type"] or "")
                    cat_b, norm_b = classify_cpp_type(bullet3_return)
                    if cat_w == "scalar" and cat_b == "scalar" and norm_w != norm_b:
                        native_mismatches.append(f"assigned value: wrap={norm_w} bullet3_field={norm_b}")
                else:
                    # getter / call / field_read: compare against the wrap function's return type
                    cat_w, norm_w = classify_cpp_type(wrap["return"])
                    cat_b, norm_b = classify_cpp_type(bullet3_return)
                    if cat_w == "scalar" and cat_b == "scalar" and norm_w != norm_b:
                        native_mismatches.append(f"return: wrap={norm_w} bullet3={norm_b}")

                    # param type compare position-by-position (skip the leading obj param on wrap side)
                    wrap_params_noobj = wrap["params"][1:] if wrap["params"] else []
                    bullet3_params = primary["params"]
                    if primary["exprkind"] == "call" and len(wrap_params_noobj) == len(bullet3_params):
                        for (wn, wt), (bn, bt) in zip(wrap_params_noobj, bullet3_params):
                            cat_w, norm_w = classify_cpp_type(wt)
                            cat_b, norm_b = classify_cpp_type(bt)
                            if cat_w == "scalar" and cat_b == "scalar" and norm_w != norm_b:
                                native_mismatches.append(f"param {wn}: wrap={norm_w} bullet3={norm_b}")

                if native_mismatches:
                    native_status = "SCALAR_MISMATCH"

            # --- wrap .h vs C# P/Invoke ---
            # BulletSharp frequently overloads one native entry point by C# name
            # (e.g. a double[] and a Vector3[] variant of the same wrap function),
            # so pick whichever declared overload's arity best matches the native
            # wrap signature before comparing types.
            cs_status = "NO_CSHARP_COUNTERPART"
            cs_mismatches = []
            wrap_params_for_cs = hdr["params"] if hdr else wrap["params"]
            if cs is not None:
                overload = min(cs, key=lambda o: abs(len(o["params"]) - len(wrap_params_for_cs)))
                cs_status = "OK"
                ret_for_cs = hdr["return"] if hdr else wrap["return"]
                st, cn, sn = scalar_compare(ret_for_cs, overload["return"])
                if st == "MISMATCH":
                    cs_mismatches.append(f"return: native={cn} cs={sn}")

                if len(wrap_params_for_cs) == len(overload["params"]):
                    for (wn, wt), (cn2, ct) in zip(wrap_params_for_cs, overload["params"]):
                        st, cnorm, snorm = scalar_compare(wt, ct)
                        if st == "MISMATCH":
                            cs_mismatches.append(f"param {wn}: native={cnorm} cs={snorm}")
                else:
                    cs_mismatches.append(
                        f"arity mismatch (closest overload): native={len(wrap_params_for_cs)} cs={len(overload['params'])}"
                    )
                if cs_mismatches:
                    cs_status = "SCALAR_MISMATCH"

            rows.append({
                "file": wrap["file"],
                "wrap_function": fn_name,
                "wrap_return": wrap["return"],
                "wrap_params": "; ".join(f"{n}:{t}" for n, t in wrap["params"]),
                "bullet3_class": bullet3_class,
                "bullet3_method": bullet3_method,
                "bullet3_return": bullet3_return,
                "native_status": native_status,
                "native_mismatches": " | ".join(native_mismatches),
                "cs_status": cs_status,
                "cs_mismatches": " | ".join(cs_mismatches),
            })

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        w.writeheader()
        for r in rows:
            w.writerow(r)

    total = len(rows)
    native_mismatch_n = sum(1 for r in rows if r["native_status"] == "SCALAR_MISMATCH")
    cs_mismatch_n = sum(1 for r in rows if r["cs_status"] == "SCALAR_MISMATCH")
    unresolved_n = sum(1 for r in rows if r["native_status"] == "UNRESOLVED")
    no_cs_n = sum(1 for r in rows if r["cs_status"] == "NO_CSHARP_COUNTERPART")

    print(f"Wrap functions analyzed: {total}")
    print(f"  native (wrap vs bullet3) scalar mismatches: {native_mismatch_n}")
    print(f"  C# (wrap vs P/Invoke) scalar mismatches:    {cs_mismatch_n}")
    print(f"  unresolved call site (manual review):       {unresolved_n}")
    print(f"  no C# counterpart found:                    {no_cs_n}")
    if parse_errors:
        print(f"\nFiles skipped due to parse errors ({len(parse_errors)}):")
        for fn, e in parse_errors:
            print(f"  {fn}: {e}")
    print(f"\nFull report written to {args.out}")


if __name__ == "__main__":
    main()
