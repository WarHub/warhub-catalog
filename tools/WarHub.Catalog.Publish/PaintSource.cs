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
    /// <summary>`false` when a source states the pot is only sold inside a set; null unstated.
    /// Nullable on purpose -- a non-nullable bool would read an absent key as `false`, turning
    /// 8,460 silences (of 8,461 committed records, measured 2026-08-11) into an assertion that
    /// nothing is sold on its own.</summary>
    public bool? SoldSeparately { get; set; }
    /// <summary>`true` when the product has no colour at all (medium/thinner/varnish); null
    /// unstated. Nullable for the same reason as SoldSeparately above.</summary>
    public bool? Colourless { get; set; }
    public string? FirstSeen { get; set; }
    public string? ProductCode { get; set; }
    public string? Ean { get; set; }
    public List<string>? AdditionalEans { get; set; }
    public string? ImageUrl { get; set; }
    public decimal? PriceGbp { get; set; }
    public decimal? PriceUsd { get; set; }
    public decimal? PriceEur { get; set; }
    public decimal? PriceCad { get; set; }
    // Archival lineage, stored upstream as the `{Name}|{Set}` cross-reference key. PaintBuilder
    // resolves both to published ids and drops anything it cannot resolve unambiguously, so the
    // catalog never publishes a dangling link.
    public List<string>? Supersedes { get; set; }
    public string? SupersededBy { get; set; }
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
    /// <summary>Net contents in grams; sibling of <see cref="VolumeMl"/>, never a replacement.</summary>
    public int? WeightG { get; set; }
    public string? Container { get; set; }
    public string? Type { get; set; }
    public string? Finish { get; set; }
}
