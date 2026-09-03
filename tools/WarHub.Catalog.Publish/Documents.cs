using System.Text.Json;
using System.Text.Json.Serialization;

namespace WarHub.Catalog.Publish;

/// <summary>
/// Output document model for the published catalog. This project owns the public
/// schema; the shapes here are what clients consume (camelCase JSON). Every data
/// document carries a self-describing envelope (version / provenance) plus its payload.
/// </summary>
internal static class JsonConfig
{
    public static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        WriteIndented = false,
    };
}

internal sealed record Partition(string Type, string Key, string Label);

internal sealed record ReleaseRef(string Tag, string Url);

internal sealed record SourceRef(string Repo, ReleaseRef? Release = null, string? PageUrl = null);

/// <summary>
/// A retail product. <c>ean</c> is optional — not every product carries a barcode. A product
/// genuinely repackaged over time (same contents, new box/barcode) carries its extra barcodes in
/// <c>additionalEans</c>; <c>ean</c> stays the single primary barcode for existing consumers.
/// </summary>
internal sealed record ProductRecord
{
    // Id + Manufacturer are published so an archival/lineage link (supersededBy / supersedes) has
    // a stable target to point at -- the resolver's entity id, `manufacturer/<code-or-slug>`.
    [JsonPropertyOrder(0)] public required string Id { get; init; }
    [JsonPropertyOrder(0)] public required string Manufacturer { get; init; }
    [JsonPropertyOrder(1)] public string? Ean { get; init; }
    [JsonPropertyOrder(1)] public IReadOnlyList<string>? AdditionalEans { get; init; }
    // The maker's OTHER codes for this same box -- a re-code that kept the barcode, or a second
    // store of the maker's numbering it differently. `productCode` stays the single canonical code;
    // these still name the product. Null (omitted) for the single-code majority.
    [JsonPropertyOrder(1)] public IReadOnlyList<string>? AdditionalCodes { get; init; }
    [JsonPropertyOrder(2)] public required string Name { get; init; }
    // LABELS, one per game system this product belongs to, in the canonical slug order the
    // resolver wrote. Null rather than `[]` when there are none, so a systemless product publishes
    // no property at all -- the same treatment `category` gets.
    [JsonPropertyOrder(3)] public IReadOnlyList<string>? GameSystems { get; init; }
    // LABELS, one per SETTING -- the universe or period -- this product belongs to. For a product
    // with game systems these are the settings those games are set in; a product with none can
    // still carry one (a novel, a period terrain piece). Null when there are none, like the rest.
    [JsonPropertyOrder(3)] public IReadOnlyList<string>? Settings { get; init; }
    [JsonPropertyOrder(4)] public string? Faction { get; init; }
    // Nullable, and the publisher no longer substitutes anything for it. A product whose category
    // nothing ever stated publishes `category: null` -- the same treatment `gameSystem` gets, for
    // the same reason: a filled-in `miniatures` is indistinguishable from a stated one, so the
    // consumer cannot tell the catalog's knowledge from its default. See
    // models/catalog.py::categoryBasis.
    [JsonPropertyOrder(5)] public string? Category { get; init; }
    [JsonPropertyOrder(6)] public required string Status { get; init; }
    [JsonPropertyOrder(7)] public required string Availability { get; init; }
    [JsonPropertyOrder(8)] public int Quantity { get; init; }
    [JsonPropertyOrder(9)] public string? ProductCode { get; init; }
    [JsonPropertyOrder(10)] public string? Url { get; init; }
    [JsonPropertyOrder(11)] public string? ImageUrl { get; init; }
    [JsonPropertyOrder(12)] public string? EanConfidence { get; init; }
    [JsonPropertyOrder(13)] public decimal? PriceGbp { get; init; }
    [JsonPropertyOrder(14)] public decimal? PriceUsd { get; init; }
    [JsonPropertyOrder(15)] public decimal? PriceEur { get; init; }
    [JsonPropertyOrder(16)] public decimal? PriceCad { get; init; }
    // Unit volume in millilitres, for paints/sprays (e.g. 12, 18, 24, 400). Null for everything else.
    [JsonPropertyOrder(17)] public int? VolumeMl { get; init; }
    // Unit NET WEIGHT in grams, for the things sold by mass rather than volume (glue, basing sand).
    // Mirrors the paint record's field so the cross-catalog seam cannot disagree with itself: a
    // barcode that resolves to both a paint and a product (paintIds/productIds, CrossCatalogLinks)
    // would otherwise publish net contents on one side and silence on the other for one physical
    // tub. Measured 2026-08-06: 3 of 22,529 products name a mass (2 GW plastic glue SKUs at 15 g,
    // 1 Mantic basing sand at 400 g) and NONE of them carries a volume, so unlike the paint side
    // nothing here is currently wrong -- this closes an absence, not an error.
    [JsonPropertyOrder(17)] public int? WeightG { get; init; }
    // Archival lineage between two product codes for the same product (a re-code, a repackaging).
    // BOTH records are published: a retired one keeps its own productCode/ean and points forward
    // with <c>supersededBy</c>; the current one lists its predecessors in <c>supersedes</c>. So a
    // decade-old box still scans to a record, and that record says what replaced it. Note the
    // relation is NOT encoded in <c>status</c> -- a consumer filtering on status keeps working
    // unchanged, and a retired record's status is still whatever the evidence says it is.
    [JsonPropertyOrder(18)] public IReadOnlyList<string>? Supersedes { get; init; }
    [JsonPropertyOrder(19)] public string? SupersededBy { get; init; }
    // The product this web bundle contains -- a maker's "rulebook with special miniature" listing
    // that quotes the book's ISBN. The bundle publishes no barcode of the book's and points at it.
    // Null (omitted) for everything that is not a declared bundle.
    [JsonPropertyOrder(19)] public string? BundleOf { get; init; }
    // Cross-catalog seam: the paint records that share a barcode with this product. Plural
    // because neither side is 1:1 -- one colour ships as many SKUs, and a barcode can be
    // carried by more than one record on either side. Null (omitted) when there is no link.
    // See CrossCatalogLinks for how it is computed and why it is emitted, not assumed.
    [JsonPropertyOrder(20)] public IReadOnlyList<string>? PaintIds { get; init; }
}

