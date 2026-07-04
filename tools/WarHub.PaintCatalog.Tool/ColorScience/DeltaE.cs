namespace WarHub.PaintCatalog.Tool.ColorScience;

/// <summary>
/// CIEDE2000 color difference formula.
/// Reference: "The CIEDE2000 Color-Difference Formula" (Sharma, Wu, Dalal, 2005).
/// </summary>
public static class DeltaE
{
    /// <summary>
    /// Computes the CIEDE2000 Delta E between two CIELAB colors.
    /// </summary>
    public static double Ciede2000(
        (double L, double A, double B) lab1,
        (double L, double A, double B) lab2)
    {
        double l1 = lab1.L, a1 = lab1.A, b1 = lab1.B;
        double l2 = lab2.L, a2 = lab2.A, b2 = lab2.B;

        // Step 1: Calculate C'ab and h'ab
        double cab1 = Math.Sqrt(a1 * a1 + b1 * b1);
        double cab2 = Math.Sqrt(a2 * a2 + b2 * b2);
        double cabMean = (cab1 + cab2) / 2.0;

        double cabMean7 = Math.Pow(cabMean, 7);
        double g = 0.5 * (1.0 - Math.Sqrt(cabMean7 / (cabMean7 + Math.Pow(25, 7))));

        double ap1 = a1 * (1.0 + g);
        double ap2 = a2 * (1.0 + g);

        double cp1 = Math.Sqrt(ap1 * ap1 + b1 * b1);
        double cp2 = Math.Sqrt(ap2 * ap2 + b2 * b2);

        double hp1 = HueAngle(ap1, b1);
        double hp2 = HueAngle(ap2, b2);

        // Step 2: Calculate Delta L', Delta C', Delta H'
        double dLp = l2 - l1;
        double dCp = cp2 - cp1;

        double dhp;
        if (cp1 * cp2 == 0)
        {
            dhp = 0;
        }
        else if (Math.Abs(hp2 - hp1) <= 180)
        {
            dhp = hp2 - hp1;
        }
        else if (hp2 - hp1 > 180)
        {
            dhp = hp2 - hp1 - 360;
        }
        else
        {
            dhp = hp2 - hp1 + 360;
        }

        double dHp = 2.0 * Math.Sqrt(cp1 * cp2) * Math.Sin(ToRad(dhp / 2.0));

        // Step 3: Calculate CIEDE2000 components
        double lMean = (l1 + l2) / 2.0;
        double cpMean = (cp1 + cp2) / 2.0;

        double hpMean;
        if (cp1 * cp2 == 0)
        {
            hpMean = hp1 + hp2;
        }
        else if (Math.Abs(hp1 - hp2) <= 180)
        {
            hpMean = (hp1 + hp2) / 2.0;
        }
        else if (hp1 + hp2 < 360)
        {
            hpMean = (hp1 + hp2 + 360) / 2.0;
        }
        else
        {
            hpMean = (hp1 + hp2 - 360) / 2.0;
        }

        double t = 1.0
            - 0.17 * Math.Cos(ToRad(hpMean - 30))
            + 0.24 * Math.Cos(ToRad(2 * hpMean))
            + 0.32 * Math.Cos(ToRad(3 * hpMean + 6))
            - 0.20 * Math.Cos(ToRad(4 * hpMean - 63));

        double lMeanMinus50Sq = (lMean - 50) * (lMean - 50);
        double sl = 1.0 + 0.015 * lMeanMinus50Sq / Math.Sqrt(20.0 + lMeanMinus50Sq);
        double sc = 1.0 + 0.045 * cpMean;
        double sh = 1.0 + 0.015 * cpMean * t;

        double cpMean7 = Math.Pow(cpMean, 7);
        double rc = 2.0 * Math.Sqrt(cpMean7 / (cpMean7 + Math.Pow(25, 7)));

        double dTheta = 30.0 * Math.Exp(-((hpMean - 275) / 25.0) * ((hpMean - 275) / 25.0));
        double rt = -Math.Sin(ToRad(2 * dTheta)) * rc;

        // Parametric weighting factors (all 1 for standard CIEDE2000)
        const double kl = 1.0;
        const double kc = 1.0;
        const double kh = 1.0;

        double dE = Math.Sqrt(
            (dLp / (kl * sl)) * (dLp / (kl * sl)) +
            (dCp / (kc * sc)) * (dCp / (kc * sc)) +
            (dHp / (kh * sh)) * (dHp / (kh * sh)) +
            rt * (dCp / (kc * sc)) * (dHp / (kh * sh)));

        return dE;
    }

    /// <summary>
    /// Computes CIEDE2000 Delta E directly from sRGB values.
    /// </summary>
    public static double FromRgb(int r1, int g1, int b1, int r2, int g2, int b2)
    {
        var lab1 = CieLab.FromRgb(r1, g1, b1);
        var lab2 = CieLab.FromRgb(r2, g2, b2);
        return Ciede2000(lab1, lab2);
    }

    private static double HueAngle(double a, double b)
    {
        if (a == 0 && b == 0) return 0;
        double h = Math.Atan2(b, a) * (180.0 / Math.PI);
        return h >= 0 ? h : h + 360.0;
    }

    private static double ToRad(double degrees) => degrees * (Math.PI / 180.0);
}
