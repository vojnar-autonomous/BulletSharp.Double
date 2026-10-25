using System;
using System.Runtime.InteropServices;
using BulletSharp;
using BulletSharp.Math;
using NUnit.Framework;

namespace BulletSharpTest
{
    // BulletSharp.Double exists to carry full IEEE-754 double precision from
    // the managed API, through the native P/Invoke boundary, into bullet3's
    // own double-precision build (BT_USE_DOUBLE_PRECISION) and back. The rest
    // of this test project exercises ordinary Bullet behavior; these tests
    // specifically probe things that would only break *because* of the
    // double-precision switch -- a struct quietly narrowed to float
    // somewhere in the marshaling, or drift that only shows up far from the
    // origin or after many accumulated steps.
    [TestFixture]
    [Category("DoublePrecision")]
    public class DoublePrecisionTests
    {
        // More significant decimal digits than a 32-bit float can hold
        // (~7 digits). If anything on the native/managed boundary silently
        // narrowed to float, these would come back rounded.
        private const double HighPrecisionX = 123456789.123456;
        private const double HighPrecisionY = -987654321.654321;
        private const double HighPrecisionZ = 555555555.555555;

        [Test]
        public void Vector3IsThreeDoublesTest()
        {
            // 3 x 8 bytes. Native btVector3 always carries a hidden 4th
            // padding scalar for SIMD alignment -- even in the double-
            // precision/non-SSE build, see bullet3's btVector3.h -- but
            // libbulletc's btVector3_copy/BTVECTOR3_COPY only ever reads or
            // writes the first 3, so this managed struct must stay exactly
            // 24 bytes, not 32, or every element-wise copy across the P/
            // Invoke boundary would misalign.
            Assert.That(Marshal.SizeOf<Vector3>(), Is.EqualTo(3 * sizeof(double)));
        }

        [Test]
        public void MatrixIsSixteenDoublesTest()
        {
            Assert.That(Marshal.SizeOf<Matrix>(), Is.EqualTo(16 * sizeof(double)));
        }

        [Test]
        public void HighPrecisionTransformRoundTripIsExactTest()
        {
            using (var context = new PhysicsContext())
            {
                context.InitializeWorld();
                using (var shape = new BoxShape(1))
                {
                    RigidBody body = context.AddBody(shape, Matrix.Identity, 1);
                    try
                    {
                        Matrix transform = body.WorldTransform;
                        transform.Origin = new Vector3(HighPrecisionX, HighPrecisionY, HighPrecisionZ);
                        body.WorldTransform = transform;

                        Vector3 readBack = body.WorldTransform.Origin;

                        // Exact equality, not Within(tolerance): any float32
                        // truncation anywhere in the round trip would shift
                        // these by a measurable amount (float32 can't hold
                        // 9 significant decimal digits), so an exact match
                        // is the actual, meaningful assertion here.
                        Assert.That(readBack.X, Is.EqualTo(HighPrecisionX));
                        Assert.That(readBack.Y, Is.EqualTo(HighPrecisionY));
                        Assert.That(readBack.Z, Is.EqualTo(HighPrecisionZ));
                    }
                    finally
                    {
                        body.Dispose();
                    }
                }
            }
        }

        [Test]
        public void FreeFallFarFromOriginMatchesClosedFormTest()
        {
            const double timeStep = 1.0 / 240.0;
            const int steps = 2000;
            const double gravityY = -9.81;

            // Far enough from the origin that float32's ~7 significant
            // digits would already be coarser than a metre. Double
            // precision should carry this exactly, with zero drift on the
            // axes gravity never touches.
            const double farX = 50_000_000.0;
            const double farZ = -12_345_678.0;

            using (var context = new PhysicsContext())
            {
                context.InitializeWorld();
                context.World.Gravity = new Vector3(0, gravityY, 0);

                using (var shape = new SphereShape(0.5f))
                {
                    RigidBody body = context.AddBody(shape, Matrix.Translation(farX, 0, farZ), 1);
                    body.ForceActivationState(ActivationState.DisableDeactivation);
                    try
                    {
                        for (int i = 0; i < steps; i++)
                        {
                            context.World.StepSimulation(timeStep, 1, timeStep);
                        }

                        // Bullet's rigid body integrator is semi-implicit
                        // (symplectic) Euler: v += g*h each step, then
                        // x += v*h. Reproduce that exact discrete recurrence
                        // in plain C# double arithmetic as the expected
                        // value, so this compares double-precision
                        // accumulation against itself rather than against a
                        // continuous-time formula the integrator never
                        // promised to match.
                        double v = 0.0;
                        double expectedY = 0.0;
                        for (int i = 0; i < steps; i++)
                        {
                            v += gravityY * timeStep;
                            expectedY += v * timeStep;
                        }

                        Vector3 finalPosition = body.WorldTransform.Origin;
                        Vector3 finalVelocity = body.LinearVelocity;

                        Assert.That(finalVelocity.Y, Is.EqualTo(v).Within(Math.Abs(v) * 1e-9));
                        Assert.That(finalPosition.Y, Is.EqualTo(expectedY).Within(Math.Abs(expectedY) * 1e-6));

                        // No force acts on X/Z: a coordinate this large must
                        // come back bit-for-bit unchanged, not merely
                        // "close" -- any drift here would mean the far-
                        // from-origin magnitude itself is corrupting
                        // precision somewhere in the step.
                        Assert.That(finalPosition.X, Is.EqualTo(farX));
                        Assert.That(finalPosition.Z, Is.EqualTo(farZ));
                    }
                    finally
                    {
                        body.Dispose();
                    }
                }
            }
        }
    }
}
