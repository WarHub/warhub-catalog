using WarHub.PaintCatalog.Tool.Models;

namespace WarHub.PaintCatalog.Tool.Reconcile;

/// <summary>Builds the archival <see cref="PaintRecord"/> from the flat working <see cref="Paint"/>.</summary>
public static class PaintRecordMapper
{
    /// <summary>
    /// The reverse: the flat working shape from an archival record. Added 2026-08-07 so the
    /// equivalence pass can run on what was actually ARCHIVED rather than on the pre-reconciliation
    /// working list -- `retract:` removes records only from the reconciler's output, so an
    /// equivalence file built from the working list names paints the archive no longer contains.
    /// Measured while retracting AK's 194 duplicates: 405 dangling sources and 1,855 dangling match
    /// rows, reproduced identically by a second full run.
    ///
    /// Lossy ON PURPOSE, and only in fields equivalence does not read: `Status`/`Availability`
    /// collapse back into <see cref="Paint.IsDiscontinued"/>, and `FirstSeen` has no home on the
    /// working shape. CIEDE2000 matching reads brand, name, set, code and hex, all of which survive.
    /// </summary>
    public static Paint ToPaint(PaintRecord r) => new()
    {
        Name = r.Name,
        Set = r.Details.Set,
        R = r.Details.R,
        G = r.Details.G,
        B = r.Details.B,
        Hex = r.Details.Hex,
        ProductCode = r.ProductCode,
        Ean = r.Ean,
        AdditionalEans = r.AdditionalEans is { Count: > 0 } extra ? [.. extra] : null,
        ImageUrl = r.ImageUrl,
        PriceGbp = r.PriceGbp,
        PriceUsd = r.PriceUsd,
        PriceEur = r.PriceEur,
        PriceCad = r.PriceCad,
        VolumeMl = r.Details.VolumeMl,
        WeightG = r.Details.WeightG,
        Packaging = r.Details.Container,
        Type = r.Details.Type,
        Finish = r.Details.Finish,
        Supersedes = r.Supersedes ?? [],
        SupersededBy = r.SupersededBy,
        IsDiscontinued = r.Status is "discontinued" or "suspected-discontinued",
    };

    public static PaintRecord ToRecord(Paint p) => new()
    {
        Name = p.Name,
        Category = "paint",
        Status = p.IsDiscontinued ? "discontinued" : "current",
        Availability = p.IsDiscontinued ? "out_of_stock" : "unknown",
        FirstSeen = null, // reconciler stamps write-once firstSeen
        ProductCode = p.ProductCode,
        Ean = p.Ean,
        AdditionalEans = p.AdditionalEans is { Count: > 0 } extra ? [.. extra] : null,
        ImageUrl = p.ImageUrl,
        PriceGbp = p.PriceGbp,
        PriceUsd = p.PriceUsd,
        PriceEur = p.PriceEur,
        PriceCad = p.PriceCad,
        Supersedes = p.Supersedes is { Count: > 0 } predecessors ? predecessors : null,
        SupersededBy = p.SupersededBy,
        Details = new PaintDetails
        {
            Set = p.Set,
            R = p.R,
            G = p.G,
            B = p.B,
            Hex = p.Hex,
            VolumeMl = p.VolumeMl,
            WeightG = p.WeightG,
            Container = p.Packaging,
            Type = p.Type,
            Finish = p.Finish,
        },
    };
}
