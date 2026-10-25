# BulletSharp.Double

Double-precision C# bindings for the [Bullet Physics](https://github.com/bulletphysics/bullet3) engine (bullet3), built and maintained by [Vojnar Autonomous](https://vojnarautonomous.com/).

Idiomatic, SWIG-like P/Invoke bindings onto bullet3's classic collision and dynamics API - collision shapes and algorithms, dynamics worlds and rigid bodies (including multithreaded variants), constraints, vehicle raycasting, the kinematic character controller, soft bodies and multibody dynamics, and `.bullet` world (de)serialization - compiled with `BT_USE_DOUBLE_PRECISION`, so every scalar and vector component carries full IEEE-754 double precision end to end: from the managed API, through the native P/Invoke boundary, into bullet3 itself.

Ships as a single package with prebuilt native binaries for six platforms.
No local CMake build is needed to consume it.

## Install

```
dotnet add package BulletSharp.Double
```

## Supported platforms

| OS      | x64 | ARM64 |
|---------|-----|-------|
| Windows | ✅  | ✅    |
| Linux   | ✅  | ✅    |
| macOS   | ✅  | ✅    |

Targets `net8.0` and `netstandard2.1`.

## Quick start

```csharp
using BulletSharp;
using BulletSharp.Math;

var conf = new DefaultCollisionConfiguration();
var dispatcher = new CollisionDispatcher(conf);
var broadphase = new DbvtBroadphase();
var solver = new SequentialImpulseConstraintSolver();
var world = new DiscreteDynamicsWorld(dispatcher, broadphase, solver, conf);
world.Gravity = new Vector3(0, -9.81, 0);

// static ground
var groundShape = new BoxShape(50, 1, 50);
var ground = new RigidBody(new RigidBodyConstructionInfo(
    0.0, new DefaultMotionState(Matrix.Translation(0, -1, 0)), groundShape, Vector3.Zero));
world.AddRigidBody(ground);

// falling sphere
var sphereShape = new SphereShape(1.0);
var sphereInfo = new RigidBodyConstructionInfo(
    1.0, new DefaultMotionState(Matrix.Translation(0, 10, 0)), sphereShape, Vector3.Zero);
sphereInfo.LocalInertia = sphereShape.CalculateLocalInertia(1.0);
var sphere = new RigidBody(sphereInfo);
world.AddRigidBody(sphere);

for (int i = 0; i < 180; i++)
{
    world.StepSimulation(1.0 / 60.0);
    if (i % 30 == 0)
        Console.WriteLine($"t={i / 60.0:F2}s  y={sphere.MotionState.WorldTransform.Origin.Y:F3}");
}

world.Dispose();
```

Prints the sphere's height every half second as it falls under gravity and settles on the ground (`y` dropping from `10` toward its resting height of `1`, the sphere's radius).

More complete examples - vehicles, ragdolls, soft bodies, character controllers, serialization, multithreading - are in [Demos](Demos).
They build against a local native `libbulletc`; see [artifacts/runtimes/README.md](artifacts/runtimes/README.md) for how to get one.

## Why double precision

We needed Bullet in C# with double precision to run a planetary-scale simulation - geo-referenced world coordinates, long flight times, positions far from any origin.
That's a harder ask for .NET than it sounds: the common C# physics options either don't go there (Jitter2 is float at its core; its double-precision build, `Jitter2.Double`, is a separate variant of the same young, much smaller engine) or only go halfway (Jolt compiles positions as double but keeps velocities, quaternions and "all internal calculations" in float, per its own maintainer).
Meanwhile pybullet - the official Python wrapper for this same Bullet - has shipped double precision unconditionally for years. .NET just never got the equivalent.
So we built it: BulletSharp.Double wraps bullet3 itself compiled with `BT_USE_DOUBLE_PRECISION` and keeps every scalar double end to end, including across the native P/Invoke boundary - verified by [`tools/verify_bindings`](tools/verify_bindings), a dedicated correctness checker that cross-references the native, P/Invoke, and C# signatures.

## Building from source

- [`artifacts/runtimes/README.md`](artifacts/runtimes/README.md) - staging native binaries locally before `dotnet pack`.
- [`.github/workflows/build-test-pack.yml`](.github/workflows/build-test-pack.yml) - the CI pipeline that builds, tests and packages all six supported platforms.

## Provenance and license

BulletSharp.Double is a fork of [BulletSharpPInvoke](https://github.com/AndresTraks/BulletSharpPInvoke) by Andres Traks, restructured and extended by [Vojnar Autonomous s.r.o.](https://vojnarautonomous.com/) toward double precision, ABI-correctness fixes, and multi-platform native packaging.

Zlib licensed. See [LICENSE](LICENSE) for the project's license and provenance notices, and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the full upstream license texts (BulletSharpPInvoke and bullet3).