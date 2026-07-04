namespace WarHub.PaintCatalog.Tool.ColorScience;

/// <summary>
/// CIELAB color space conversion from sRGB.
/// Uses D65 illuminant (standard for sRGB).
/// </summary>
public static class CieLab
{
    // D65 reference white point
    private const double Xn = 0.95047;
    private const double Yn = 1.00000;
    private const double Zn = 1.08883;

    /// <summary>
    /// Converts sRGB values (0-255) to CIELAB (L*, a*, b*).
    /// </summary>
    public static (double L, double A, double B) FromRgb(int r, int g, int b)
    {
        // sRGB to linear RGB
        double rLin = SrgbToLinear(r / 255.0);
        double gLin = SrgbToLinear(g / 255.0);
        double bLin = SrgbToLinear(b / 255.0);

        // Linear RGB to XYZ (sRGB matrix, D65)
        double x = 0.4124564 * rLin + 0.3575761 * gLin + 0.1804375 * bLin;
        double y = 0.2126729 * rLin + 0.7151522 * gLin + 0.0721750 * bLin;
        double z = 0.0193339 * rLin + 0.1191920 * gLin + 0.9503041 * bLin;

        // XYZ to CIELAB
        double fx = LabF(x / Xn);
        double fy = LabF(y / Yn);
        double fz = LabF(z / Zn);

        double l = 116.0 * fy - 16.0;
        double a = 500.0 * (fx - fy);
        double bStar = 200.0 * (fy - fz);

        return (l, a, bStar);
    }

    /// <summary>
    /// sRGB companding: inverse gamma for sRGB.
    /// </summary>
    private static double SrgbToLinear(double c)
    {
        return c <= 0.04045
            ? c / 12.92
            : Math.Pow((c + 0.055) / 1.055, 2.4);
    }

    /// <summary>
    /// CIELAB f(t) function.
    /// </summary>
    private static double LabF(double t)
    {
        const double delta = 6.0 / 29.0;
        const double deltaCubed = delta * delta * delta; // ≈ 0.008856

        return t > deltaCubed
            ? Math.Cbrt(t)
            : t / (3.0 * delta * delta) + 4.0 / 29.0;
    }
}
