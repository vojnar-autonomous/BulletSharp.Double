# verify_bindings

Cross-checks type signatures across the three layers of the binding:

    bullet3 (native engine)  <-->  libbulletc (C ABI adapter)  <-->  C# P/Invoke

For every exported libbulletc wrap function, resolves the actual bullet3
method/field it calls by reading the call site in the wrap `.cpp` (not by
guessing from the function's name), then compares canonical
(macro/typedef-resolved) types on both boundaries:

1. wrap signature vs. the real bullet3 declaration it invokes
   -> catches ABI mismatches like the btSoftBodySolver float/btScalar bug.
2. wrap `.h` declared signature vs. the matching `UnsafeNativeMethods.cs`
   P/Invoke declaration (matched by exported symbol name)
   -> catches drift between the native export and the managed import
      (missing/extra parameters, wrong overload bound, etc).

Only primitive/scalar types (float, double, int, bool, enums, ...) are
compared strictly -- pointers, references, structs and templates are
expected to change shape across the boundary by design (object* -> IntPtr,
btVector3 -> Vector3, ...) so they are recorded in the report but not
flagged as mismatches.

## Requirements

Assumes bullet3 is checked out as a sibling directory (`../../../bullet3`
relative to this script, i.e. next to this fork's own repo root -- same
layout `libbulletc`'s own CMakeLists.txt expects).

    pip install --break-system-packages 'clang==18.1.8'

(pin the `clang` python package to the same major version as the system
`libclang`; adjust `LIBCLANG_PATH` at the top of the script if your
system's libclang lives elsewhere).

## Usage

    python3 verify_bindings.py [--out report.csv]

Prints a summary (counts of scalar mismatches / unresolved call sites / no
C# counterpart) and writes the full matched+mismatched map to a CSV.

## Known limitations

- Call-site resolution only handles the common single-statement patterns
  (a single method call, a single field read/write). Wrap functions with
  more complex bodies (loops, multiple calls, manual array marshalling via
  the `BTVECTOR3_IN`/`conversion.h` macros) are reported as `UNRESOLVED` for
  manual review rather than guessed at.
- Non-scalar types (pointers, btVector3, templates, enums) are recorded but
  not strictly compared -- auditing those needs a human read of the
  `wrap_params`/`bullet3_*` columns in the CSV.
