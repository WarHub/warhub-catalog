using WarHub.PaintCatalog.Tool.Models;

namespace WarHub.PaintCatalog.Tool.Reconcile;

/// <summary>Builds the archival <see cref="PaintRecord"/> from the flat working <see cref="Paint"/>.</summary>
public static class PaintRecordMapper
{
    public static PaintRecord ToRecord(Paint p) => new()
    {
        Name = p.Name,
        Category = "paint",
        Status = p.IsDiscontinued ? "discontinued" : "current",
        Availability = p.IsDiscontinued ? "out_of_stock" : "unknown",
        FirstSeen = null, // reconciler stamps write-once firstSeen
        ProductCode = p.ProductCode,
        Ean = p.Ean,
        ImageUrl = p.ImageUrl,
        Details = new PaintDetails
        {
            Set = p.Set,
            R = p.R,
            G = p.G,
            B = p.B,
            Hex = p.Hex,
            VolumeMl = p.VolumeMl,
            Container = p.Packaging,
            Type = p.Type,
            Finish = p.Finish,
        },
    };
}
