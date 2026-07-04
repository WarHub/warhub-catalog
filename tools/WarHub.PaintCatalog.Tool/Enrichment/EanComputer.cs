using System.Text.RegularExpressions;

namespace WarHub.PaintCatalog.Tool.Enrichment;

/// <summary>
/// Computes EAN-13 barcodes for Vallejo paints from their product codes.
/// Formula: "8429551" + 5-digit code (remove dot) + check digit.
/// </summary>
public static partial class EanComputer
{
    private const string VallejoPrefix = "8429551";

    [GeneratedRegex(@"^\d{2}\.\d{3}$")]
    private static partial Regex VallejoCodePattern();

    /// <summary>
    /// Computes an EAN-13 barcode for a Vallejo paint product code.
    /// Returns null if the code is not a valid Vallejo format (XX.XXX).
    /// </summary>
    public static string? ComputeVallejoEan(string? productCode)
    {
        if (productCode is null) return null;

        if (!VallejoCodePattern().IsMatch(productCode))
            return null;

        // Remove dot: "70.950" → "70950"
        string digits = productCode.Replace(".", "");

        // Build first 12 digits: prefix (7) + code (5) = 12
        string partial = VallejoPrefix + digits;

        if (partial.Length != 12)
            return null;

        int checkDigit = ComputeCheckDigit(partial);
        return partial + checkDigit;
    }

    /// <summary>
    /// Computes the EAN-13 check digit for a 12-digit string.
    /// </summary>
    public static int ComputeCheckDigit(string first12Digits)
    {
        if (first12Digits.Length != 12)
            throw new ArgumentException("Must be exactly 12 digits.", nameof(first12Digits));

        int sum = 0;
        for (int i = 0; i < 12; i++)
        {
            int digit = first12Digits[i] - '0';
            int weight = (i % 2 == 0) ? 1 : 3;
            sum += digit * weight;
        }

        return (10 - (sum % 10)) % 10;
    }
}
