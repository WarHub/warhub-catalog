namespace WarHub.PaintCatalog.Tool.Models;

/// <summary>
/// Archival paint record: shared storage core at top level, paint-specific
/// color/physical fields nested under <see cref="Details"/>. This is the only
/// shape written to disk / reconciled / ledgered. Built from the flat working
/// <see cref="Paint"/> by PaintRecordMapper. Property order drives YAML order.
/// </summary>
public record PaintRecord
{
    public required string Name { get; init; }
    /// <summary>Constant "paint" for this catalog.</summary>
    public required string Category { get; init; }
    /// <summary>Archival lifecycle: current | suspected-discontinued | discontinued | delisted.</summary>
    public required string Status { get; init; }
    /// <summary>Volatile purchasability: in_stock | out_of_stock | pre_order | limited | unknown.</summary>
    public required string Availability { get; init; }
    /// <summary>
    /// WHETHER THE MANUFACTURER SELLS THIS POT ON ITS OWN. `null` -- the overwhelming default --
    /// means no source said, which is a different claim from "yes". `false` means a source stated
    /// the paint exists ONLY inside a boxed set.
    ///
    /// Deliberately NOT a `status` or `availability` value, for the reason `supersedes` gives a few
    /// lines down: those are free strings every consumer filters on, and a new value in them would
    /// silently drop exactly the records this exists to keep reachable. A sibling field is additive
    /// -- a consumer that has never heard of it behaves as before.
    ///
    /// The record it was added for is ak-interactive AK17082 "Wolf Blue Grey", which Warlord's own
    /// listing for the Winter Blue Soldiers set spells out: "Special color only for this set - not
    /// sold separately." Without this field the catalog would publish it as `current` / `unknown`,
    /// i.e. indistinguishable from a pot you can walk in and buy -- which is worse than silence for
    /// the one person most likely to look it up, somebody holding the bottle and reading the label.
    ///
    /// NOTHING WRITES `true`, deliberately. No source states the positive; a listed product's
    /// separate availability is implied by its having a page, and stamping `true` on all 8,461
    /// records (measured 2026-08-11; exactly one of them, AK17082, states anything at all) would
    /// assert a fact no source states -- the same argument set-member `quantity` loses on. `true`
    /// is reserved for a source that ever says it in words.
    /// </summary>
    public bool? SoldSeparately { get; init; }

    /// <summary>
    /// This product HAS no colour: a mixing medium, thinner, varnish, sealer, flow improver,
    /// retarder or cleaner. A sibling field for the same reason <see cref="SoldSeparately"/> is
    /// one -- a consumer that has never heard of it behaves exactly as before.
    ///
    /// IT EXISTS BECAUSE AN EMPTY HEX ALREADY MEANS SOMETHING ELSE. `hex: ""` is the pipeline's
    /// word for "colour not yet known": <see cref="Enrichment.SwatchApplier"/> fills exactly those
    /// records from the next chart pass, and the publisher omits the key so a consumer reads it as
    /// absent rather than as black. Measured 2026-08-13 across the archive: of 391 hexless records
    /// only 68 are utility products -- the other 323 are ordinary colours awaiting extraction. So
    /// blanking a varnish says "come back and fill this in", which is the opposite of the truth,
    /// and the next chart pass duly does.
    ///
    /// The alternative the archive actually used was worse: 94 of 145 such records carried a
    /// STAND-IN, 48 of them exactly #FFFFFF and 92 of 94 neutral to within 12 per channel. Those
    /// are not colours, and nothing downstream could tell. They entered the equivalence graph as
    /// real ones -- <see cref="Equivalence.EquivalenceFinder"/> admits any non-empty hex -- so
    /// data/paints/equivalences.yaml published a clear brush-on sealer as a deltaE 0 `close` match
    /// for five white paints, 310 such rows in total, with 25 utility names appearing 216 times as
    /// the TARGET of somebody else's colour match.
    ///
    /// So the field is an assertion, and the hex is its consequence: `colourless: true` clears the
    /// hex and zeroes R/G/B in <see cref="Enrichment.OverrideApplier"/>, which runs after the
    /// swatch pass and therefore also undoes any fill that pass made. `null` means unstated, as
    /// with SoldSeparately; nothing writes `false`.
    /// </summary>
    public bool? Colourless { get; init; }

    /// <summary>
    /// WHAT THE PRODUCT IS FOR. `category` is the constant `paint` for everything a maker's
    /// chart lists -- colour or not, since 2026-09-02 -- so this is the key that tells a varnish
    /// from a colour: `colour` (deposits colour; the finer grain stays in <see cref="PaintDetails.Type"/>
    /// and <see cref="PaintDetails.Finish"/>), `primer`, `varnish`, `medium`, `cleaner`,
    /// `texture`, `pigment`, and the hobby-hardware values a chart should never list but a
    /// harvest can (`applicator`, `tool`, `basing`, `build`). The closed vocabulary lives in
    /// <see cref="Enrichment.RoleClassifier"/>, which derives the value from brand, range and
    /// name every run; a `role:` line in overrides.yaml outranks it per record.
    ///
    /// Sits beside <see cref="Colourless"/> because the two are one fact stated twice: a varnish,
    /// medium or cleaner HAS no colour, so a record carrying one of those roles must carry the
    /// flag, and a flagged record cannot be a `colour`. <see cref="Enrichment.RoleInvariant"/>
    /// holds that over every record the tool writes and fails the run otherwise -- the flag is
    /// what keeps the record out of the colour-equivalence graph, the role is what says why.
    ///
    /// Nullable in the type only because the working shape cannot promise a value before the
    /// classifier has run; every archived record carries one, and the invariant treats a missing
    /// role as a violation. A sibling field for the reason <see cref="SoldSeparately"/> is one:
    /// a consumer that has never heard of it behaves as before.
    /// </summary>
    public string? Role { get; init; }