/// <summary>A cross-brand near match; lower <c>deltaE</c> is closer.</summary>
internal sealed record PaintEquivalent(
    [property: JsonPropertyOrder(1)] string Id,
    [property: JsonPropertyOrder(2)] double DeltaE,
    [property: JsonPropertyOrder(3)] string? Tier);

/// <summary>A single paint. <c>id</c> is the stable global key (<c>brand-slug/paint-slug</c>).</summary>
internal sealed record PaintRecord(
    [property: JsonPropertyOrder(1)] string Id,
    [property: JsonPropertyOrder(2)] string Brand,
    [property: JsonPropertyOrder(3)] string Category,
    // WHAT THE PRODUCT IS FOR: colour | primer | varnish | medium | cleaner | texture | pigment,
    // plus applicator | tool | basing | build for the hardware a chart should never list. Since
    // 2026-09-02 `category` is the constant `paint` for everything a maker's chart lists,
    // colour or not, so this is the key that tells a varnish from a colour; a colour's finer
    // grain (wash, contrast, metallic) stays in `type`/`finish` and is never repeated here.
    // Emitted right after `category` because it is the other half of the same question; the
    // same JsonPropertyOrder as `category` is deliberate -- ties keep declaration order, which
    // `ean`/`additionalEans` below already rely on.
    [property: JsonPropertyOrder(3)] string? Role,
    [property: JsonPropertyOrder(4)] string? Range,
    [property: JsonPropertyOrder(5)] string Name,
    // Null = colour not yet known (harvested additions await chart-swatch extraction); the
    // property is omitted from the JSON entirely rather than published as "".
    [property: JsonPropertyOrder(6)] string? Hex,
    [property: JsonPropertyOrder(7)] string? Type,
    [property: JsonPropertyOrder(8)] string? Finish,
    [property: JsonPropertyOrder(9)] int? VolumeMl,
    // NET CONTENTS in grams for the products sold by mass instead of by volume -- 2 paints as of
    // 2026-08-06, both Green Stuff World foam-primer tubs. A SIBLING of volumeMl, in the style of
    // the four price scalars below: the unit is in the name, both may be present (a pigment
    // weighed into a jar of stated size), and a consumer that never reads it behaves exactly as it
    // did before the field existed. Deliberately NOT a {unit, amount} pair or a repurposed
    // volumeMl -- either would force every existing reader of volumeMl to be rewritten and would
    // have to migrate 7,903 values for a 2-record problem.
    [property: JsonPropertyOrder(9)] int? WeightG,
    [property: JsonPropertyOrder(10)] string? Container,
    // ean/productCode are the manufacturer's retail identifiers, optional (only some brands supply
    // them -- currently GW/Citadel via the trade-barcode bridge, and Vallejo via computed EAN).
    [property: JsonPropertyOrder(11)] string? ProductCode,
    [property: JsonPropertyOrder(12)] string? Ean,
    // Further barcodes the same paint is sold under (today: concurrent regional trade variants),
    // so a scan of any of them resolves. Mirrors ProductRecord.AdditionalEans; null -> omitted.
    [property: JsonPropertyOrder(12)] IReadOnlyList<string>? AdditionalEans,
    // Product/swatch image from the manufacturer or a harvested catalog page.
    [property: JsonPropertyOrder(13)] string? ImageUrl,
    // Manufacturer list price, mirroring ProductRecord. Availability deliberately does NOT come
    // with it: the trade evidence that carries paint prices carries no stock signal at all, and one
    // paint identity spans several retail SKUs whose stock differs.
    [property: JsonPropertyOrder(14)] decimal? PriceGbp,
    [property: JsonPropertyOrder(15)] decimal? PriceUsd,
    [property: JsonPropertyOrder(16)] decimal? PriceEur,
    [property: JsonPropertyOrder(17)] decimal? PriceCad,
    [property: JsonPropertyOrder(18)] string Status,
    [property: JsonPropertyOrder(19)] string Availability,
    // `false` when a source states this pot is only available inside a boxed set; ABSENT
    // whenever no source said, which is nearly always and is a different claim from `true`.
    // A consumer that has never heard of this field sees exactly what it saw before -- which
    // is the point of it being a sibling rather than a new `availability` value, the same
    // reasoning `supersedes` records just below.
    [property: JsonPropertyOrder(19)] bool? SoldSeparately,
    // `true` when the product is a medium, thinner, varnish or other agent that HAS no colour,
    // which is why its `hex` is absent. Without it a consumer cannot tell that absence from the
    // far commoner one just above -- a colour this catalog has not harvested yet -- and 323 of
    // the 391 hexless records are the latter. Absent whenever nobody stated it.
    [property: JsonPropertyOrder(20)] bool? Colourless,
    // Archival lineage between two paint identities for the same colour -- a reformulation that
    // moved the paint into another range keeps BOTH records: the retired one points forward with
    // `supersededBy`, the replacement lists its predecessors in `supersedes`. Values are paint ids,
    // so an old pot still resolves and says what replaced it. As on ProductRecord the relation is
    // deliberately NOT encoded in `status` -- a consumer filtering on status keeps working, and a
    // retired paint's status stays whatever the evidence says it is.
    [property: JsonPropertyOrder(20)] IReadOnlyList<string>? Supersedes,
    [property: JsonPropertyOrder(21)] string? SupersededBy,
    [property: JsonPropertyOrder(22)] IReadOnlyList<PaintEquivalent> Equivalents,
    // Cross-catalog seam: the product records that share a barcode with this paint. Plural
    // because one colour is sold as many SKUs (pot, spray, contrast, a paint-set component),
    // so a paint routinely resolves to several products. Mirrors ProductRecord.PaintIds;
    // null -> omitted. Defaulted so the link pass can fill it via `with` after assembly.
    [property: JsonPropertyOrder(23)] IReadOnlyList<string>? ProductIds = null);

