namespace WarHub.Catalog.Publish;

// Local read-models for the new nested paint brand-archive YAML (data/paints/brands/*.yaml).
// The publisher owns its read contract; these decouple it from the paint tool's model and
// avoid a name clash with the publisher's own output PaintRecord.
internal sealed class BrandFile
{
    public string Brand { get; set; } = "";
    public string BrandSlug { get; set; } = "";
    public string Source { get; set; } = "";
    public string License { get; set; } = "";
    public List<PaintYaml> Paints { get; set; } = [];
}

internal sealed class PaintYaml
{
    public string Name { get; set; } = "";
    public string Category { get; set; } = "";
    public string Status { get; set; } = "";
    public string Availability { get; set; } = "";
    public string? FirstSeen { get; set; }
    public string? ProductCode { get; set; }
    public string? Ean { get; set; }
    public string? ImageUrl { get; set; }
    public PaintDetailsYaml Details { get; set; } = new();
}

internal sealed class PaintDetailsYaml
{
    public string Set { get; set; } = "";
    public int R { get; set; }
    public int G { get; set; }
    public int B { get; set; }
    public string Hex { get; set; } = "";
    public int? VolumeMl { get; set; }
    public string? Container { get; set; }
    public string? Type { get; set; }
    public string? Finish { get; set; }
}
