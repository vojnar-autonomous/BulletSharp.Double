# Staging native binaries for `dotnet pack`

`BulletSharp.Double`'s NuGet package needs to carry a prebuilt `libbulletc`
for every RID it supports (currently `linux-x64` and `win-x64`), under
NuGet's standard `runtimes/{rid}/native/` convention. The .NET SDK then
picks the right one automatically for whoever installs the package — no
`.targets` file or manual wiring needed on their side.

There's no single machine that can build both: `linux-x64` comes from CI
(Ubuntu runner), `win-x64` from your own Windows build. Gather both here
before running `dotnet pack` — `BulletSharp.Double.csproj`'s `Pack` target
reads them from this folder by default and **fails the pack** if either is
missing, so you can't publish a package that's silently missing a platform.

1. **`linux-x64/native/libbulletc.so`** — download the `libbulletc-linux-x64`
   artifact from the latest successful `.NET Core` workflow run on `main`
   (GitHub → Actions → that run → Artifacts), unzip it, and place the `.so`
   here.
2. **`win-x64/native/libbulletc.dll`** — build it locally the usual way
   (`cmake -S libbulletc -B libbulletc/build -A x64` then
   `cmake --build libbulletc/build --config Release`), then copy
   `libbulletc/build/lib/Release/libbulletc.dll` here.
3. From the repo root: `dotnet pack BulletSharp/BulletSharp.Double.csproj -c Release`.
   The `.nupkg`/`.snupkg` land in `BulletSharp/bin/Release/`.
4. `dotnet nuget push BulletSharp/bin/Release/BulletSharp.Double.<version>.nupkg --api-key <key> --source https://api.nuget.org/v3/index.json`
   (and the matching `.snupkg` — `dotnet nuget push` sends both together
   when they're both present next to each other).

These files are gitignored (`.gitkeep` only) — re-gather them each release,
don't commit the binaries.