// ---- Envelope-bearing documents ------------------------------------------------

internal sealed class ProductCatalogDocument
{
    [JsonPropertyOrder(0)] public string SchemaVersion { get; init; } = SchemaInfo.SchemaVersion;
    [JsonPropertyOrder(1)] public string Kind { get; init; } = "product-catalog";
    [JsonPropertyOrder(2)] public required string Version { get; init; }
    [JsonPropertyOrder(3)] public required string GeneratedAt { get; init; }
    [JsonPropertyOrder(4)] public string? GitCommit { get; init; }
    [JsonPropertyOrder(5)] public Partition? Partition { get; init; }
    [JsonPropertyOrder(6)] public required IReadOnlyDictionary<string, int> Counts { get; init; }
    [JsonPropertyOrder(7)] public required SourceRef Source { get; init; }
    [JsonPropertyOrder(8)] public required IReadOnlyList<ProductRecord> Products { get; init; }
}

internal sealed class PaintCatalogDocument
{
    [JsonPropertyOrder(0)] public string SchemaVersion { get; init; } = SchemaInfo.SchemaVersion;
    [JsonPropertyOrder(1)] public string Kind { get; init; } = "paint-catalog";
    [JsonPropertyOrder(2)] public required string Version { get; init; }
    [JsonPropertyOrder(3)] public required string GeneratedAt { get; init; }
    [JsonPropertyOrder(4)] public string? GitCommit { get; init; }
    [JsonPropertyOrder(5)] public Partition? Partition { get; init; }
    [JsonPropertyOrder(6)] public required IReadOnlyDictionary<string, int> Counts { get; init; }
    [JsonPropertyOrder(7)] public required SourceRef Source { get; init; }
    [JsonPropertyOrder(8)] public required IReadOnlyList<PaintRecord> Paints { get; init; }
}