    /// <summary>Write-once, immutable.</summary>
    public string? FirstSeen { get; init; }
    public string? ProductCode { get; init; }
    public string? Ean { get; init; }
    /// <summary>
    /// Further barcodes the SAME paint is sold under beyond the primary <see cref="Ean"/>, so a
    /// scan of any of them still identifies this paint. Today these are concurrent REGIONAL trade
    /// variants (e.g. a spray sold as both an R/O-Europe and a UK/ROW SKU with one shared SSC
    /// code), NOT retired barcodes -- do not present them as superseded. Null (never an empty
    /// list) when there is only one barcode, so the key is omitted from the archive YAML.
    ///
    /// Declared as <c>List</c>, not <c>IReadOnlyList</c>: YamlDotNet SERIALIZES a read-only list
    /// happily but has no node deserializer for one, so the archive wrote a shape it could not read
    /// back. That is invisible until a record actually gains the key -- which happened the first
    /// time the bridge matched the 9 regional spray pairs, and the very next load of
    /// citadel-colour.yaml then died with "No node deserializer was able to deserialize the node
    /// into type IReadOnlyList&lt;String&gt;" at the first `additionalEans` entry. Any list property
    /// added to this archival record must be round-trip tested, not just written.
    /// </summary>
    public List<string>? AdditionalEans { get; init; }
    public string? ImageUrl { get; init; }
    /// <summary>
    /// Manufacturer list price per currency, from the trade bridge or a hand override. Note that
    /// <see cref="Availability"/> deliberately does NOT come from the same evidence: trade sheets
    /// carry no stock signal, and one paint identity spans several retail SKUs with different stock.
    /// </summary>
    public decimal? PriceGbp { get; init; }
    public decimal? PriceUsd { get; init; }
    public decimal? PriceEur { get; init; }
    public decimal? PriceCad { get; init; }
    /// <summary>
    /// Archival lineage between two paint identities for the same colour (a reformulation moved
    /// into another range). BOTH records are kept: the retired one keeps its own set/volume/code
    /// and points forward with <see cref="SupersededBy"/>, the replacement lists its predecessors
    /// in <see cref="Supersedes"/>. Stored as the <c>{Name}|{Set}</c> cross-reference key used
    /// everywhere else in this tool; the publisher resolves it to a published id. Mirrors
    /// ProductRecord: the relation is deliberately NOT encoded in <see cref="Status"/>, which every
    /// consumer filters on and would hide exactly the archival record this keeps reachable.
    /// </summary>
    public List<string>? Supersedes { get; init; }
    public string? SupersededBy { get; init; }
    public required PaintDetails Details { get; init; }
}

/// <summary>Paint-specific color/physical fields (the category extension block).</summary>
public record PaintDetails
{
    public required string Set { get; init; }
    public required int R { get; init; }
    public required int G { get; init; }
    public required int B { get; init; }
    public required string Hex { get; init; }
    public int? VolumeMl { get; init; }
    /// <summary>
    /// NET CONTENTS in grams, for the products sold by mass rather than by volume -- not the
    /// gross shipping weight, which the Shopify evidence carries on 1,843 observations and which
    /// must never feed this. A sibling of <see cref="VolumeMl"/> in the style of the four
    /// <c>price*</c> scalars above: the unit is in the name, both may be stated, and a consumer
    /// that ignores this field behaves exactly as it did before it existed. <c>int</c> because
    /// every mass observed anywhere in this repo is integral (250 gr, 400 g, 15 g) and
    /// <see cref="VolumeMl"/> is already <c>int</c>; widening later is additive.
    ///
    /// Measured 2026-08-06: 2 of 8,547 committed records are sold by mass (Green Stuff World
    /// `Foam Primer and Coat - Black/Grey 250gr`). That is the whole population, not a sample --
    /// hobby pigments, weathering powders and basing sands are sold by JAR VOLUME in this corpus:
    /// re-measured 2026-08-07 over all 21 brand files, 283 records match pigment/powder/paste/
    /// putty/sand/glue in their set OR their name, 217 of them state a volume and ZERO state a
    /// mass. (An earlier draft of this comment said "317 records: 3 state a volume", which was
    /// wrong by roughly seventyfold AND inverted the fact it was quoting -- these records
    /// overwhelmingly DO carry a volume, which is the whole point.) The field exists because the
    /// write path could not say "no volume", not because a large repair was waiting.
    /// </summary>
    public int? WeightG { get; init; }
    /// <summary>Bottle type (dropper | pot | spray | ...). Was the legacy `packaging` field.</summary>
    public string? Container { get; init; }
    public string? Type { get; init; }
    public string? Finish { get; init; }
}

/// <summary>Per-brand archival file envelope. No derived counts (recomputed at publish).</summary>
public record BrandArchive
{
    public required string Brand { get; init; }
    public required string BrandSlug { get; init; }
    public string Source { get; init; } = "Arcturus5404/miniature-paints";
    public string License { get; init; } = "MIT";
    public required List<PaintRecord> Paints { get; init; }
}
