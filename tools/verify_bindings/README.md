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

Runs on Linux, macOS and Windows. In every case you need:

1. The `clang` Python package, **pinned to the same major version as your
   system's native libclang** (a version mismatch fails loudly at startup
   with an `undefined symbol` error, so this is the #1 thing to check if
   setup breaks):

       pip install "clang==18.1.8"   # adjust the version, see below

2. A native `libclang` shared library somewhere `find_libclang()` (top of
   the script) can see. It checks common install locations per OS, then
   the `LIBCLANG_PATH` env var as an override, then falls back to
   clang.cindex's own default search. Nothing to configure if one of these
   finds it; the script prints which path it picked (or that it found
   none) on startup.

   - **Linux**: usually already present if `clang`/`clang++` are installed
     (`apt install clang` / `dnf install clang` / etc.) -- the script looks
     under `/usr/lib/<arch>/`, `/usr/lib/llvm-*/lib/`, `/usr/lib/`.
   - **macOS**: Xcode Command Line Tools (`xcode-select --install`) already
     ship one; Homebrew's `brew install llvm` is also checked.
   - **Windows**: easiest is `pip install libclang` (a separate PyPI
     package from `clang` above, despite the confusingly similar name) --
     it bundles a `libclang.dll` the script finds automatically via the
     installed package's own directory. Alternatively install LLVM for
     Windows (https://github.com/llvm/llvm-project/releases, the
     `LLVM-*-win64.exe` installer) and it's picked up from
     `C:\Program Files\LLVM\bin\libclang.dll`.

   If none of that works on your machine, find your `libclang` manually
   and set it explicitly:

       # Windows (PowerShell)
       $env:LIBCLANG_PATH = "C:\Program Files\LLVM\bin\libclang.dll"
       # Linux/macOS
       export LIBCLANG_PATH=/path/to/libclang.so

To find the right `clang` package version for whatever libclang you have,
match its major version number (18.x pairs with `libclang-18`, etc.) --
`pip index versions clang` lists what's on PyPI.

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