/// <summary>One record that carries a barcode. <c>catalog</c> is <c>product</c> or <c>paint</c>.</summary>
internal sealed record BarcodeRef(
    [property: JsonPropertyOrder(1)] string Catalog,
    [property: JsonPropertyOrder(2)] string Id);

/// <summary>
/// The cross-catalog barcode index: every barcode in either catalog, mapped to the records that
/// carry it. Keyed by the barcode itself so a scanner does one lookup, not a scan. A key whose
/// value names records from BOTH catalogs is the seam this document exists for -- the same
/// physical thing published twice, once as a SKU and once as a colour.
/// </summary>
internal sealed class BarcodeIndexDocument
{
    [JsonPropertyOrder(0)] public string SchemaVersion { get; init; } = SchemaInfo.SchemaVersion;
    [JsonPropertyOrder(1)] public string Kind { get; init; } = "barcode-index";
    [JsonPropertyOrder(2)] public required string Version { get; init; }
    [JsonPropertyOrder(3)] public required string GeneratedAt { get; init; }
    [JsonPropertyOrder(4)] public string? GitCommit { get; init; }
    [JsonPropertyOrder(6)] public required IReadOnlyDictionary<string, int> Counts { get; init; }
    [JsonPropertyOrder(7)] public required SourceRef Source { get; init; }
    // Dictionary keys are NOT camelCased -- JsonSerializerOptions.PropertyNamingPolicy applies to
    // property names only, DictionaryKeyPolicy is unset, so barcodes pass through verbatim.
    [JsonPropertyOrder(8)] public required IReadOnlyDictionary<string, IReadOnlyList<BarcodeRef>> Barcodes { get; init; }
}

/// <summary>
/// One paint inside a boxed set. <c>paintId</c> is the contract; everything else is the audit
/// trail for how this row was reached.
///
/// Deliberately NOT carried: the member's brand and the resolved paint's product code. Both are
/// on the paint record already, and the brand is literally the id's first segment -- restating
/// them here would give one fact two published homes that can disagree. <c>ref</c> IS carried
/// because it exists nowhere else: it is the manufacturer's own printed code, before the leading
/// zeros were stripped ('09030' resolving to productCode '9030'), and it is the only link back to
/// the <c>contentSkus</c> entry this member came from.
/// </summary>
internal sealed record SetMemberRecord(
    [property: JsonPropertyOrder(1)] string PaintId,
    [property: JsonPropertyOrder(2)] string Ref,
    // How many the source states. ABSENT MEANS THE SOURCE DID NOT SAY -- not one unit. No source
    // in this corpus states a count today (every file's counts.quantified is 0), so the key is
    // currently emitted on no member at all; it is declared because the generator can already
    // carry one and a consumer must not read the silence as "1".
    [property: JsonPropertyOrder(3)] int? Quantity,
    // Absent -- on 2,211 of 2,214 members -- means the printed code resolved to this paint on its
    // own. Present means it did NOT, and names what settled it instead: `statedName` (the set
    // listed one code twice and the name printed beside it picked the paint) or `correction` (a
    // human declared in data/catalog/set-refs.yaml that the manufacturer mistyped its own code).
    // Both keep `ref` verbatim, so the repair is visible rather than laundered.
    [property: JsonPropertyOrder(4)] string? ResolvedBy,
    [property: JsonPropertyOrder(5)] string? StatedName);

/// <summary>
/// A ref this relation could NOT turn into a paint, published rather than dropped -- a set that
/// silently listed 7 of its 8 colours would be indistinguishable from one that really has 7.
/// </summary>
internal sealed record UnresolvedRef(
    [property: JsonPropertyOrder(1)] string Ref,
    [property: JsonPropertyOrder(2)] string Reason);

