# Staging native binaries for `dotnet pack`

`BulletSharp.Double`'s NuGet package needs to carry a prebuilt `libbulletc`
for every RID it supports (`linux-x64`, `linux-arm64`, `win-x64`,
`win-arm64`, `osx-x64`, `osx-arm64`), under NuGet's standard
`runtimes/{rid}/native/` convention. The .NET SDK then picks the right one
automatically for whoever installs the package -- no `.targets` file or
manual wiring needed on their side.

All six are built by CI (`.github/workflows/build-test-pack.yml`), one per
hosted runner OS/arch -- there's no single machine that can build all of
them locally. `BulletSharp.Double.csproj`'s `Pack` target reads them from
this folder by default and **fails the pack** if any is missing, so you
can't publish a package that's silently missing a platform.

## The easy way: let CI pack it

Trigger the workflow manually (GitHub -> Actions -> "Build native
libbulletc, test, and pack" -> Run workflow) on `main`. Its `pack` job
downloads all six native artifacts from the matching `build-and-test` legs
and runs the pack itself with `-p:ContinuousIntegrationBuild=true` (so the
symbol package doesn't embed the runner's checkout path). Download the
`nuget-packages` artifact from that run -- it's the `.nupkg`/`.snupkg`,
ready for `dotnet nuget push`, still entirely untouched by CI itself.

## The manual way

1. Download each `libbulletc-<rid>` artifact from the latest successful
   run on `main` (GitHub -> Actions -> that run -> Artifacts), unzip, and
   place under `<rid>/native/`:
   - `linux-x64/native/libbulletc.so`
   - `linux-arm64/native/libbulletc.so`
   - `win-x64/native/libbulletc.dll`
   - `win-arm64/native/libbulletc.dll`
   - `osx-x64/native/libbulletc.dylib`
   - `osx-arm64/native/libbulletc.dylib`
2. From the repo root: `dotnet pack BulletSharp/BulletSharp.Double.csproj -c Release -p:ContinuousIntegrationBuild=true`.
   The `.nupkg`/`.snupkg` land in `BulletSharp/bin/Release/`. If you don't
   also have a local native build at `../libbulletc/build/` for your own
   OS (the separate check that's about running/testing this repo, not
   packing it), add `-p:SkipNativeLibBulletCCheck=true`.
3. `dotnet nuget push BulletSharp/bin/Release/BulletSharp.Double.<version>.nupkg --api-key <key> --source https://api.nuget.org/v3/index.json`
   (and the matching `.snupkg` -- `dotnet nuget push` sends both together
   when they're both present next to each other).

These files are gitignored (`.gitkeep` only) -- re-gather them each
release, don't commit the binaries.
