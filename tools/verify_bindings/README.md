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

Assumes bullet3 is present at `<repo-root>/bullet3` (a git submodule --
run `git submodule update --init` if it's empty), same layout
`libbulletc`'s own CMakeLists.txt expects.

Runs on Linux, macOS and Windows. You need two things, and **their major
versions must match each other** -- a mismatch fails loudly at startup
with an `undefined symbol` error (clang's C API only ever grows, so an
older piece paired with a newer one is fine; two pieces more than a couple
of major versions apart, in either direction, risks a missing symbol):

1. A native `libclang` shared library. `find_libclang()` (top of the
   script) looks in common install locations per OS, then the
   `LIBCLANG_PATH` env var as an override, then falls back to
   clang.cindex's own default search. The script prints which path it
   picked (or that it found none) on startup.

   - **Linux**: usually already present if `clang`/`clang++` are installed
     (`apt install clang` / `dnf install clang` / etc.) -- looked for under
     `/usr/lib/<arch>/`, `/usr/lib/llvm-*/lib/`, `/usr/lib/`.
   - **macOS**: Xcode Command Line Tools (`xcode-select --install`) already
     ship one; Homebrew's `brew install llvm` is also checked.
   - **Windows**: install LLVM for Windows
     (https://github.com/llvm/llvm-project/releases, the
     `LLVM-*-win64.exe` installer) -- picked up from
     `C:\Program Files\LLVM\bin\libclang.dll`. **Don't** use the `libclang`
     PyPI package as your source for this DLL: as of writing it's stuck at
     18.1.1 (unmaintained for newer LLVM releases), so if pip gives you
     newer `clang` Python bindings alongside it you get exactly the
     mismatch this section warns about. The official installer always has
     a current release.

   Note: the `libclang` package installs its own `clang/cindex.py` into the
   *same* `clang` Python package namespace as the `clang` package below --
   installing both is a namespace collision (whichever installs last wins,
   silently). Pick one approach: either `libclang` alone (self-contained,
   simplest, but capped at the old 18.1.1 it bundles) or LLVM-for-Windows
   plus the separate `clang` package below (current, but two installs).
   Don't mix them.

2. The `clang` Python package -- pure Python, no compiled extension, so it
   installs on any Python version regardless of what's available for (1):

       pip install clang==<major>.<minor>.<patch>

   Pick the version whose **major** number matches whatever LLVM you
   installed in step 1 (LLVM 20.x -> `clang==20.1.5`, LLVM 21.x ->
   `clang==21.1.7`, etc. -- `pip index versions clang` lists what's on
   PyPI). Do not just `pip install clang` unpinned: it grabs the latest,
   which may be newer than the LLVM release you actually have installed.

   If you installed LLVM 20 or newer in step 1, pinning to an old
   `clang==18.1.8` is the wrong direction (older bindings are fine against
   a newer native lib, but there's no reason to undershoot -- just match
   it) -- use `clang==20.1.x`/`21.1.x` etc. to fit whatever you actually have.

If step 1 isn't found automatically, set it explicitly:

    # Windows (PowerShell)
    $env:LIBCLANG_PATH = "C:\Program Files\LLVM\bin\libclang.dll"
    # Linux/macOS
    export LIBCLANG_PATH=/path/to/libclang.so

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