/// <summary>
/// What one boxed set contains. Keyed by product id in <see cref="SetContentsDocument.Sets"/>, so
/// the id is not repeated here.
/// </summary>
internal sealed record SetRecord
{
    // A REVIEW LABEL off the product record, carried so a human reading this document alone can
    // tell which box a row is. Never join on it -- the product record is authoritative.
    [JsonPropertyOrder(1)] public required string Name { get; init; }
    // stated | description | sku -- HOW MUCH THE CONTENTS CLAIM IS WORTH, and the one field here a
    // consumer must not ignore. See the schema for what each value licenses.
    [JsonPropertyOrder(2)] public required string ContentSkusFrom { get; init; }
    // Always present, possibly empty -- like `equivalents` on a paint, and unlike the optional
    // link arrays, because "this set resolved nothing" is a fact worth stating positively.
    [JsonPropertyOrder(3)] public required IReadOnlyList<SetMemberRecord> Members { get; init; }
    // Omitted, never [], when every ref resolved.
    [JsonPropertyOrder(4)] public IReadOnlyList<UnresolvedRef>? Unresolved { get; init; }
}

/// <summary>
/// What is inside each boxed set: the product records that contain paints, mapped to the paint
/// records they contain. Keyed by product id so a consumer holding a product does one lookup.
///
/// This is the document that can only be built HERE. The upstream generator resolves each ref to
/// a paint's identity ({Name}|{Set} plus productCode) but cannot name it, because paint ids are
/// minted at publish time -- so a consumer given only the upstream file would have to rebuild the
/// id-minting rules to use it. The publisher is the one component holding both sides at once.
/// </summary>
internal sealed class SetContentsDocument
{
    [JsonPropertyOrder(0)] public string SchemaVersion { get; init; } = SchemaInfo.SchemaVersion;
    [JsonPropertyOrder(1)] public string Kind { get; init; } = "set-contents";
    [JsonPropertyOrder(2)] public required string Version { get; init; }
    [JsonPropertyOrder(3)] public required string GeneratedAt { get; init; }
    [JsonPropertyOrder(4)] public string? GitCommit { get; init; }
    [JsonPropertyOrder(6)] public required IReadOnlyDictionary<string, int> Counts { get; init; }
    [JsonPropertyOrder(7)] public required SourceRef Source { get; init; }
    // As on the barcode index, dictionary keys are NOT camelCased: DictionaryKeyPolicy is unset,
    // so product ids pass through with their manufacturer's own casing (ak-interactive/AK1063).
    [JsonPropertyOrder(8)] public required IReadOnlyDictionary<string, SetRecord> Sets { get; init; }
}

// `setting` is the universe or period this partition's game belongs to -- null on a paint index,
// and null for a catch-all game bucket that belongs to none.
/// <summary>A setting on the product index: the universe or period its game partitions belong to.</summary>
internal sealed record SettingEntry(
    [property: JsonPropertyOrder(1)] string Key,
    [property: JsonPropertyOrder(2)] string Label);

internal sealed record IndexEntry(string Key, string Label, int Records, string File, string? Setting = null);

internal sealed class IndexDocument
{
    [JsonPropertyOrder(0)] public string SchemaVersion { get; init; } = SchemaInfo.SchemaVersion;
    [JsonPropertyOrder(1)] public required string Kind { get; init; }        // product-index | paint-index
    [JsonPropertyOrder(2)] public required string Version { get; init; }
    [JsonPropertyOrder(3)] public required string GeneratedAt { get; init; }
    [JsonPropertyOrder(4)] public required string PartitionType { get; init; } // gameSystem | brand
    [JsonPropertyOrder(5)] public required int Total { get; init; }
    [JsonPropertyOrder(6)] public required IReadOnlyList<IndexEntry> Partitions { get; init; }
    // The settings the partitions above are grouped into, for a product index. Absent on a paint
    // index, whose partitions are brands and belong to no universe.
    [JsonPropertyOrder(7)] public IReadOnlyList<SettingEntry>? Settings { get; init; }
}

internal sealed record FileEntry(
    string Path, string Kind, string? Partition, int? Records, long Bytes, string Sha256);

internal sealed class ManifestDocument
{
    [JsonPropertyOrder(0)] public string SchemaVersion { get; init; } = SchemaInfo.SchemaVersion;
    [JsonPropertyOrder(1)] public string Kind { get; init; } = "manifest";
    [JsonPropertyOrder(2)] public required string Version { get; init; }
    [JsonPropertyOrder(3)] public required string GeneratedAt { get; init; }
    [JsonPropertyOrder(4)] public string? GitCommit { get; init; }
    [JsonPropertyOrder(5)] public required SourceRef Source { get; init; }
    [JsonPropertyOrder(6)] public required IReadOnlyDictionary<string, int> Counts { get; init; }
    [JsonPropertyOrder(7)] public required IReadOnlyList<FileEntry> Files { get; init; }
}

internal static class SchemaInfo
{
    public const string SchemaVersion = "1.1";
}
